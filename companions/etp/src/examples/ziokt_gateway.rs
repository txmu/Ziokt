//! Explicit bounded local JSONL bridge; the operator supplies private keys and approved peers.
use base64::{engine::general_purpose::STANDARD, Engine};
use etp_core::{
    crypto::noise::KeyPair,
    network::node::{EtpEngine, NodeConfig},
    plugin::{PluginRegistry, StandardDialect},
};
use rand::RngCore;
use serde::Deserialize;
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    fs,
    io::{self, BufRead, Read, Write},
    net::SocketAddr,
    sync::Arc,
};
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    bind: SocketAddr,
    private_key: String,
    peers: HashMap<SocketAddr, String>,
    #[serde(default)]
    relay: bool,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    id: u64,
    method: String,
    params: Value,
}
fn hex_key(value: &str) -> anyhow::Result<Vec<u8>> {
    anyhow::ensure!(
        value.len() == 64 && value.bytes().all(|b| b.is_ascii_hexdigit()),
        "invalid key"
    );
    (0..64)
        .step_by(2)
        .map(|i| u8::from_str_radix(&value[i..i + 2], 16).map_err(Into::into))
        .collect()
}
#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let path = std::env::args()
        .nth(1)
        .ok_or_else(|| anyhow::anyhow!("private node configuration required"))?;
    let metadata = fs::symlink_metadata(&path)?;
    anyhow::ensure!(
        metadata.is_file() && metadata.len() <= 65536,
        "private regular config required"
    );
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        anyhow::ensure!(
            metadata.permissions().mode() & 0o077 == 0,
            "private config permissions required"
        );
    }
    let settings: Config = serde_json::from_slice(&fs::read(path)?)?;
    anyhow::ensure!(settings.peers.len() <= 128, "peer budget");
    let private = hex_key(&settings.private_key)?;
    let secret = x25519_dalek::StaticSecret::from(<[u8; 32]>::try_from(private.as_slice())?);
    let mut config = NodeConfig::default();
    config.bind_addr = settings.bind.to_string();
    config.keypair = KeyPair {
        private,
        public: x25519_dalek::PublicKey::from(&secret).as_bytes().to_vec(),
    };
    rand::rngs::OsRng.fill_bytes(&mut config.stateless_secret);
    config.max_sessions = 128;
    config.enable_onion_relay = settings.relay;
    for (address, key) in &settings.peers {
        config.trusted_peers.insert(
            *address,
            hex_key(key)?
                .try_into()
                .map_err(|_| anyhow::anyhow!("peer key length"))?,
        );
    }
    let plugins = Arc::new(PluginRegistry::new());
    plugins.register_dialect(Arc::new(StandardDialect));
    let (engine, handle, mut received) = EtpEngine::new(config, plugins).await?;
    let task = tokio::spawn(engine.run());
    let input = io::stdin();
    let mut reader = input.lock();
    let mut output = io::stdout();
    for _ in 0..4096 {
        let mut frame = Vec::new();
        let count = Read::by_ref(&mut reader)
            .take(131073)
            .read_until(b'\n', &mut frame)?;
        if count == 0 {
            break;
        }
        anyhow::ensure!(
            frame.len() <= 131072 && frame.last() == Some(&b'\n'),
            "bounded JSONL frame required"
        );
        let request: Request = serde_json::from_slice(&frame)?;
        anyhow::ensure!(request.id < (1u64 << 53), "correlation bound");
        let result:Result<Value,anyhow::Error>=async {match request.method.as_str(){
   "etp.stats"=>{anyhow::ensure!(request.params==json!({}),"exact stats request");Ok(json!({"schema":"ziokt.etp-stats.v1","native":handle.get_stats().await?}))},
   "etp.onion.send"=>{
    let object=request.params.as_object().ok_or_else(||anyhow::anyhow!("object required"))?;anyhow::ensure!(object.len()==2,"exact onion frame");
    let hops=object.get("hops").and_then(Value::as_array).ok_or_else(||anyhow::anyhow!("hops required"))?;anyhow::ensure!((2..=4).contains(&hops.len()),"2..4 hops required");
    let mut path=Vec::new();for item in hops {let address:SocketAddr=item.as_str().ok_or_else(||anyhow::anyhow!("literal peer required"))?.parse()?;anyhow::ensure!(!path.iter().any(|(a,_)|*a==address),"repeated peer");let key=settings.peers.get(&address).ok_or_else(||anyhow::anyhow!("peer not approved"))?;path.push((address,hex_key(key)?));}
    let data=STANDARD.decode(object.get("ciphertext").and_then(Value::as_str).ok_or_else(||anyhow::anyhow!("ciphertext required"))?)?;anyhow::ensure!(data.len()>=16384&&data.len()<=65536&&data.len().is_power_of_two(),"padded sealed object required");handle.send_onion(path,data).await?;Ok(json!({"accepted":true,"delivery_confirmed":false,"direct_fallback":false}))
   },
   "etp.receive"=>{anyhow::ensure!(request.params==json!({}),"exact receive request");match tokio::time::timeout(std::time::Duration::from_secs(5),received.recv()).await {Ok(Some((_address,bytes)))=>{anyhow::ensure!(bytes.len()<=65536,"receive budget");Ok(json!({"ciphertext":bytes.chunks(3072).map(|chunk|STANDARD.encode(chunk)).collect::<Vec<_>>()}))},_=>Ok(json!({"ciphertext":null}))}},
   "etp.shutdown"=>{handle.shutdown().await?;Ok(json!({"stopped":true}))},
   _=>Err(anyhow::anyhow!("unsupported operation"))
  }}.await;
        let response = match result {
            Ok(result) => json!({"id":request.id,"ok":true,"result":result}),
            Err(_) => json!({"id":request.id,"ok":false,"error":{"code":"ETP_REJECTED"}}),
        };
        writeln!(output, "{}", response)?;
        output.flush()?;
        if request.method == "etp.shutdown" {
            break;
        }
    }
    task.abort();
    Ok(())
}
