use anyhow::{anyhow, Result};
use serde::Deserialize;
use serde_json::Value;
use std::collections::HashMap;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ForumConfig {
    pub database: String,
    pub identities: HashMap<String, String>,
    pub subscriptions: Vec<String>,
}

#[cfg(feature = "persistence")]
mod enabled {
    use super::*;
    use base64::{engine::general_purpose::STANDARD, Engine};
    use ed25519_dalek::SigningKey;
    use etp_core::{
        common::DhtStoreRequest,
        network::node::{EtpHandle, NodeConfig},
        plugin::{
            flavors::{
                composite::CompositeFlavor,
                forum::{ForumFlavor, ForumPost, ParentStatus},
            },
            PluginRegistry, StandardFlavor,
        },
        transport::reliability::MultiplexingMode,
    };
    use serde_json::json;
    use std::{
        collections::HashSet,
        net::SocketAddr,
        path::{Component, Path},
        sync::Arc,
        time::{SystemTime, UNIX_EPOCH},
    };
    use tokio::sync::mpsc;
    use zeroize::Zeroize;
    const STREAM: u32 = 3;
    fn name(value: &str) -> Result<()> {
        anyhow::ensure!(
            !value.is_empty()
                && value.len() <= 64
                && value
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b"_-".contains(&b)),
            "bounded identity name required"
        );
        Ok(())
    }
    fn topic(value: &str) -> Result<()> {
        anyhow::ensure!(
            !value.is_empty() && value.len() <= 256 && !value.chars().any(char::is_control),
            "bounded topic required"
        );
        Ok(())
    }
    fn id(value: &str) -> Result<[u8; 32]> {
        super::super::hex_key(value)?
            .try_into()
            .map_err(|_| anyhow!("invalid post ID"))
    }
    fn private_database(value: &str) -> Result<()> {
        let path = Path::new(value);
        anyhow::ensure!(
            path.is_absolute()
                && !path
                    .components()
                    .any(|c| matches!(c, Component::ParentDir | Component::CurDir)),
            "absolute database path required"
        );
        let mut current = std::path::PathBuf::new();
        for part in path.components() {
            current.push(part.as_os_str());
            match std::fs::symlink_metadata(&current) {
                Ok(meta) => {
                    anyhow::ensure!(
                        !meta.file_type().is_symlink() && meta.is_dir(),
                        "database path must not contain symlinks"
                    );
                    #[cfg(unix)]
                    {
                        use std::os::unix::fs::MetadataExt;
                        anyhow::ensure!(
                            meta.mode() & 0o022 == 0 || meta.mode() & 0o1000 != 0,
                            "database ancestors must prevent untrusted path replacement"
                        );
                    }
                }
                Err(error) if error.kind() == std::io::ErrorKind::NotFound && current == path => {
                    let mut builder = std::fs::DirBuilder::new();
                    #[cfg(unix)]
                    {
                        use std::os::unix::fs::DirBuilderExt;
                        builder.mode(0o700);
                    }
                    builder.create(&current)?;
                }
                Err(error) => return Err(error.into()),
            }
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            let meta = std::fs::symlink_metadata(path)?;
            anyhow::ensure!(
                meta.is_dir()
                    && !meta.file_type().is_symlink()
                    && meta.mode() & 0o077 == 0
                    && meta.uid() == unsafe { libc::geteuid() },
                "private owner-controlled Forum directory required"
            );
        }
        #[cfg(not(unix))]
        {
            return Err(anyhow!(
                "private Forum directory ownership check unsupported on this platform"
            ));
        }
        Ok(())
    }
    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Identity {
        name: String,
    }
    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Subscribe {
        topic: String,
    }
    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Publish {
        topic: String,
        content: String,
        author: Option<String>,
        parent_id: Option<String>,
    }
    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Get {
        id: String,
    }
    pub struct ForumGateway {
        flavor: Arc<ForumFlavor>,
        identities: HashMap<String, SigningKey>,
        subscriptions: parking_lot::Mutex<HashSet<String>>,
        network: Option<mpsc::Receiver<(SocketAddr, Vec<u8>)>>,
        dht: Option<mpsc::Receiver<DhtStoreRequest>>,
        tasks: Vec<tokio::task::JoinHandle<()>>,
    }
    impl ForumGateway {
        pub fn prepare(
            settings: ForumConfig,
            plugins: &Arc<PluginRegistry>,
            config: &mut NodeConfig,
        ) -> Result<Self> {
            anyhow::ensure!(
                settings.identities.len() <= 8 && settings.subscriptions.len() <= 64,
                "Forum configuration budget"
            );
            let mut identities = HashMap::new();
            for (label, mut secret) in settings.identities {
                name(&label)?;
                let mut bytes = super::super::hex_key(&secret)?;
                secret.zeroize();
                let mut seed: [u8; 32] = bytes.as_slice().try_into()?;
                bytes.zeroize();
                identities.insert(label, SigningKey::from_bytes(&seed));
                seed.zeroize();
            }
            let mut subscriptions = HashSet::new();
            for item in settings.subscriptions {
                topic(&item)?;
                anyhow::ensure!(subscriptions.insert(item), "duplicate Forum subscription");
            }
            private_database(&settings.database)?;
            let (network_tx, network) = mpsc::channel(512);
            let (dht_tx, dht) = mpsc::channel(256);
            let flavor = ForumFlavor::new(&settings.database, dht_tx, network_tx)?;
            for item in &subscriptions {
                flavor.try_subscribe(item)?;
            }
            let composite = Arc::new(CompositeFlavor::new(Arc::new(StandardFlavor)));
            composite.bind_stream(STREAM, flavor.clone());
            plugins.register_flavor(flavor.clone());
            plugins.register_flavor(composite);
            config.default_flavor = "etp.flavor.composite.v1".into();
            config.multiplexing_mode = MultiplexingMode::ParallelMulti;
            Ok(Self {
                flavor,
                identities,
                subscriptions: parking_lot::Mutex::new(subscriptions),
                network: Some(network),
                dht: Some(dht),
                tasks: Vec::new(),
            })
        }
        pub fn start(&mut self, handle: EtpHandle, peers: HashMap<SocketAddr, [u8; 32]>) {
            let connector = handle.clone();
            self.tasks.push(tokio::spawn(async move {
                for (peer, key) in peers {
                    let _ = connector.connect(peer, key.to_vec()).await;
                }
            }));
            let mut network = self.network.take().expect("Forum network starts once");
            let sender = handle.clone();
            self.tasks.push(tokio::spawn(async move {
                while let Some((peer, packet)) = network.recv().await {
                    if sender.send_stream(peer, STREAM, packet).await.is_err() {
                        break;
                    }
                }
            }));
            let mut dht = self.dht.take().expect("Forum DHT starts once");
            self.tasks.push(tokio::spawn(async move {
                while let Some(request) = dht.recv().await {
                    if handle
                        .dht_store(request.key, request.value, request.ttl_seconds)
                        .await
                        .is_err()
                    {
                        break;
                    }
                }
            }));
        }
        fn subscribe(&self, value: &str) -> Result<()> {
            topic(value)?;
            let mut subscriptions = self.subscriptions.lock();
            anyhow::ensure!(
                subscriptions.contains(value) || subscriptions.len() < 64,
                "Forum subscription budget"
            );
            self.flavor.try_subscribe(value)?;
            subscriptions.insert(value.into());
            Ok(())
        }
        pub async fn call(&self, method: &str, params: &Value) -> Result<Value> {
            match method {
                "etp.forum.identity" => {
                    let value: Identity = serde_json::from_value(params.clone())?;
                    name(&value.name)?;
                    let key = self
                        .identities
                        .get(&value.name)
                        .ok_or_else(|| anyhow!("unknown identity"))?;
                    Ok(
                        json!({"schema":"ziokt.etp-forum-identity.v1","name":value.name,"author_id":hex::encode(blake3::hash(key.verifying_key().as_bytes()).as_bytes())}),
                    )
                }
                "etp.forum.subscribe" => {
                    let value: Subscribe = serde_json::from_value(params.clone())?;
                    self.subscribe(&value.topic)?;
                    Ok(
                        json!({"subscribed":true,"topic_hash":hex::encode(blake3::hash(value.topic.as_bytes()).as_bytes())}),
                    )
                }
                "etp.forum.publish" => {
                    anyhow::ensure!(
                        params.as_object().is_some_and(|o| o.contains_key("author")),
                        "explicit named author or null required"
                    );
                    let value: Publish = serde_json::from_value(params.clone())?;
                    topic(&value.topic)?;
                    anyhow::ensure!(
                        !value.content.is_empty() && value.content.len() <= 32768,
                        "Forum content budget"
                    );
                    let mut post = ForumPost {
                        id: [0; 32],
                        topic_hash: blake3::hash(value.topic.as_bytes()).into(),
                        author_id: None,
                        timestamp: SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs() as i64,
                        content: value.content,
                        parent_id: value.parent_id.as_deref().map(id).transpose()?,
                        signature: vec![],
                    };
                    if let Some(label) = value.author {
                        name(&label)?;
                        post.sign(
                            self.identities
                                .get(&label)
                                .ok_or_else(|| anyhow!("unknown identity"))?,
                        );
                    } else {
                        post.id = post.calculate_id();
                    }
                    self.subscribe(&value.topic)?;
                    let dht_enqueued = self.flavor.publish_prepared_post(post.clone()).await?;
                    Ok(
                        json!({"schema":"ziokt.etp-forum-publish.v1","id":hex::encode(post.id),"stored":true,"dht_enqueued":dht_enqueued,"delivery_confirmed":false,"state":"stored_locally","gossip":"best_effort"}),
                    )
                }
                "etp.forum.get" => {
                    let value: Get = serde_json::from_value(params.clone())?;
                    let Some(post) = self.flavor.get_post(&id(&value.id)?) else {
                        return Ok(json!({"post":null}));
                    };
                    let status = match self.flavor.parent_status(&post) {
                        ParentStatus::NotReply => "not_reply",
                        ParentStatus::Available => "available",
                        ParentStatus::MissingOrExpired => "missing_or_expired",
                    };
                    Ok(
                        json!({"post":{"id":hex::encode(post.id),"topic_hash":hex::encode(post.topic_hash),"author_id":post.author_id.map(hex::encode),"timestamp":post.timestamp,"content_base64":post.content.as_bytes().chunks(3072).map(|part| STANDARD.encode(part)).collect::<Vec<_>>(),"parent_id":post.parent_id.map(hex::encode),"signature_base64":STANDARD.encode(&post.signature),"parent_status":status}}),
                    )
                }
                _ => Err(anyhow!("METHOD_UNSUPPORTED")),
            }
        }
    }
    impl Drop for ForumGateway {
        fn drop(&mut self) {
            for task in &self.tasks {
                task.abort();
            }
        }
    }
}
#[cfg(feature = "persistence")]
pub use enabled::ForumGateway;
