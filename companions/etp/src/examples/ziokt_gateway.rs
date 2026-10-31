//! Explicit bounded local JSONL bridge; the operator supplies private keys and approved peers.
#[path = "support/tcp_transport.rs"]
mod tcp_transport;
#[path = "support/forum_gateway.rs"]
mod forum_gateway;
#[path = "support/mailbox_gateway.rs"]
mod mailbox_gateway;
#[path = "support/fileshare_gateway.rs"]
mod fileshare_gateway;
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
    #[serde(default = "default_transport")]
    transport: String,
    #[serde(default)]
    forum: Option<forum_gateway::ForumConfig>,
    #[serde(default)]
    mailbox: Option<mailbox_gateway::MailboxConfig>,
    #[serde(default)]
    fileshare: Option<fileshare_gateway::FileShareConfig>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    id: u64,
    method: String,
    params: Value,
}
fn default_transport()->String {"udp".into()}
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
    anyhow::ensure!(
        !std::env::var("ZIOKT_AIRGAP")
            .is_ok_and(|v| matches!(v.to_ascii_lowercase().as_str(), "1" | "true" | "yes")),
        "AIRGAP_DENIED: native network gateway disabled"
    );
    let path = std::env::args()
        .nth(1)
        .ok_or_else(|| anyhow::anyhow!("private node configuration required"))?;
    let mut options = fs::OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC);
    }
    let config_file = options.open(&path)?;
    let metadata = config_file.metadata()?;
    anyhow::ensure!(
        metadata.is_file() && metadata.len() <= 65536,
        "private regular config required"
    );
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        anyhow::ensure!(
            metadata.mode() & 0o077 == 0
                && metadata.uid() == unsafe { libc::geteuid() }
                && metadata.nlink() == 1,
            "private owner-controlled config required"
        );
    }
    let mut raw = Vec::new();
    config_file.take(65537).read_to_end(&mut raw)?;
    anyhow::ensure!(raw.len() <= 65536, "configuration budget");
    let mut settings: Config = serde_json::from_slice(&raw)?;
    use zeroize::Zeroize;
    raw.zeroize();
    anyhow::ensure!(settings.peers.len() <= 128, "peer budget");
    let private = hex_key(&settings.private_key)?;
    settings.private_key.zeroize();
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
    #[cfg(feature = "persistence")]
    let mut forum = settings
        .forum
        .take()
        .map(|settings| forum_gateway::ForumGateway::prepare(settings, &plugins, &mut config))
        .transpose()?;
    #[cfg(feature = "persistence")]
    let forum_peers = config.trusted_peers.clone();
    #[cfg(feature = "persistence")]
    let mut fileshare = settings.fileshare.take().map(fileshare_gateway::FileShareGateway::prepare).transpose()?;
    #[cfg(feature = "persistence")]
    let mut mailbox = settings
        .mailbox
        .take()
        .map(|settings| mailbox_gateway::MailboxGateway::prepare(settings, &config.trusted_peers))
        .transpose()?;
    #[cfg(feature = "persistence")]
    if mailbox.is_some() || fileshare.is_some() {
        use etp_core::plugin::{flavors::composite::CompositeFlavor, StandardFlavor};
        let composite = Arc::new(CompositeFlavor::new(Arc::new(StandardFlavor)));
        if let Some(forum) = &forum {
            composite.bind_stream(3, forum.flavor());
        }
        if let Some(mail) = &mailbox {
            composite.bind_stream(4, mail.flavor.clone());
            plugins.register_flavor(mail.flavor.clone());
        }
        if let Some(files) = &fileshare {
            composite.bind_stream(5, files.flavor.clone());
            plugins.register_flavor(files.flavor.clone());
        }
        plugins.register_flavor(composite);
        config.default_flavor = "etp.flavor.composite.v1".into();
        config.multiplexing_mode =
            etp_core::transport::reliability::MultiplexingMode::ParallelMulti;
    }
    let (engine, handle, mut received) = match settings.transport.as_str() {
        "udp" => EtpEngine::new(config, plugins).await?,
        "tcp" => {
            let transport=tcp_transport::TcpPacketTransport::bind(settings.bind,settings.peers.keys().copied().collect()).await?;
            EtpEngine::new_with_transport(config,plugins,Arc::new(transport)).await?
        },
        _ => anyhow::bail!("transport must be udp or tcp"),
    };
    #[cfg(feature = "persistence")]
    if let Some(files) = &mut fileshare {
        // One startup handshake owner: connect replaces native Noise state.
        // Forum/Mailbox already initiate their approved peers when configured.
        files.start(handle.clone(), forum_peers.clone(), forum.is_none() && mailbox.is_none());
    }
    #[cfg(feature = "persistence")]
    if let Some(mail) = &mut mailbox {
        mail.start(handle.clone(), forum_peers.clone());
    }
    #[cfg(feature = "persistence")]
    if let Some(forum) = &mut forum {
        forum.start(handle.clone(), forum_peers);
    }
    let mut task = tokio::spawn(engine.run());
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
   "etp.stats"=>{anyhow::ensure!(request.params==json!({}),"exact stats request");Ok(json!({"schema":"ziokt.etp-stats.v1","native":{"summary":handle.get_stats().await?}}))},
   "etp.onion.send"=>{
    let object=request.params.as_object().ok_or_else(||anyhow::anyhow!("object required"))?;anyhow::ensure!(object.len()==2,"exact onion frame");
    let hops=object.get("hops").and_then(Value::as_array).ok_or_else(||anyhow::anyhow!("hops required"))?;anyhow::ensure!((2..=4).contains(&hops.len()),"2..4 hops required");
    let mut path=Vec::new();for item in hops {let address:SocketAddr=item.as_str().ok_or_else(||anyhow::anyhow!("literal peer required"))?.parse()?;anyhow::ensure!(!path.iter().any(|(a,_)|*a==address),"repeated peer");let key=settings.peers.get(&address).ok_or_else(||anyhow::anyhow!("peer not approved"))?;path.push((address,hex_key(key)?));}
    let data=STANDARD.decode(object.get("ciphertext").and_then(Value::as_str).ok_or_else(||anyhow::anyhow!("ciphertext required"))?)?;anyhow::ensure!(data.len()>=16384&&data.len()<=65536&&data.len().is_power_of_two(),"padded sealed object required");handle.send_onion(path,data).await?;Ok(json!({"accepted":true,"delivery_confirmed":false,"direct_fallback":false}))
   },
   "etp.receive"=>{anyhow::ensure!(request.params==json!({}),"exact receive request");match tokio::time::timeout(std::time::Duration::from_secs(5),received.recv()).await {Ok(Some((_address,bytes)))=>{anyhow::ensure!(bytes.len()<=65536,"receive budget");Ok(json!({"ciphertext":bytes.chunks(3072).map(|chunk|STANDARD.encode(chunk)).collect::<Vec<_>>()}))},_=>Ok(json!({"ciphertext":null}))}},
   "etp.shutdown"=>{handle.shutdown().await?;Ok(json!({"stopped":true}))},
   method if method.starts_with("etp.mailbox.") => {
    #[cfg(feature="persistence")]
    {if let Some(mail)=&mailbox{mail.call(method,&request.params)}else{Err(anyhow::anyhow!("METHOD_UNSUPPORTED"))}}
    #[cfg(not(feature="persistence"))]
    {Err(anyhow::anyhow!("METHOD_UNSUPPORTED"))}
   },
   method if method.starts_with("etp.fileshare.") => {
    #[cfg(feature="persistence")]
    {if let Some(files)=&fileshare{files.call(method,&request.params).await}else{Err(anyhow::anyhow!("METHOD_UNSUPPORTED"))}}
    #[cfg(not(feature="persistence"))]
    {Err(anyhow::anyhow!("METHOD_UNSUPPORTED"))}
   },
   method if method.starts_with("etp.forum.") => {
    #[cfg(feature = "persistence")]
    { if let Some(forum) = &forum { forum.call(method, &request.params).await } else { Err(anyhow::anyhow!("METHOD_UNSUPPORTED")) } }
    #[cfg(not(feature = "persistence"))]
    { Err(anyhow::anyhow!("METHOD_UNSUPPORTED")) }
   },
   _=>Err(anyhow::anyhow!("unsupported operation"))
  }}.await;
        let response = match result {
            Ok(result) => json!({"id":request.id,"ok":true,"result":result}),
            Err(error) => {
                json!({"id":request.id,"ok":false,"error":{"code":if error.to_string() == "METHOD_UNSUPPORTED" { "METHOD_UNSUPPORTED" } else { "ETP_REJECTED" }}})
            }
        };
        writeln!(output, "{}", response)?;
        output.flush()?;
        if request.method == "etp.shutdown" {
            break;
        }
    }
    let _ = handle.shutdown().await;
    if tokio::time::timeout(std::time::Duration::from_secs(3), &mut task)
        .await
        .is_err()
    {
        task.abort();
    }
    Ok(())
}
