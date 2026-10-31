//! Optional native ETP mailbox host. Transport peers and signing peers are separate grants.
use serde::Deserialize;
use std::{collections::HashMap, net::SocketAddr};
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct MailboxConfig {
    pub database: String,
    #[serde(default)]
    pub replication: Option<ReplicationConfig>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReplicationConfig {
    pub copies: usize,
    pub signing_key: String,
    pub peers: HashMap<SocketAddr, String>,
}
#[cfg(feature = "persistence")]
mod enabled {
    use super::*;
    use anyhow::{ensure, Result};
    use base64::{engine::general_purpose::STANDARD, Engine};
    use etp_core::{
        network::node::EtpHandle,
        plugin::flavors::{mailbox::MailboxFlavor, mailbox_replication::ReplicaConfig},
    };
    use std::{
        collections::BTreeMap,
        path::{Component, Path},
        sync::Arc,
    };
    use tokio::sync::mpsc;
    use zeroize::Zeroize;
    pub struct MailboxGateway {
        pub flavor: Arc<MailboxFlavor>,
        network: Option<mpsc::Receiver<(SocketAddr, Vec<u8>)>>,
        tasks: Vec<tokio::task::JoinHandle<()>>,
        copies: usize,
    }
    impl MailboxGateway {
        pub fn prepare(
            settings: MailboxConfig,
            native_peers: &HashMap<SocketAddr, [u8; 32]>,
        ) -> Result<Self> {
            let path = Path::new(&settings.database);
            ensure!(
                path.is_absolute()
                    && !path
                        .components()
                        .any(|c| matches!(c, Component::ParentDir | Component::CurDir)),
                "absolute private mailbox database path required"
            );
            let mut current = std::path::PathBuf::new();
            for part in path.components() {
                current.push(part.as_os_str());
                if let Ok(meta) = std::fs::symlink_metadata(&current) {
                    ensure!(
                        !meta.file_type().is_symlink(),
                        "mailbox database path cannot contain symlinks"
                    );
                }
            }
            std::fs::create_dir_all(path)?;
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700))?;
            }
            let (tx, network) = mpsc::channel(256);
            let mut copies = 1;
            let replicas = if let Some(mut config) = settings.replication {
                copies = config.copies;
                let mut peers = BTreeMap::new();
                for (address, key) in config.peers {
                    ensure!(
                        native_peers.contains_key(&address),
                        "replica must also be an authorized encrypted ETP transport peer"
                    );
                    peers.insert(super::super::hex_key(&key)?.as_slice().try_into()?, address);
                }
                let mut bytes = super::super::hex_key(&config.signing_key)?;
                config.signing_key.zeroize();
                let key = bytes.as_slice().try_into()?;
                bytes.zeroize();
                Some(ReplicaConfig { copies, key, peers })
            } else {
                None
            };
            let flavor = MailboxFlavor::new_with_replication(&settings.database, tx, replicas)?;
            Ok(Self {
                flavor,
                network: Some(network),
                tasks: Vec::new(),
                copies,
            })
        }
        pub fn start(&mut self, handle: EtpHandle, peers: HashMap<SocketAddr, [u8; 32]>) {
            let mut network = self.network.take().expect("Mailbox starts once");
            let sender = handle.clone();
            self.tasks.push(tokio::spawn(async move {
                while let Some((peer, packet)) = network.recv().await {
                    let _ = sender.send_stream(peer, 4, packet).await;
                }
            }));
            let flavor = self.flavor.clone();
            self.tasks.push(tokio::spawn(async move {
                let mut timer = tokio::time::interval(std::time::Duration::from_secs(5));
                loop {
                    timer.tick().await;
                    for (peer, key) in &peers {
                        let _ = handle.connect(*peer, key.to_vec()).await;
                    }
                    let _ = flavor.reconcile();
                }
            }));
        }
        pub fn call(&self, method: &str, params: &serde_json::Value) -> Result<serde_json::Value> {
            match method {
                "etp.mailbox.status" => {
                    ensure!(
                        params.as_object().is_some_and(|v| v.is_empty()),
                        "status fields"
                    );
                    Ok(
                        serde_json::json!({"schema":"etp.mailbox.health.v1","native_store":"opened","copies_required":self.copies}),
                    )
                }
                "etp.mailbox.request" => {
                    ensure!(
                        params.as_object().is_some_and(|v| v.len() == 1),
                        "request fields"
                    );
                    let data = params["frame_base64"]
                        .as_str()
                        .ok_or_else(|| anyhow::anyhow!("frame"))?;
                    ensure!(data.len() <= 12000, "frame budget");
                    let bytes = STANDARD.decode(data)?;
                    ensure!(
                        bytes.len() >= 2 && bytes[0] == 2 && [1, 2, 4, 6].contains(&bytes[1]),
                        "recipient operations only"
                    );
                    let response = self.flavor.process_packet("127.0.0.1:0".parse()?, &bytes)?;
                    Ok(serde_json::json!({"frame_base64":STANDARD.encode(response)}))
                }
                _ => anyhow::bail!("METHOD_UNSUPPORTED"),
            }
        }
    }
    impl Drop for MailboxGateway {
        fn drop(&mut self) {
            for task in &self.tasks {
                task.abort();
            }
        }
    }
}
#[cfg(feature = "persistence")]
pub use enabled::MailboxGateway;
