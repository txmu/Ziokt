//! Typed adapter to the original FileShare flavor, never a replacement wire/store.
use serde::Deserialize;
use std::collections::HashMap;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FileShareConfig {
    pub storage: String,
    pub exports: HashMap<String, String>,
}

#[cfg(feature = "persistence")]
mod enabled {
    use super::*;
    use anyhow::{anyhow, ensure, Result};
    use base64::{engine::general_purpose::STANDARD, Engine};
    use etp_core::{network::node::EtpHandle, plugin::flavors::fileshare::FileShareFlavor};
    use serde_json::{json, Value};
    use std::{net::SocketAddr, path::{Component, Path}, sync::Arc, time::{Duration, Instant}};
    use tokio::sync::mpsc;

    pub struct FileShareGateway {
        pub flavor: Arc<FileShareFlavor>,
        exports: HashMap<String, [u8; 32]>,
        peers: HashMap<SocketAddr, [u8; 32]>,
        network: Option<mpsc::Receiver<(SocketAddr, Vec<u8>)>>,
        tasks: Vec<tokio::task::JoinHandle<()>>,
    }
    impl FileShareGateway {
        pub fn prepare(settings: FileShareConfig) -> Result<Self> {
            ensure!(settings.exports.len() <= 16, "native export budget");
            super::super::forum_gateway::private_database(&settings.storage)?;
            let (tx, rx) = mpsc::channel(64);
            let flavor = FileShareFlavor::new(&settings.storage, tx)?;
            let mut exports = HashMap::new();
            for (name, source) in settings.exports {
                ensure!(!name.is_empty() && name.len() <= 64 && name.bytes().all(|b| b.is_ascii_alphanumeric() || b"_-".contains(&b)), "export alias");
                let path = Path::new(&source);
                ensure!(path.is_absolute() && !path.components().any(|c| matches!(c, Component::ParentDir | Component::CurDir)), "fixed absolute source required");
                // The native flavor snapshots/validates its own regular file,
                // content address and chunk integrity. No path is accepted over IPC.
                exports.insert(name, flavor.share_file(path)?);
            }
            Ok(Self {flavor, exports, peers: HashMap::new(), network: Some(rx), tasks: Vec::new()})
        }
        pub fn start(&mut self, handle: EtpHandle, peers: HashMap<SocketAddr, [u8; 32]>, initiate: bool) {
            self.peers = peers.clone();
            let connect = handle.clone();let initial = peers.clone();
            if initiate {
                self.tasks.push(tokio::spawn(async move {
                    for (peer, key) in initial { let _ = connect.connect(peer, key.to_vec()).await; }
                }));
            }
            let mut network = self.network.take().expect("FileShare network starts once");
            self.tasks.push(tokio::spawn(async move {
                let mut reconnect = HashMap::<SocketAddr, Instant>::new();
                while let Some((peer, packet)) = network.recv().await {
                    if !peers.contains_key(&peer) { continue; }
                    if handle.send_stream(peer, 5, packet).await.is_err() {
                        let due = reconnect.get(&peer).map_or(true, |last| last.elapsed() >= Duration::from_secs(5));
                        if due {
                            reconnect.insert(peer, Instant::now());
                            if let Some(key) = peers.get(&peer) {
                                let _ = tokio::time::timeout(Duration::from_secs(1), handle.connect(peer, key.to_vec())).await;
                            }
                        }
                    }
                }
            }));
        }
        pub async fn call(&self, method: &str, params: &Value) -> Result<Value> {
            let object = params.as_object().ok_or_else(|| anyhow!("object required"))?;
            if method == "etp.fileshare.list" {
                ensure!(object.is_empty(), "exact list arguments");
                let mut exports = self.exports.iter().map(|(name, hash)|json!({"name":name,"hash":hex::encode(hash)})).collect::<Vec<_>>();
                exports.sort_by_key(|v|v["name"].as_str().unwrap().to_string());
                return Ok(json!({"schema":"ziokt.etp-fileshare-list.v1","exports":exports,"chunk_bytes":16384,"file_bytes_limit":16777216}));
            }
            ensure!(matches!(method, "etp.fileshare.manifest"|"etp.fileshare.chunk"|"etp.fileshare.request"|"etp.fileshare.status"), "METHOD_UNSUPPORTED");
            let expected = if method == "etp.fileshare.request" { vec!["hash","peer"] } else if method == "etp.fileshare.chunk" { vec!["hash","index"] } else { vec!["hash"] };
            ensure!(object.len() == expected.len() && expected.iter().all(|key|object.contains_key(*key)), "exact FileShare fields");
            let hash: [u8;32] = super::super::hex_key(object["hash"].as_str().ok_or_else(||anyhow!("hash required"))?)?.try_into().map_err(|_|anyhow!("native root length"))?;
            if method == "etp.fileshare.request" {
                let peer: SocketAddr = object["peer"].as_str().ok_or_else(||anyhow!("peer required"))?.parse()?;
                ensure!(self.peers.contains_key(&peer), "peer not approved");
                let (state,_,_) = self.flavor.download_progress(hash);
                if state == "absent" || state == "timed_out" { self.flavor.start_download(hash, peer).await?; }
                let (state, received, total) = self.flavor.download_progress(hash);
                return Ok(json!({"schema":"ziokt.etp-fileshare-status.v1","state":state,"received":received,"total":total,"content_verified":false}));
            }
            if method == "etp.fileshare.status" {
                let (state, received, total) = self.flavor.download_progress(hash);
                return Ok(json!({"schema":"ziokt.etp-fileshare-status.v1","state":state,"received":received,"total":total,"content_verified":false}));
            }
            if method == "etp.fileshare.manifest" {
                let manifest = self.flavor.shared_manifest(hash)?;
                return Ok(json!({"schema":"ziokt.etp-fileshare-manifest.v1","hash":hex::encode(hash),"name":manifest.file_name,"size":manifest.file_size,"mime":manifest.mime_type,"chunk_bytes":16384,"chunks":manifest.chunk_hashes.iter().map(hex::encode).collect::<Vec<_>>(),"content_verified":false}));
            }
            let index = object["index"].as_u64().filter(|n|*n <= u32::MAX as u64).ok_or_else(||anyhow!("chunk index"))? as u32;
            let bytes = self.flavor.read_shared_chunk(hash,index)?;
            Ok(json!({"schema":"ziokt.etp-fileshare-chunk.v1","hash":hex::encode(hash),"index":index,"data_base64":bytes.chunks(3072).map(|part|STANDARD.encode(part)).collect::<Vec<_>>(),"native_chunk_verified":true}))
        }
    }
    impl Drop for FileShareGateway {
        fn drop(&mut self) { for task in &self.tasks { task.abort(); } }
    }
}
#[cfg(feature = "persistence")]
pub use enabled::FileShareGateway;
