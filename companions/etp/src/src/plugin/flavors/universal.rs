// etp-core/src/plugin/flavors/universal.rs

#![cfg(feature = "persistence")] // 基础依赖：必须有持久化支持

use std::collections::{HashMap, HashSet};
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use anyhow::{anyhow, Context, Result};
use bincode::Options;
use blake3;
use ed25519_dalek::{Signature, Signer, SigningKey, Verifier, VerifyingKey};
use log::{debug, error, info, trace, warn};
use lru::LruCache;
use parking_lot::{Mutex, RwLock};
use rand::Rng;
use serde::{Deserialize, Serialize};
use sled::transaction::{ConflictableTransactionError, Transactional};
use sled::Db;
use std::num::NonZeroUsize;
use tokio::sync::{broadcast, mpsc};

// 安全擦除支持
#[cfg(feature = "paranoid-security")]
use zeroize::{Zeroize, ZeroizeOnDrop};

// ETP 核心接口
use crate::common::DhtStoreRequest;
use crate::plugin::{CapabilityProvider, Flavor, FlavorContext};
use crate::NodeID;

// --- 扩展模块 ---
#[cfg(feature = "extensions")]
use crate::crypto::onion::{NonceMode, OnionConfig, OnionCrypto, PaddingStrategy};
#[cfg(feature = "extensions")]
use crate::extensions::identity::{EtpIdentity, GhostIdentity, IdentityType};
#[cfg(feature = "extensions")]
use crate::extensions::kns::{KnsKernel, KnsPath, RecordKind, ResolutionPriority};

// --- 区块链支持 ---
#[cfg(feature = "smart-contracts")]
use primitive_types::{H160 as EthAddress, H256 as EthHash, U256};
#[cfg(feature = "smart-contracts")]
use std::str::FromStr;

// --- 协议常量 ---
const UNIVERSAL_PROTO_VER: u8 = 0x03;
const MAX_WIRE: usize = 1024;
const MAX_MESSAGES: usize = 4096;
const MAX_TOPICS: usize = 8;
const MAX_PEERS: usize = 100;

// 策略 ID (Strategy / Command)
const STRATEGY_DIRECT: u8 = 0x01; // 点对点
const STRATEGY_MANAGED: u8 = 0x02; // 托管
const STRATEGY_BROADCAST: u8 = 0x03; // 广播 (Gossip)
const STRATEGY_DEADDROP: u8 = 0x04; // 死信箱
const STRATEGY_CONTROL: u8 = 0xFF; // [新增] 控制信令 (用于 Sync)

// 安全配置
const REPLAY_CACHE_SIZE: usize = 10000;
const MSG_TIME_WINDOW_SEC: u64 = 300;
const SYNC_BLOOM_SIZE_BITS: usize = 4096; // 512-byte Bloom Filter
const SYNC_HASH_FUNCS: usize = 3;

// ============================================================================
//  数据结构定义
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UniversalMessage {
    pub uuid: u128,
    pub timestamp: u64,
    pub sender_id: NodeID,
    pub sender_pub_key: [u8; 32],
    pub strategy: DeliveryStrategy,
    pub content: MessageContent,
    pub resources: Vec<ResourceLink>,
    pub options: MessageOptions,
    pub signature: Vec<u8>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct MessageOptions {
    pub reply_to: Option<u128>,
    pub delete_after_read_secs: u32,
    pub tags: Vec<String>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq)]
pub enum DeliveryStrategy {
    Direct {
        target: NodeID,
    },
    Managed {
        server: SocketAddr,
        target: NodeID,
    },
    Broadcast {
        topic_hash: [u8; 32],
    },
    #[cfg(feature = "extensions")]
    DeadDrop {
        target_pub_key: [u8; 32],
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum MessageContent {
    Text(String),
    Binary(Vec<u8>),
    RichText(String),
    PaymentRequest {
        chain: String,
        target_address: String,
        amount: String,
        memo: String,
    },
    System(String),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum ResourceLink {
    FileShare([u8; 32]),
    Magnet(String),
    IpfsCid(String),
    #[cfg(feature = "extensions")]
    KnsPtr(String),

    // --- 区块链 ---
    #[cfg(feature = "smart-contracts")]
    EthTx {
        hash: EthHash,
        network_id: u64,
    },
    #[cfg(feature = "smart-contracts")]
    EthNft {
        contract: EthAddress,
        token_id: U256,
        network_id: u64,
    },

    /// Solana 资源引用
    SolanaRef {
        address: String, // Base58 string
        signature: Option<String>,
        cluster: String,
    },
}

impl ResourceLink {
    /// 验证链接格式是否合法 (利用可选编译特性)
    pub fn validate(&self) -> bool {
        fn bounded(value: &str, max: usize) -> bool {
            !value.is_empty() && value.len() <= max && !value.chars().any(char::is_control)
        }
        match self {
            ResourceLink::FileShare(_) => true,
            ResourceLink::Magnet(value) => {
                bounded(value, 512) && value.starts_with("magnet:?xt=urn:btih:")
            }
            ResourceLink::IpfsCid(value) => {
                bounded(value, 128) && value.chars().all(|c| c.is_ascii_alphanumeric())
            }
            #[cfg(feature = "extensions")]
            ResourceLink::KnsPtr(value) => bounded(value, 512),
            ResourceLink::SolanaRef {
                address,
                signature,
                cluster,
            } => {
                let base58 = |v: &str, min: usize, max: usize| {
                    v.len() >= min
                        && v.len() <= max
                        && v.bytes().all(|b| {
                            b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
                                .contains(&b)
                        })
                };
                base58(address, 32, 44)
                    && signature.as_ref().map_or(true, |s| base58(s, 64, 88))
                    && bounded(cluster, 32)
            }
            #[cfg(feature = "smart-contracts")]
            ResourceLink::EthNft { .. } | ResourceLink::EthTx { .. } => true,
        }
    }
}

fn decode<T: serde::de::DeserializeOwned>(bytes: &[u8]) -> Result<T> {
    anyhow::ensure!(bytes.len() <= MAX_WIRE, "universal frame budget");
    Ok(bincode::DefaultOptions::new()
        .with_fixint_encoding()
        .with_limit(MAX_WIRE as u64)
        .reject_trailing_bytes()
        .deserialize(bytes)?)
}
impl UniversalMessage {
    fn signing_bytes(&self) -> Result<Vec<u8>> {
        let mut bytes = b"ETP/UNIVERSAL/MESSAGE/v3\0".to_vec();
        bytes.extend(bincode::serialize(&(
            self.uuid,
            self.timestamp,
            self.sender_id,
            self.sender_pub_key,
            &self.strategy,
            &self.content,
            &self.resources,
            &self.options,
        ))?);
        Ok(bytes)
    }
    fn verify(&self) -> Result<()> {
        let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
        anyhow::ensure!(
            self.timestamp <= now.saturating_add(MSG_TIME_WINDOW_SEC)
                && now.saturating_sub(self.timestamp) <= MSG_TIME_WINDOW_SEC * 100,
            "universal message expired"
        );
        anyhow::ensure!(
            self.options.tags.len() <= 16
                && self.options.tags.iter().all(|t| t.len() <= 64)
                && self.options.delete_after_read_secs <= 604800
                && self.resources.len() <= 8
                && self.resources.iter().all(ResourceLink::validate),
            "universal metadata budget"
        );
        anyhow::ensure!(
            bincode::serialized_size(self)? as usize + 2 <= MAX_WIRE,
            "use resource references for large message content"
        );
        anyhow::ensure!(
            self.sender_id == *blake3::hash(&self.sender_pub_key).as_bytes(),
            "universal author mismatch"
        );
        let public = VerifyingKey::from_bytes(&self.sender_pub_key)?;
        public.verify_strict(
            &self.signing_bytes()?,
            &Signature::from_slice(&self.signature)?,
        )?;
        Ok(())
    }
}

// --- 控制信令结构 (用于 Gossip Sync) ---
#[derive(Debug, Serialize, Deserialize)]
enum ControlMessage {
    /// 同步提议：发送我的订阅话题和 Bloom Filter
    SyncOffer {
        topic_hashes: Vec<[u8; 32]>,
        bloom_bits: Vec<u8>,
        time_range: (u64, u64), // (Start, End)
    },
    /// 同步请求：请求特定的 Message UUIDs
    SyncRequest {
        uuids: Vec<u128>,
    },
    Inventory {
        uuids: Vec<u128>,
    },
}

// --- 简易 Bloom Filter ---
struct SyncBloom {
    bits: Vec<u8>,
}
impl SyncBloom {
    fn new() -> Self {
        Self {
            bits: vec![0u8; SYNC_BLOOM_SIZE_BITS / 8],
        }
    }
    fn from_bytes(bytes: Vec<u8>) -> Self {
        Self { bits: bytes }
    }
    fn insert(&mut self, item: &[u8]) {
        for i in 0..SYNC_HASH_FUNCS {
            let idx = self.hash(item, i);
            self.bits[idx / 8] |= 1 << (idx % 8);
        }
    }
    fn contains(&self, item: &[u8]) -> bool {
        for i in 0..SYNC_HASH_FUNCS {
            let idx = self.hash(item, i);
            if (self.bits[idx / 8] & (1 << (idx % 8))) == 0 {
                return false;
            }
        }
        true
    }
    fn hash(&self, item: &[u8], seed: usize) -> usize {
        let mut h = blake3::Hasher::new();
        h.update(&seed.to_le_bytes());
        h.update(item);
        let res = h.finalize();
        // 取前8字节做索引
        let mut b = [0u8; 8];
        b.copy_from_slice(&res.as_bytes()[0..8]);
        (u64::from_le_bytes(b) as usize) % SYNC_BLOOM_SIZE_BITS
    }
}

// ============================================================================
//  存储层
// ============================================================================

pub struct UniversalStore {
    db: Db,
    mutation: Mutex<()>,
}

impl UniversalStore {
    fn new(path: &str) -> Result<Self> {
        let db = sled::open(path)?;
        let result = Self {
            db,
            mutation: Mutex::new(()),
        };
        // Preserve old unauthenticated or damaged bytes for explicit export.
        let tree = result.db.open_tree("messages")?;
        let quarantine = result.db.open_tree("quarantined_universal_v2")?;
        for entry in tree.iter() {
            let (key, value) = entry?;
            if decode::<UniversalMessage>(&value)
                .and_then(|m| m.verify())
                .is_err()
            {
                (&tree, &quarantine)
                    .transaction(|(messages, old)| {
                        old.insert(key.as_ref(), value.as_ref())?;
                        messages.remove(key.as_ref())?;
                        Ok::<_, ConflictableTransactionError<()>>(())
                    })
                    .map_err(|e| anyhow!("universal quarantine: {:?}", e))?;
            }
        }
        result.db.flush()?;
        Ok(result)
    }

    fn save_msg(&self, msg: &UniversalMessage) -> Result<bool> {
        msg.verify()?;
        let _guard = self.mutation.lock();
        let tree = self.db.open_tree("messages")?;
        let index = self.db.open_tree("idx_topic")?;
        let key = msg.uuid.to_be_bytes();
        let value = bincode::serialize(msg)?;
        if let Some(old) = tree.get(key)? {
            anyhow::ensure!(
                old.as_ref() == value.as_slice(),
                "conflicting universal message ID"
            );
            self.db.flush()?;
            return Ok(false);
        }
        anyhow::ensure!(
            tree.len() < MAX_MESSAGES,
            "universal storage requires archival"
        );
        let index_key = if let DeliveryStrategy::Broadcast { topic_hash } = msg.strategy {
            let mut k = topic_hash.to_vec();
            k.extend_from_slice(&msg.timestamp.to_be_bytes());
            k.extend_from_slice(&key);
            Some(k)
        } else {
            None
        };
        (&tree, &index)
            .transaction(|(messages, topics)| {
                messages.insert(key.as_slice(), value.as_slice())?;
                if let Some(ref k) = index_key {
                    topics.insert(k.as_slice(), key.as_slice())?;
                }
                Ok::<_, ConflictableTransactionError<()>>(())
            })
            .map_err(|e| anyhow!("universal store: {:?}", e))?;
        self.db.flush()?;
        Ok(true)
    }

    fn get_msg(&self, uuid: u128) -> Option<UniversalMessage> {
        let tree = self.db.open_tree("messages").ok()?;
        let val = tree.get(&uuid.to_be_bytes()).ok()??;
        decode::<UniversalMessage>(&val)
            .ok()
            .filter(|m| m.verify().is_ok())
    }

    fn get_history(&self, limit: usize, offset: usize) -> Result<Vec<UniversalMessage>> {
        let tree = self.db.open_tree("messages")?;
        let mut messages = Vec::new();
        for entry in tree
            .iter()
            .rev()
            .skip(offset.min(MAX_MESSAGES))
            .take(limit.min(256))
        {
            let (_, value) = entry?;
            let message = decode::<UniversalMessage>(&value)?;
            message.verify()?;
            messages.push(message);
        }
        Ok(messages)
    }

    /// 获取特定时间段内、特定话题的消息 UUID
    fn get_uuids_in_range(&self, topics: &HashSet<[u8; 32]>, start: u64, end: u64) -> Vec<u128> {
        let mut results = Vec::new();
        if let Ok(idx_tree) = self.db.open_tree("idx_topic") {
            for topic in topics {
                let mut start_key = topic.to_vec();
                start_key.extend_from_slice(&start.to_be_bytes());

                let mut end_key = topic.to_vec();
                end_key.extend_from_slice(&end.to_be_bytes());
                end_key.extend_from_slice(&[0xFF; 16]); // Cover UUID range

                for item in idx_tree.range(start_key..end_key) {
                    if let Ok((_, uuid_bytes)) = item {
                        if let Ok(bytes) = uuid_bytes.as_ref().try_into() {
                            if results.len() < MAX_MESSAGES {
                                results.push(u128::from_be_bytes(bytes));
                            }
                        }
                    }
                }
            }
        }
        results
    }

    fn mark_read(&self, msg: &UniversalMessage) -> Result<()> {
        if msg.options.delete_after_read_secs == 0 {
            return Ok(());
        }
        let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
        let deadlines = self.db.open_tree("read_deadlines_v3")?;
        let key = msg.uuid.to_be_bytes();
        let deadline = (now + msg.options.delete_after_read_secs as u64).to_be_bytes();
        let _ =
            deadlines.compare_and_swap(key, None as Option<&[u8]>, Some(deadline.as_slice()))?;
        self.db.flush()?;
        Ok(())
    }
    fn sweep(&self) -> Result<()> {
        let _guard = self.mutation.lock();
        let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
        let deadlines = self.db.open_tree("read_deadlines_v3")?;
        let messages = self.db.open_tree("messages")?;
        for entry in messages.iter().take(MAX_MESSAGES) {
            let (key, value) = entry?;
            let expired = match decode::<UniversalMessage>(&value) {
                Ok(msg) => now.saturating_sub(msg.timestamp) > MSG_TIME_WINDOW_SEC * 100,
                Err(_) => false,
            };
            let read_expired = deadlines.get(&key)?.is_some_and(|v| {
                v.len() == 8 && now >= u64::from_be_bytes(v.as_ref().try_into().unwrap())
            });
            if expired || read_expired {
                if let Ok(bytes) = key.as_ref().try_into() {
                    self.delete_msg(u128::from_be_bytes(bytes))?;
                }
            }
        }
        Ok(())
    }
    fn delete_msg(&self, uuid: u128) -> Result<()> {
        let _guard = self.mutation.lock();
        let messages = self.db.open_tree("messages")?;
        let index = self.db.open_tree("idx_topic")?;
        let deadlines = self.db.open_tree("read_deadlines_v3")?;
        let key = uuid.to_be_bytes();
        let old = messages
            .get(key)?
            .and_then(|v| decode::<UniversalMessage>(&v).ok());
        let index_key = old.and_then(|msg| {
            if let DeliveryStrategy::Broadcast { topic_hash } = msg.strategy {
                let mut k = topic_hash.to_vec();
                k.extend_from_slice(&msg.timestamp.to_be_bytes());
                k.extend_from_slice(&key);
                Some(k)
            } else {
                None
            }
        });
        (&messages, &index, &deadlines)
            .transaction(|(m, i, d)| {
                m.remove(key.as_slice())?;
                d.remove(key.as_slice())?;
                if let Some(ref k) = index_key {
                    i.remove(k.as_slice())?;
                }
                Ok::<_, ConflictableTransactionError<()>>(())
            })
            .map_err(|e| anyhow!("universal deletion: {:?}", e))?;
        self.db.flush()?;
        Ok(())
    }
}

// ============================================================================
//  Flavor 实现
// ============================================================================

#[derive(Clone)]
#[cfg_attr(feature = "paranoid-security", derive(Zeroize, ZeroizeOnDrop))]
struct SecureSigningKey {
    #[cfg_attr(feature = "paranoid-security", zeroize(skip))]
    inner: SigningKey,
}

impl SecureSigningKey {
    fn from_bytes(bytes: &[u8; 32]) -> Self {
        Self {
            inner: SigningKey::from_bytes(bytes),
        }
    }
    fn sign(&self, data: &[u8]) -> Signature {
        self.inner.sign(data)
    }
    fn verifying_key(&self) -> VerifyingKey {
        self.inner.verifying_key()
    }
}

pub struct UniversalMessengerFlavor {
    signing_key: SecureSigningKey,
    verifying_key: VerifyingKey,
    store: Arc<UniversalStore>,

    network_tx: mpsc::Sender<(SocketAddr, Vec<u8>)>,
    dht_tx: mpsc::Sender<DhtStoreRequest>,
    ui_tx: broadcast::Sender<UniversalMessage>,

    #[cfg(feature = "extensions")]
    kns: Option<Arc<KnsKernel>>,

    subscriptions: RwLock<HashSet<[u8; 32]>>,
    replay_cache: Mutex<LruCache<u128, u64>>,
    peers: RwLock<HashSet<SocketAddr>>,
    routes: RwLock<HashMap<NodeID, SocketAddr>>,
    ingress: Mutex<(u64, usize)>,
    last_poll: Mutex<u64>,
    inventory_cursor: Mutex<usize>,
}

impl UniversalMessengerFlavor {
    pub fn new(
        db_path: &str,
        key_bytes: &[u8; 32],
        network_tx: mpsc::Sender<(SocketAddr, Vec<u8>)>,
        dht_tx: mpsc::Sender<DhtStoreRequest>,
        #[cfg(feature = "extensions")] kns_kernel: Option<Arc<KnsKernel>>,
    ) -> Result<Arc<Self>> {
        let signing_key = SecureSigningKey::from_bytes(key_bytes);
        let verifying_key = signing_key.verifying_key();

        Ok(Arc::new(Self {
            signing_key,
            verifying_key,
            store: Arc::new(UniversalStore::new(db_path)?),
            network_tx,
            dht_tx,
            ui_tx: broadcast::channel(1024).0,

            #[cfg(feature = "extensions")]
            kns: kns_kernel,

            subscriptions: RwLock::new(HashSet::new()),
            replay_cache: Mutex::new(LruCache::new(NonZeroUsize::new(REPLAY_CACHE_SIZE).unwrap())),
            peers: RwLock::new(HashSet::new()),
            routes: RwLock::new(HashMap::new()),
            ingress: Mutex::new((0, 0)),
            last_poll: Mutex::new(0),
            inventory_cursor: Mutex::new(0),
        }))
    }

    // --- Public API ---

    pub async fn send(
        &self,
        strategy: DeliveryStrategy,
        content: MessageContent,
        resources: Vec<ResourceLink>,
        options: Option<MessageOptions>,
    ) -> Result<u128> {
        // 资源格式校验
        for res in &resources {
            if !res.validate() {
                return Err(anyhow!("Invalid resource link format: {:?}", res));
            }
        }

        let uuid = rand::random::<u128>();
        let timestamp = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
        let sender_pub_bytes = self.verifying_key.to_bytes();
        let sender_id = blake3::hash(&sender_pub_bytes).into();

        let mut msg = UniversalMessage {
            uuid,
            timestamp,
            sender_id,
            sender_pub_key: sender_pub_bytes,
            strategy: strategy.clone(),
            content,
            resources,
            options: options.unwrap_or_default(),
            signature: vec![],
        };

        msg.signature = self
            .signing_key
            .sign(&msg.signing_bytes()?)
            .to_bytes()
            .to_vec();
        msg.verify()?;

        anyhow::ensure!(
            bincode::serialized_size(&msg)? as usize + 2 <= MAX_WIRE,
            "universal wire budget"
        );
        self.store.sweep()?;
        self.store.save_msg(&msg)?;
        self.dispatch_message(msg).await?;

        Ok(uuid)
    }

    pub fn subscribe_topic(&self, topic: &str) {
        let hash = blake3::hash(topic.as_bytes()).into();
        if self.subscriptions.read().len() >= MAX_TOPICS {
            warn!("Universal subscription capacity reached");
            return;
        }
        self.subscriptions.write().insert(hash);
        info!("Universal: Subscribed to topic '{}'", topic);
    }

    /// Explicit reviewed mapping between an author identity and an engine address.
    pub fn register_peer(&self, id: NodeID, address: SocketAddr) -> Result<()> {
        anyhow::ensure!(
            address.port() != 0 && !address.ip().is_unspecified(),
            "real peer address required"
        );
        let mut routes = self.routes.write();
        anyhow::ensure!(
            routes.contains_key(&id) || routes.len() < MAX_PEERS,
            "universal route capacity"
        );
        routes.insert(id, address);
        Ok(())
    }
    /// Offline export of quarantined untrusted bytes; never authenticates/replays them.
    pub fn export_quarantined(&self, output: &mut dyn std::io::Write) -> Result<usize> {
        let tree = self.store.db.open_tree("quarantined_universal_v2")?;
        let mut count = 0;
        for entry in tree.iter() {
            let (key, value) = entry?;
            output.write_all(&(key.len() as u64).to_be_bytes())?;
            output.write_all(&(value.len() as u64).to_be_bytes())?;
            output.write_all(&key)?;
            output.write_all(&value)?;
            count += 1;
        }
        Ok(count)
    }
    pub fn local_id(&self) -> NodeID {
        *blake3::hash(&self.verifying_key.to_bytes()).as_bytes()
    }

    pub fn fetch_history(&self, limit: usize, offset: usize) -> Vec<UniversalMessage> {
        self.try_fetch_history(limit, offset)
            .unwrap_or_else(|error| {
                error!("Universal history failed: {}", error);
                Vec::new()
            })
    }
    pub fn try_fetch_history(&self, limit: usize, offset: usize) -> Result<Vec<UniversalMessage>> {
        self.store.sweep()?;
        let messages = self.store.get_history(limit, offset)?;
        for msg in &messages {
            self.store.mark_read(msg)?;
        }
        Ok(messages)
    }

    pub fn subscribe_realtime(&self) -> broadcast::Receiver<UniversalMessage> {
        self.ui_tx.subscribe()
    }

    // --- Internal Logic ---

    async fn dispatch_message(&self, msg: UniversalMessage) -> Result<()> {
        match msg.strategy {
            DeliveryStrategy::Direct { target } => {
                let route = self.routes.read().get(&target).copied();
                self.dispatch_standard_packet(STRATEGY_DIRECT, &msg, route)
                    .await?;
                self.push_to_dht_storage(target, &msg).await?;
            }
            DeliveryStrategy::Managed { server, .. } => {
                self.dispatch_standard_packet(STRATEGY_MANAGED, &msg, Some(server))
                    .await?;
            }
            DeliveryStrategy::Broadcast { .. } => {
                let peers: Vec<_> = self.peers.read().iter().copied().collect();
                anyhow::ensure!(
                    !peers.is_empty(),
                    "message stored locally; no connected broadcast peers"
                );
                for peer in peers {
                    self.dispatch_standard_packet(STRATEGY_BROADCAST, &msg, Some(peer))
                        .await?;
                }
            }
            #[cfg(feature = "extensions")]
            DeliveryStrategy::DeadDrop { target_pub_key } => {
                self.perform_dead_drop(target_pub_key, &msg).await?;
            }
        }
        Ok(())
    }

    async fn dispatch_standard_packet(
        &self,
        strategy_id: u8,
        msg: &UniversalMessage,
        target: Option<SocketAddr>,
    ) -> Result<()> {
        let payload = bincode::serialize(msg)?;
        let mut packet = vec![UNIVERSAL_PROTO_VER, strategy_id];
        packet.extend(payload);

        if let Some(t) = target {
            self.network_tx.try_send((t, packet)).map_err(|e| {
                anyhow!(
                    "message stored locally; bounded network queue unavailable: {}",
                    e
                )
            })?;
        } else {
            return Err(anyhow!(
                "message stored locally; no reviewed direct peer mapping"
            ));
        }
        Ok(())
    }

    async fn push_to_dht_storage(&self, key: NodeID, msg: &UniversalMessage) -> Result<()> {
        let data = bincode::serialize(msg)?;
        anyhow::ensure!(data.len() <= 2048, "universal DHT object budget");
        let _recipient = key;
        let req = DhtStoreRequest {
            key: *blake3::hash(&data).as_bytes(),
            value: data,
            ttl_seconds: 86400,
        };
        self.dht_tx
            .try_send(req)
            .map_err(|e| anyhow!("message stored locally; DHT enqueue failed: {}", e))?;
        Ok(())
    }

    #[cfg(feature = "extensions")]
    async fn perform_dead_drop(&self, target_pub: [u8; 32], msg: &UniversalMessage) -> Result<()> {
        let kns = self
            .kns
            .as_ref()
            .ok_or_else(|| anyhow!("KNS Kernel not available"))?;
        let content = bincode::serialize(msg)?;

        let now_day = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs() / 86400;
        let mut hasher = blake3::Hasher::new();
        hasher.update(&target_pub);
        hasher.update(&now_day.to_be_bytes());
        let domain_id = hex::encode(hasher.finalize().as_bytes());

        let ghost = Arc::new(GhostIdentity::new());
        let domain = kns.create_domain(&domain_id, ghost.clone());
        let path = KnsPath::new(vec!["drop".into()])?;

        let onion_conf = OnionConfig {
            nonce_mode: NonceMode::Random,
            padding: PaddingStrategy::BlockAligned(256),
        };
        let encrypted = OnionCrypto::seal(&target_pub, &content, &onion_conf)?;

        domain.publish(&path, &encrypted, RecordKind::Static, 3600)?;
        info!("Universal: DeadDrop to '{}'", domain_id);
        Ok(())
    }

    // --- Message Handling ---

    fn handle_incoming_msg(&self, msg: UniversalMessage, peer: SocketAddr) {
        // Authenticate before replay state, so invalid messages cannot poison UUIDs.
        if msg.verify().is_err() {
            return;
        }
        if self.store.get_msg(msg.uuid).is_some() {
            return;
        }
        if self.replay_cache.lock().contains(&msg.uuid) {
            return;
        }
        match msg.strategy {
            DeliveryStrategy::Direct { target } if target != self.local_id() => return,
            DeliveryStrategy::Managed { target, .. } if target != self.local_id() => {
                let route = self.routes.read().get(&target).copied();
                if let Some(address) = route {
                    if address != peer && self.queue_packet(STRATEGY_MANAGED, &msg, address).is_ok()
                    {
                        self.replay_cache.lock().put(msg.uuid, msg.timestamp);
                    }
                }
                return;
            }
            _ => {}
        }
        // 4. Strategy Filter
        if let DeliveryStrategy::Broadcast { topic_hash } = msg.strategy {
            if !self.subscriptions.read().contains(&topic_hash) {
                return;
            }
        }

        // 5. Store & Notify
        if let Ok(is_new) = self.store.save_msg(&msg) {
            if is_new {
                self.replay_cache.lock().put(msg.uuid, msg.timestamp);
                let _ = self.ui_tx.send(msg.clone());
            }
        }
    }

    // --- Control Handling (Gossip Sync) ---

    fn queue_packet(&self, strategy: u8, msg: &UniversalMessage, peer: SocketAddr) -> Result<()> {
        let mut packet = vec![UNIVERSAL_PROTO_VER, strategy];
        packet.extend(bincode::serialize(msg)?);
        anyhow::ensure!(packet.len() <= MAX_WIRE, "universal wire budget");
        self.network_tx
            .try_send((peer, packet))
            .map_err(|e| anyhow!("universal queue unavailable: {}", e))
    }
    fn handle_control_msg(&self, peer: SocketAddr, data: &[u8]) {
        match decode::<ControlMessage>(data) {
            Ok(ControlMessage::SyncOffer {
                topic_hashes,
                bloom_bits,
                time_range,
            }) => {
                if topic_hashes.len() > MAX_TOPICS
                    || bloom_bits.len() != SYNC_BLOOM_SIZE_BITS / 8
                    || time_range.0 > time_range.1
                {
                    return;
                }
                // 收到对方的 Sync Offer
                // 1. 检查是否有共同订阅的话题
                let my_subs = self.subscriptions.read();
                let common_topics: HashSet<_> = my_subs
                    .intersection(&topic_hashes.into_iter().collect())
                    .cloned()
                    .collect();

                if common_topics.is_empty() {
                    return;
                }

                // 2. 查找本地在这些话题下的消息
                let bloom = SyncBloom::from_bytes(bloom_bits);
                let local_uuids =
                    self.store
                        .get_uuids_in_range(&common_topics, time_range.0, time_range.1);

                let mut missing_in_remote = Vec::new();
                for uuid in local_uuids {
                    // 如果对方 Bloom Filter 里没有这个 UUID，说明对方缺这个消息
                    // Bloom Filter 可能假阳性 (False Positive)，但不会假阴性 (False Negative)。
                    // 所以如果 contains 返回 false，对方一定没有。
                    if !bloom.contains(&uuid.to_be_bytes()) {
                        missing_in_remote.push(uuid);
                    }
                }

                // 3. 推送缺失消息
                if !missing_in_remote.is_empty() {
                    debug!(
                        "Universal: Syncing {} msgs to {}",
                        missing_in_remote.len(),
                        peer
                    );
                    for uuid in missing_in_remote.iter().take(50) {
                        // Limit burst
                        if let Some(msg) = self.store.get_msg(*uuid) {
                            let _ = self.queue_packet(STRATEGY_BROADCAST, &msg, peer);
                        }
                    }
                }
            }
            Ok(ControlMessage::Inventory { uuids }) => {
                if uuids.len() > 32 {
                    return;
                }
                let missing: Vec<_> = uuids
                    .into_iter()
                    .filter(|id| self.store.get_msg(*id).is_none())
                    .collect();
                if !missing.is_empty() {
                    if let Ok(body) =
                        bincode::serialize(&ControlMessage::SyncRequest { uuids: missing })
                    {
                        let mut packet = vec![UNIVERSAL_PROTO_VER, STRATEGY_CONTROL];
                        packet.extend(body);
                        let _ = self.network_tx.try_send((peer, packet));
                    }
                }
            }
            Ok(ControlMessage::SyncRequest { uuids }) => {
                if uuids.len() > 32 {
                    return;
                }
                for uuid in uuids {
                    if let Some(msg) = self.store.get_msg(uuid) {
                        if let DeliveryStrategy::Broadcast { topic_hash } = msg.strategy {
                            if self.subscriptions.read().contains(&topic_hash) {
                                let _ = self.queue_packet(STRATEGY_BROADCAST, &msg, peer);
                            }
                        }
                    }
                }
            }
            Err(_) => {}
        }
    }
}

// --- Plugin Interface ---

impl std::fmt::Debug for UniversalMessengerFlavor {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("UniversalMessengerFlavor")
            .finish_non_exhaustive()
    }
}

impl CapabilityProvider for UniversalMessengerFlavor {
    fn capability_id(&self) -> String {
        "etp.flavor.universal.v3".into()
    }
}

impl Flavor for UniversalMessengerFlavor {
    fn priority(&self) -> u8 {
        200
    }

    fn on_stream_data(&self, ctx: FlavorContext, data: &[u8]) -> bool {
        if data.len() < 2 || data.len() > MAX_WIRE || data[0] != UNIVERSAL_PROTO_VER {
            return false;
        }

        {
            let now = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs()
                / 60;
            let mut budget = self.ingress.lock();
            if budget.0 != now {
                *budget = (now, 0);
            }
            if budget.1 >= 512 {
                return true;
            }
            budget.1 += 1;
        }
        let strategy_id = data[1];
        let payload = &data[2..];

        if strategy_id == STRATEGY_CONTROL {
            self.handle_control_msg(ctx.src_addr, payload);
            return true;
        }

        if let Ok(msg) = decode::<UniversalMessage>(payload) {
            if !matches!(
                (strategy_id, msg.strategy),
                (STRATEGY_DIRECT, DeliveryStrategy::Direct { .. })
                    | (STRATEGY_MANAGED, DeliveryStrategy::Managed { .. })
                    | (STRATEGY_BROADCAST, DeliveryStrategy::Broadcast { .. })
            ) {
                return false;
            }
            self.handle_incoming_msg(msg, ctx.src_addr);
            return true;
        }
        false
    }

    fn on_connection_open(&self, peer: SocketAddr) {
        {
            let mut peers = self.peers.write();
            if peers.len() >= MAX_PEERS {
                return;
            }
            peers.insert(peer);
        }
        // 发起 Gossip 同步
        let topics: Vec<[u8; 32]> = self.subscriptions.read().iter().cloned().collect();
        if topics.is_empty() {
            return;
        }

        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs();
        let start = now.saturating_sub(3600); // Sync last 1 hour

        // 构建 Bloom Filter
        let mut bloom = SyncBloom::new();
        // 简单策略：把这1小时内所有订阅话题下的消息ID都放进去
        let topic_set: HashSet<_> = topics.iter().cloned().collect();
        let uuids = self.store.get_uuids_in_range(&topic_set, start, now);
        for uuid in uuids {
            bloom.insert(&uuid.to_be_bytes());
        }

        let offer = ControlMessage::SyncOffer {
            topic_hashes: topics,
            bloom_bits: bloom.bits,
            time_range: (start, now),
        };

        if let Ok(data) = bincode::serialize(&offer) {
            let mut packet = vec![UNIVERSAL_PROTO_VER, STRATEGY_CONTROL];
            packet.extend(data);

            if packet.len() <= MAX_WIRE {
                let _ = self.network_tx.try_send((peer, packet));
            }
        }
    }

    fn poll(&self) {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();
        {
            let mut last = self.last_poll.lock();
            if now.saturating_sub(*last) < 60 {
                return;
            }
            *last = now;
        }
        if let Err(error) = self.store.sweep() {
            warn!("Universal expiry failed: {}", error);
        }
        let topics = self.subscriptions.read().clone();
        let ids = self.store.get_uuids_in_range(
            &topics,
            now.saturating_sub(MSG_TIME_WINDOW_SEC * 100),
            now,
        );
        let peers: Vec<_> = self.peers.read().iter().copied().collect();
        if peers.is_empty() {
            return;
        }
        let mut cursor = self.inventory_cursor.lock();
        let begin = if ids.is_empty() {
            0
        } else {
            *cursor % ids.len()
        };
        let batch = ids[begin..].iter().take(32).copied().collect();
        if let Ok(body) = bincode::serialize(&ControlMessage::Inventory { uuids: batch }) {
            let mut packet = vec![UNIVERSAL_PROTO_VER, STRATEGY_CONTROL];
            packet.extend(body);
            let mut queued = false;
            for peer in peers {
                if self.network_tx.try_send((peer, packet.clone())).is_ok() {
                    queued = true;
                }
            }
            if queued {
                *cursor = begin + 32;
            }
        }
    }
    fn on_connection_close(&self, peer: SocketAddr) {
        self.peers.write().remove(&peer);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::plugin::SystemContext;
    struct Directory(std::path::PathBuf);
    impl Directory {
        fn new() -> Self {
            let path = std::env::temp_dir().join(format!(
                "etp-universal-{}-{}",
                std::process::id(),
                rand::random::<u128>()
            ));
            std::fs::create_dir(&path).unwrap();
            Self(path)
        }
        fn path(&self) -> &std::path::Path {
            &self.0
        }
    }
    impl Drop for Directory {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }
    struct ContextImpl;
    impl SystemContext for ContextImpl {
        fn lookup_peer(&self, _: &NodeID) -> Option<SocketAddr> {
            None
        }
        fn is_connected(&self, _: SocketAddr) -> bool {
            true
        }
        fn my_node_id(&self) -> NodeID {
            [0; 32]
        }
    }
    fn instance(
        path: &str,
        key: u8,
        tx: mpsc::Sender<(SocketAddr, Vec<u8>)>,
    ) -> Arc<UniversalMessengerFlavor> {
        let (dht, _) = mpsc::channel(16);
        UniversalMessengerFlavor::new(
            path,
            &[key; 32],
            tx,
            dht,
            #[cfg(feature = "extensions")]
            None,
        )
        .unwrap()
    }
    #[tokio::test]
    async fn signed_broadcast_real_udp_storage_and_invalid_replay_do_not_poison() {
        let root = Directory::new();
        let (tx, mut rx) = mpsc::channel(16);
        let sender = instance(root.path().join("a").to_str().unwrap(), 1, tx);
        let (tx, _) = mpsc::channel(16);
        let receiver = instance(root.path().join("b").to_str().unwrap(), 2, tx);
        let udp = tokio::net::UdpSocket::bind("127.0.0.1:0").await.unwrap();
        let remote = tokio::net::UdpSocket::bind("127.0.0.1:0").await.unwrap();
        let peer = remote.local_addr().unwrap();
        sender.on_connection_open(peer);
        receiver.subscribe_topic("topic");
        let topic_hash = *blake3::hash(b"topic").as_bytes();
        sender
            .send(
                DeliveryStrategy::Broadcast { topic_hash },
                MessageContent::Text("signed text".into()),
                vec![],
                None,
            )
            .await
            .unwrap();
        let (_, packet) = tokio::time::timeout(Duration::from_secs(2), rx.recv())
            .await
            .unwrap()
            .unwrap();
        udp.send_to(&packet, peer).await.unwrap();
        let mut bytes = [0; MAX_WIRE];
        let (len, source) =
            tokio::time::timeout(Duration::from_secs(2), remote.recv_from(&mut bytes))
                .await
                .unwrap()
                .unwrap();
        let mut forged = decode::<UniversalMessage>(&bytes[2..len]).unwrap();
        forged.signature[0] ^= 1;
        receiver.handle_incoming_msg(forged, source);
        assert!(receiver.try_fetch_history(16, 0).unwrap().is_empty());
        assert!(receiver.on_stream_data(
            FlavorContext {
                src_addr: source,
                stream_id: 1,
                data_len: len,
                system: &ContextImpl
            },
            &bytes[..len]
        ));
        let history = receiver.try_fetch_history(16, 0).unwrap();
        assert_eq!(history.len(), 1);
        assert!(history[0].verify().is_ok());
        let id = history[0].uuid;
        assert!(receiver.store.get_msg(id).is_some());
        receiver.handle_incoming_msg(history[0].clone(), source);
        assert_eq!(receiver.try_fetch_history(16, 0).unwrap().len(), 1);
    }
    #[tokio::test]
    async fn invalid_bloom_unknown_route_and_read_deadline_are_explicit() {
        let root = Directory::new();
        let (tx, _) = mpsc::channel(16);
        let sender = instance(root.path().join("a").to_str().unwrap(), 3, tx);
        assert!(sender
            .send(
                DeliveryStrategy::Direct { target: [7; 32] },
                MessageContent::Text("local intent".into()),
                vec![],
                None
            )
            .await
            .is_err());
        let mut msg = sender.try_fetch_history(1, 0).unwrap().remove(0);
        msg.options.delete_after_read_secs = 1;
        msg.uuid = msg.uuid.wrapping_add(1);
        msg.signature = sender
            .signing_key
            .sign(&msg.signing_bytes().unwrap())
            .to_bytes()
            .to_vec();
        sender.store.save_msg(&msg).unwrap();
        sender.try_fetch_history(16, 0).unwrap();
        let deadlines = sender.store.db.open_tree("read_deadlines_v3").unwrap();
        deadlines
            .insert(msg.uuid.to_be_bytes(), 0u64.to_be_bytes().as_slice())
            .unwrap();
        sender.store.sweep().unwrap();
        assert!(sender.store.get_msg(msg.uuid).is_none());
        sender.subscribe_topic("topic");
        let malformed = ControlMessage::SyncOffer {
            topic_hashes: vec![*blake3::hash(b"topic").as_bytes()],
            bloom_bits: vec![],
            time_range: (0, u64::MAX),
        };
        sender.handle_control_msg(
            "127.0.0.1:12345".parse().unwrap(),
            &bincode::serialize(&malformed).unwrap(),
        );
        assert!(decode::<UniversalMessage>(&vec![0; MAX_WIRE + 1]).is_err());
    }
}
