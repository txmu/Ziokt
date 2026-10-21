// etp-core/src/plugin/flavors/forum.rs

use anyhow::{anyhow, Context, Result};
use bincode::Options;
use blake3;
use ed25519_dalek::{Signature, Signer, SigningKey, VerifyingKey};
use log::{debug, info, warn};
use parking_lot::RwLock;
use sled::transaction::{ConflictableTransactionError, Transactional};

use serde::{Deserialize, Serialize};
use sled::Db;
use std::collections::{HashMap, HashSet, VecDeque};
use std::net::SocketAddr;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};
use tokio::sync::mpsc;

use crate::common::DhtStoreRequest;
#[cfg(feature = "extensions")]
use crate::extensions::identity::EtpIdentity;
use crate::plugin::{CapabilityProvider, Flavor, FlavorContext};
use crate::NodeID;

// --- 协议常量 ---
const FORUM_PROTO_VER: u8 = 0x02;
const CMD_POST_PUSH: u8 = 0x01; // 推送新帖子
const CMD_SYNC_OFFER: u8 = 0x02; // 发送 Bloom Filter 进行同步
const CMD_FETCH_REQ: u8 = 0x03; // Request a specific retained post from a peer

const SYNC_INTERVAL_SECS: u64 = 60; // 每分钟同步一次
const POST_TTL: u64 = 86400 * 30; // 帖子保留 30 天
const BLOOM_SIZE_BITS: usize = 32768; // 4 KiB, ~2.2% false positives at 4096 posts
const BLOOM_HASH_FUNCS: usize = 5;
const MAX_POST_BYTES: usize = 32 * 1024;
const MAX_POSTS: usize = 4096;
const MAX_TOPICS: usize = 64;
const CMD_INVENTORY: u8 = 4;
const CMD_FRAGMENT: u8 = 5;
const FRAGMENT_BYTES: usize = 850;
const MAX_FRAGMENTS: usize = (MAX_POST_BYTES + 1024 + FRAGMENT_BYTES - 1) / FRAGMENT_BYTES;
struct PartialMessage {
    started: u64,
    parts: Vec<Option<Vec<u8>>>,
}

const PEER_WINDOW_BYTES: usize = 2 * 1024 * 1024;
const PEER_WINDOW_PACKETS: usize = 512;
#[derive(Default)]
struct PeerBudget {
    start: u64,
    bytes: usize,
    packets: usize,
}
impl PeerBudget {
    fn admit(&mut self, bytes: usize) -> bool {
        let now = now_secs();
        if now.saturating_sub(self.start) >= SYNC_INTERVAL_SECS {
            *self = Self {
                start: now,
                ..Self::default()
            };
        }
        if self.packets >= PEER_WINDOW_PACKETS
            || self.bytes.saturating_add(bytes) > PEER_WINDOW_BYTES
        {
            return false;
        }
        self.packets += 1;
        self.bytes += bytes;
        true
    }
}

// --- 数据结构 ---

/// 论坛帖子实体
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ForumPost {
    /// 帖子唯一 Hash (Content Addressable)
    pub id: [u8; 32],
    /// 话题/板块 Hash (用于订阅分类)
    pub topic_hash: [u8; 32],
    /// 作者 ID (None 表示匿名)
    pub author_id: Option<NodeID>,
    /// 发布时间
    pub timestamp: i64,
    /// 内容 (UTF-8 文本或 Markdown)
    pub content: String,
    /// 引用/回复的帖子 ID
    pub parent_id: Option<[u8; 32]>,
    /// v2 proof: Ed25519 public key (32 bytes) followed by signature (64). Anonymous: empty.
    pub signature: Vec<u8>,
}

impl ForumPost {
    fn canonical(&self) -> Vec<u8> {
        let mut bytes = b"ETP/FORUM/POST/v2\0".to_vec();
        bytes.extend_from_slice(&self.topic_hash);
        bytes.extend_from_slice(&self.timestamp.to_be_bytes());
        bytes.push(self.author_id.is_some() as u8);
        if let Some(author) = self.author_id {
            bytes.extend_from_slice(&author);
        }
        bytes.push(self.parent_id.is_some() as u8);
        if let Some(parent) = self.parent_id {
            bytes.extend_from_slice(&parent);
        }
        bytes.extend_from_slice(&(self.content.len() as u64).to_be_bytes());
        bytes.extend_from_slice(self.content.as_bytes());
        bytes
    }

    pub fn calculate_id(&self) -> [u8; 32] {
        blake3::hash(&self.canonical()).into()
    }

    pub fn sign(&mut self, key: &SigningKey) {
        let public = key.verifying_key().to_bytes();
        self.author_id = Some(blake3::hash(&public).into());
        self.id = self.calculate_id();
        self.signature = public.to_vec();
        self.signature
            .extend_from_slice(&key.sign(&self.canonical()).to_bytes());
    }

    pub fn verify(&self) -> bool {
        let now = now_secs() as i64;
        self.timestamp >= now - POST_TTL as i64
            && self.timestamp <= now + 300
            && self.verify_integrity()
    }

    fn verify_integrity(&self) -> bool {
        if self.content.is_empty()
            || self.content.len() > MAX_POST_BYTES
            || self.id != self.calculate_id()
            || self.parent_id == Some(self.id)
        {
            return false;
        }
        match self.author_id {
            None => self.signature.is_empty(),
            Some(author) => {
                if self.signature.len() != 96 {
                    return false;
                }
                let public: [u8; 32] = self.signature[..32].try_into().unwrap();
                if author != *blake3::hash(&public).as_bytes() {
                    return false;
                }
                let Ok(key) = VerifyingKey::from_bytes(&public) else {
                    return false;
                };
                let Ok(signature) = Signature::from_slice(&self.signature[32..]) else {
                    return false;
                };
                key.verify_strict(&self.canonical(), &signature).is_ok()
            }
        }
    }
}

/// 生产级 Bloom Filter 实现 (固定大小，便于网络传输)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PostBloomFilter {
    pub bits: Vec<u8>,
    pub timestamp_start: i64, // 涵盖的时间范围
    pub timestamp_end: i64,
    pub topic_filter: Option<[u8; 32]>, // 仅同步特定话题
}

impl PostBloomFilter {
    pub fn new(topic: Option<[u8; 32]>, start: i64, end: i64) -> Self {
        Self {
            bits: vec![0u8; BLOOM_SIZE_BITS / 8],
            timestamp_start: start,
            timestamp_end: end,
            topic_filter: topic,
        }
    }

    pub fn insert(&mut self, item: &[u8]) {
        if self.bits.len() != BLOOM_SIZE_BITS / 8 {
            return;
        }
        for i in 0..BLOOM_HASH_FUNCS {
            let idx = self.get_hash_index(item, i);
            let byte_idx = idx / 8;
            let bit_idx = idx % 8;
            self.bits[byte_idx] |= 1 << bit_idx;
        }
    }

    pub fn contains(&self, item: &[u8]) -> bool {
        if self.bits.len() != BLOOM_SIZE_BITS / 8 {
            return false;
        }
        for i in 0..BLOOM_HASH_FUNCS {
            let idx = self.get_hash_index(item, i);
            let byte_idx = idx / 8;
            let bit_idx = idx % 8;
            if (self.bits[byte_idx] & (1 << bit_idx)) == 0 {
                return false;
            }
        }
        true
    }

    fn get_hash_index(&self, item: &[u8], seed: usize) -> usize {
        let mut hasher = blake3::Hasher::new();
        hasher.update(&(seed as u64).to_le_bytes());
        hasher.update(item);
        let hash = hasher.finalize();
        // 取前 8 字节转为 usize
        let mut bytes = [0u8; 8];
        bytes.copy_from_slice(&hash.as_bytes()[0..8]);
        (u64::from_le_bytes(bytes) as usize) % BLOOM_SIZE_BITS
    }
}

/// Status of the immediate parent only; this never asserts whole-thread completeness.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ParentStatus {
    NotReply,
    Available,
    MissingOrExpired,
}

/// 论坛存储引擎
pub struct ForumStore {
    db: Db,
    mutation: parking_lot::Mutex<()>,
    last_cleanup: AtomicU64,
}

impl ForumStore {
    pub fn open(path: &str) -> Result<Self> {
        let db = sled::open(path).context("Failed to open Forum DB")?;
        let store = Self {
            db,
            mutation: parking_lot::Mutex::new(()),
            last_cleanup: AtomicU64::new(0),
        };
        store.prune()?;
        Ok(store)
    }

    pub fn save_post(&self, post: &ForumPost) -> Result<bool> {
        if !post.verify() {
            return Err(anyhow!("invalid or expired forum post"));
        }
        let _guard = self.mutation.lock();
        self.prune()?;
        let posts = self.db.open_tree("posts")?;
        let indexes = self.db.open_tree("indexes")?;
        let bytes = bincode::serialize(post)?;
        if let Some(existing) = posts.get(post.id)? {
            if existing.as_ref() != bytes.as_slice() {
                return Err(anyhow!("conflicting post ID"));
            }
            return Ok(false);
        }
        if posts.len() >= MAX_POSTS {
            return Err(anyhow!("forum capacity reached"));
        }
        let key = index_key(post);
        (&posts, &indexes)
            .transaction(|(p, i)| {
                p.insert(post.id.as_slice(), bytes.as_slice())?;
                i.insert(key.as_slice(), post.id.as_slice())?;
                Ok::<_, ConflictableTransactionError<()>>(())
            })
            .map_err(|e| anyhow!("forum transaction: {:?}", e))?;
        self.db.flush()?;
        Ok(true)
    }

    fn prune(&self) -> Result<()> {
        let now = now_secs();
        let last = self.last_cleanup.load(Ordering::Relaxed);
        if last != 0 && now.saturating_sub(last) < SYNC_INTERVAL_SECS {
            return Ok(());
        }
        if self
            .last_cleanup
            .compare_exchange(last, now, Ordering::Relaxed, Ordering::Relaxed)
            .is_err()
        {
            return Ok(());
        }
        let posts = self.db.open_tree("posts")?;
        let indexes = self.db.open_tree("indexes")?;
        let quarantine = self.db.open_tree("quarantined_posts_v1")?;
        let mut changed = false;
        for entry in posts.iter() {
            let (id, bytes) = entry?;
            let post = decode::<ForumPost>(&bytes).ok();
            if post
                .as_ref()
                .map_or(true, |p| !p.verify() || p.id.as_slice() != id.as_ref())
            {
                (&posts, &indexes, &quarantine)
                    .transaction(|(p, i, q)| {
                        // Preserve untrusted legacy/malformed bytes exactly.
                        // Only valid v2 expiration is ordinary TTL removal.
                        if post.as_ref().map_or(true, |post| {
                            !post.verify_integrity()
                                || post.id.as_slice() != id.as_ref()
                                || post.timestamp >= now as i64 - POST_TTL as i64
                        }) {
                            q.insert(id.as_ref(), bytes.as_ref())?;
                        }
                        p.remove(id.as_ref())?;
                        if let Some(ref post) = post {
                            i.remove(index_key(post))?;
                        }
                        Ok::<_, ConflictableTransactionError<()>>(())
                    })
                    .map_err(|e| anyhow!("forum prune: {:?}", e))?;
                changed = true;
            }
        }
        if changed {
            self.db.flush()?;
        }
        Ok(())
    }

    /// Export untrusted records as length-prefixed bincode (raw key, raw value).
    /// Export does not decode, authenticate, republish or delete any record.
    pub fn export_quarantined_posts(&self, output: &mut dyn std::io::Write) -> Result<usize> {
        let tree = self.db.open_tree("quarantined_posts_v1")?;
        let mut count = 0;
        for entry in tree.iter() {
            let (key, value) = entry?;
            let bytes = bincode::serialize(&(key.to_vec(), value.to_vec()))?;
            output.write_all(&(bytes.len() as u64).to_be_bytes())?;
            output.write_all(&bytes)?;
            count += 1;
        }
        Ok(count)
    }

    /// 获取时间范围内的帖子 ID (用于构建 Bloom Filter 或响应 Sync)
    /// Bounded stable identity inventory for application cursors. Original native
    /// signatures, TTL and topic/author bindings are checked before IDs are exposed.
    pub fn snapshot_ids(&self, topic: [u8; 32], author: [u8; 32]) -> Result<Vec<[u8; 32]>> {
        let _guard = self.mutation.lock();
        let posts = self.db.open_tree("posts")?;
        anyhow::ensure!(posts.len() <= MAX_POSTS, "forum capacity exceeded");
        let mut ids = Vec::new();
        for item in posts.iter() {
            let (key, bytes) = item?;
            if let Ok(post) = decode::<ForumPost>(&bytes) {
                if post.verify()
                    && post.topic_hash == topic
                    && post.author_id == Some(author)
                    && post.id.as_slice() == key.as_ref()
                {
                    ids.push(post.id);
                }
            }
        }
        ids.sort_unstable();
        Ok(ids)
    }

    pub fn get_posts_in_range(
        &self,
        topic: Option<[u8; 32]>,
        start: i64,
        end: i64,
    ) -> Vec<ForumPost> {
        let index_tree = match self.db.open_tree("indexes") {
            Ok(t) => t,
            Err(_) => return vec![],
        };

        let posts_tree = match self.db.open_tree("posts") {
            Ok(t) => t,
            Err(_) => return vec![],
        };

        // Total storage is capped, so an all-topic query also has a fixed bound.
        if start > end {
            return Vec::new();
        }
        let mut results = Vec::new();

        if let Some(t_hash) = topic {
            let mut start_key = t_hash.to_vec();
            start_key.extend_from_slice(&start.to_be_bytes());

            let mut end_key = t_hash.to_vec();
            end_key.extend_from_slice(&end.to_be_bytes());
            // Append max value to end_key to cover the full second
            end_key.extend_from_slice(&[0xFF; 32]);

            for item in index_tree.range(start_key..=end_key) {
                if let Ok((_, post_id_bytes)) = item {
                    if let Ok(Some(post_bytes)) = posts_tree.get(&post_id_bytes) {
                        if let Ok(post) = decode::<ForumPost>(&post_bytes) {
                            if post.verify()
                                && post.topic_hash == t_hash
                                && post.timestamp >= start
                                && post.timestamp <= end
                                && post_id_bytes.as_ref() == post.id.as_slice()
                            {
                                results.push(post);
                            }
                        }
                    }
                }
            }
        } else {
            for item in posts_tree.iter().take(MAX_POSTS) {
                if let Ok((_, bytes)) = item {
                    if let Ok(post) = decode::<ForumPost>(&bytes) {
                        if post.timestamp >= start && post.timestamp <= end && post.verify() {
                            results.push(post);
                        }
                    }
                }
            }
        }

        results
    }

    pub fn parent_status(&self, post: &ForumPost) -> ParentStatus {
        match post.parent_id {
            None => ParentStatus::NotReply,
            Some(id) if self.get_post(&id).is_some() => ParentStatus::Available,
            Some(_) => ParentStatus::MissingOrExpired,
        }
    }

    pub fn get_post(&self, id: &[u8]) -> Option<ForumPost> {
        let tree = self.db.open_tree("posts").ok()?;
        let bytes = tree.get(id).ok()??;
        decode::<ForumPost>(&bytes)
            .ok()
            .filter(|post| post.verify() && post.id.as_slice() == id)
    }
}

// --- Forum Flavor ---

pub struct ForumFlavor {
    store: Arc<ForumStore>,
    #[cfg(feature = "extensions")]
    identity: Option<Arc<dyn EtpIdentity>>,
    dht_tx: mpsc::Sender<DhtStoreRequest>,
    network_tx: mpsc::Sender<(SocketAddr, Vec<u8>)>,

    /// 订阅列表 (本地感兴趣的话题)
    subscriptions: RwLock<HashSet<[u8; 32]>>,

    /// 最后同步时间 (PeerAddr -> Timestamp)
    /// 防止频繁向同一个 Peer 发送 Sync Offer
    sync_status: RwLock<lru::LruCache<SocketAddr, u64>>,
    inventory_cursor: RwLock<HashMap<(SocketAddr, [u8; 32]), usize>>,
    topic_cursor: RwLock<HashMap<SocketAddr, usize>>,
    inbound_budget: parking_lot::Mutex<lru::LruCache<SocketAddr, PeerBudget>>,
    outbound_budget: parking_lot::Mutex<lru::LruCache<SocketAddr, PeerBudget>>,
    partial: parking_lot::Mutex<lru::LruCache<(SocketAddr, [u8; 32]), PartialMessage>>,
    outbox: parking_lot::Mutex<VecDeque<(SocketAddr, Vec<u8>)>>,
}

impl ForumFlavor {
    pub fn new(
        db_path: &str,
        dht_tx: mpsc::Sender<DhtStoreRequest>,
        network_tx: mpsc::Sender<(SocketAddr, Vec<u8>)>,
    ) -> Result<Arc<Self>> {
        let store = Arc::new(ForumStore::open(db_path)?);
        let subscription_tree = store.db.open_tree("subscriptions_v2")?;
        if subscription_tree.len() > MAX_TOPICS {
            return Err(anyhow!("persisted subscription budget"));
        }
        let mut subscriptions = HashSet::new();
        for item in subscription_tree.iter() {
            let (key, value) = item?;
            if key.len() != 32 || !value.is_empty() {
                return Err(anyhow!("invalid persisted subscription"));
            }
            subscriptions.insert(
                key.as_ref()
                    .try_into()
                    .map_err(|_| anyhow!("invalid persisted topic"))?,
            );
        }

        Ok(Arc::new(Self {
            store,
            #[cfg(feature = "extensions")]
            identity: None,
            dht_tx,
            network_tx,
            subscriptions: RwLock::new(subscriptions),
            inventory_cursor: RwLock::new(HashMap::new()),
            topic_cursor: RwLock::new(HashMap::new()),
            outbox: parking_lot::Mutex::new(VecDeque::new()),
            partial: parking_lot::Mutex::new(lru::LruCache::new(
                std::num::NonZeroUsize::new(128).unwrap(),
            )),
            inbound_budget: parking_lot::Mutex::new(lru::LruCache::new(
                std::num::NonZeroUsize::new(100).unwrap(),
            )),
            outbound_budget: parking_lot::Mutex::new(lru::LruCache::new(
                std::num::NonZeroUsize::new(100).unwrap(),
            )),
            sync_status: RwLock::new(lru::LruCache::new(
                std::num::NonZeroUsize::new(100).unwrap(),
            )),
        }))
    }

    /// Attach an existing ETP Ed25519 identity without exporting its private key.
    #[cfg(feature = "extensions")]
    pub fn new_with_identity(
        db_path: &str,
        dht_tx: mpsc::Sender<DhtStoreRequest>,
        network_tx: mpsc::Sender<(SocketAddr, Vec<u8>)>,
        identity: Arc<dyn EtpIdentity>,
    ) -> Result<Arc<Self>> {
        let public = identity.public_key();
        if public.len() != 32 || identity.node_id() != *blake3::hash(&public).as_bytes() {
            return Err(anyhow!(
                "Forum requires an Ed25519 identity bound to its public key"
            ));
        }
        if identity
            .expiration()
            .map_or(false, |expiry| expiry <= SystemTime::now())
        {
            return Err(anyhow!("expired Forum identity"));
        }
        let public: [u8; 32] = public
            .as_slice()
            .try_into()
            .map_err(|_| anyhow!("invalid Ed25519 key length"))?;
        let verifying = VerifyingKey::from_bytes(&public)?;
        let challenge = b"ETP/FORUM/IDENTITY/v2\0";
        let proof = identity.sign(challenge)?;
        verifying.verify_strict(challenge, &Signature::from_slice(&proof)?)?;
        let mut flavor = Self::new(db_path, dht_tx, network_tx)?;
        Arc::get_mut(&mut flavor)
            .ok_or_else(|| anyhow!("Forum initialization unexpectedly shared"))?
            .identity = Some(identity);
        Ok(flavor)
    }

    pub fn get_post(&self, id: &[u8; 32]) -> Option<ForumPost> {
        self.store.get_post(id)
    }

    pub fn parent_status(&self, post: &ForumPost) -> ParentStatus {
        self.store.parent_status(post)
    }

    pub fn snapshot_ids(&self, topic: [u8; 32], author: [u8; 32]) -> Result<Vec<[u8; 32]>> {
        self.store.snapshot_ids(topic, author)
    }

    pub fn local_author_id(&self) -> Option<NodeID> {
        #[cfg(feature = "extensions")]
        {
            self.identity.as_ref().map(|identity| identity.node_id())
        }
        #[cfg(not(feature = "extensions"))]
        {
            None
        }
    }

    /// Publish anonymously, or sign with the attached identity matching author_id.
    pub async fn publish_post(
        &self,
        content: &str,
        topic: &str,
        author_id: Option<NodeID>,
    ) -> Result<()> {
        let timestamp = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs() as i64;
        let topic_hash = blake3::hash(topic.as_bytes()).into();

        let mut post = ForumPost {
            id: [0; 32],
            topic_hash,
            author_id,
            timestamp,
            content: content.to_string(),
            parent_id: None,
            signature: vec![], // Anonymous posts carry no identity proof.
        };

        if let Some(author) = author_id {
            self.sign_with_local_identity(&mut post, author)?;
        }
        post.id = post.calculate_id();
        self.publish(post).await
    }

    #[cfg(feature = "extensions")]
    fn sign_with_local_identity(&self, post: &mut ForumPost, author: NodeID) -> Result<()> {
        let identity = self.identity.as_ref().ok_or_else(|| {
            anyhow!("authenticated publishing requires an attached identity or publish_signed_post")
        })?;
        if identity.node_id() != author {
            return Err(anyhow!("requested author does not match local identity"));
        }
        if identity
            .expiration()
            .map_or(false, |expiry| expiry <= SystemTime::now())
        {
            return Err(anyhow!("local Forum identity expired"));
        }
        let public = identity.public_key();
        if public.len() != 32 || author != *blake3::hash(&public).as_bytes() {
            return Err(anyhow!("local Forum identity changed during publication"));
        }
        post.signature = public;
        post.signature.extend(identity.sign(&post.canonical())?);
        Ok(())
    }
    #[cfg(not(feature = "extensions"))]
    fn sign_with_local_identity(&self, _: &mut ForumPost, _: NodeID) -> Result<()> {
        Err(anyhow!(
            "attached identities require extensions; use publish_signed_post"
        ))
    }

    pub async fn publish_signed_post(
        &self,
        content: &str,
        topic: &str,
        parent_id: Option<[u8; 32]>,
        key: &SigningKey,
    ) -> Result<()> {
        let mut post = ForumPost {
            id: [0; 32],
            topic_hash: blake3::hash(topic.as_bytes()).into(),
            author_id: None,
            timestamp: now_secs() as i64,
            content: content.into(),
            parent_id,
            signature: vec![],
        };
        post.sign(key);
        self.publish(post).await
    }

    async fn publish(&self, post: ForumPost) -> Result<()> {
        // 1. 本地存储
        self.store.save_post(&post)?;
        info!(
            "Forum: Published post {:?} to topic '{}'",
            hex::encode(post.id),
            hex::encode(post.topic_hash)
        );

        // 2. 序列化
        let payload_bytes = bincode::serialize(&post)?;

        // The existing Engine STORE protocol accepts <=2048 bytes, <=1 day,
        // and a BLAKE3 key over the exact serialized value (not canonical post ID).
        let dht_result = if payload_bytes.len() > 2048 {
            Err(anyhow!(
                "post persisted locally; DHT object exceeds 2048 byte limit"
            ))
        } else {
            self.dht_tx
                .try_send(DhtStoreRequest {
                    key: blake3::hash(&payload_bytes).into(),
                    value: payload_bytes.clone(),
                    ttl_seconds: 86400,
                })
                .map_err(|e| anyhow!("post persisted locally; DHT enqueue failed: {}", e))
        };

        // 4. 主动广播给邻居 (Gossip Push)
        // 构造 Packet: [Ver][CMD_POST][Data]
        let mut net_pkg = vec![FORUM_PROTO_VER, CMD_POST_PUSH];
        net_pkg.extend(payload_bytes);

        for peer in self.peers() {
            self.send(peer, net_pkg.clone());
        }
        dht_result
    }

    /// Err means local admission/durability failed. Ok reports DHT admission;
    /// the post has been flushed even when remote submission is unavailable.
    pub async fn publish_prepared_post(&self, post: ForumPost) -> Result<bool> {
        self.store.save_post(&post)?;
        // Also establish durability for a duplicate left visible by a previous
        // failed flush; visibility alone must never become a stored ACK.
        self.store.db.flush()?;
        Ok(self.publish(post).await.is_ok())
    }

    pub fn subscribe(&self, topic: &str) {
        if let Err(error) = self.try_subscribe(topic) {
            warn!("Forum subscription rejected: {}", error);
        }
    }
    pub fn try_subscribe(&self, topic: &str) -> Result<()> {
        let hash = blake3::hash(topic.as_bytes()).into();
        let mut topics = self.subscriptions.write();
        if !topics.contains(&hash) && topics.len() >= MAX_TOPICS {
            return Err(anyhow!("Forum subscription budget"));
        }
        if !topics.contains(&hash) {
            self.store
                .db
                .open_tree("subscriptions_v2")?
                .insert(hash, &[])?;
            self.store.db.flush()?;
            topics.insert(hash);
        }
        Ok(())
    }

    /// 生成 Sync Offer (Bloom Filter)
    fn generate_sync_offer(&self, topic: [u8; 32]) -> Vec<u8> {
        let now = now_secs() as i64;
        let start = now - POST_TTL as i64;

        let posts = self.store.get_posts_in_range(Some(topic), start, now);
        let mut bf = PostBloomFilter::new(Some(topic), start, now);

        for post in posts {
            bf.insert(&post.id);
        }

        bincode::serialize(&bf).unwrap_or_default()
    }
}

fn admit_peer(
    budgets: &parking_lot::Mutex<lru::LruCache<SocketAddr, PeerBudget>>,
    peer: SocketAddr,
    bytes: usize,
) -> bool {
    let mut budgets = budgets.lock();
    if !budgets.contains(&peer) {
        budgets.put(peer, PeerBudget::default());
    }
    budgets
        .get_mut(&peer)
        .map_or(false, |budget| budget.admit(bytes))
}
fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}
fn index_key(post: &ForumPost) -> Vec<u8> {
    let mut key = post.topic_hash.to_vec();
    key.extend(post.timestamp.to_be_bytes());
    key.extend(post.id);
    key
}
fn decode<T: serde::de::DeserializeOwned>(data: &[u8]) -> Result<T> {
    if data.len() > MAX_POST_BYTES + 1024 {
        return Err(anyhow!("forum decode byte limit"));
    }
    Ok(bincode::DefaultOptions::new()
        .with_fixint_encoding()
        .with_limit((MAX_POST_BYTES + 1024) as u64)
        .reject_trailing_bytes()
        .deserialize(data)?)
}
impl ForumFlavor {
    fn peers(&self) -> Vec<SocketAddr> {
        self.sync_status
            .read()
            .iter()
            .map(|(peer, _)| *peer)
            .collect()
    }
    fn send(&self, peer: SocketAddr, packet: Vec<u8>) -> bool {
        if packet.len() <= 1024 {
            return self.send_frame(peer, packet);
        }
        if packet.len() > MAX_POST_BYTES + 1024 {
            return false;
        }
        let id = blake3::hash(&packet);
        let count = (packet.len() + FRAGMENT_BYTES - 1) / FRAGMENT_BYTES;
        self.flush_outbox();
        // Avoid starting a message that does not fit the current bounded backlog.
        if self.outbox.lock().len() + count > 512 {
            return false;
        }
        for (index, part) in packet.chunks(FRAGMENT_BYTES).enumerate() {
            let mut fragment = vec![FORUM_PROTO_VER, CMD_FRAGMENT];
            fragment.extend(id.as_bytes());
            fragment.extend((index as u16).to_be_bytes());
            fragment.extend((count as u16).to_be_bytes());
            fragment.extend(part);
            if !self.send_frame(peer, fragment) {
                return false;
            }
        }
        true
    }
    fn flush_outbox(&self) {
        let mut outbox = self.outbox.lock();
        while let Some(packet) = outbox.pop_front() {
            match self.network_tx.try_send(packet) {
                Ok(()) => (),
                Err(mpsc::error::TrySendError::Full(packet)) => {
                    outbox.push_front(packet);
                    break;
                }
                Err(mpsc::error::TrySendError::Closed(_)) => {
                    outbox.clear();
                    break;
                }
            }
        }
    }
    fn send_frame(&self, peer: SocketAddr, packet: Vec<u8>) -> bool {
        if !admit_peer(&self.outbound_budget, peer, packet.len()) {
            return false;
        }
        self.flush_outbox();
        let mut outbox = self.outbox.lock();
        if !outbox.is_empty() {
            if outbox.len() >= 512 {
                return false;
            }
            outbox.push_back((peer, packet));
            return true;
        }
        match self.network_tx.try_send((peer, packet)) {
            Ok(()) => true,
            Err(mpsc::error::TrySendError::Full(packet)) => {
                outbox.push_back(packet);
                true
            }
            Err(mpsc::error::TrySendError::Closed(_)) => false,
        }
    }
    fn receive_fragment(&self, peer: SocketAddr, data: &[u8]) -> Option<Vec<u8>> {
        if data.len() < 39 || data.len() > 38 + FRAGMENT_BYTES {
            return None;
        }
        let id: [u8; 32] = data[2..34].try_into().ok()?;
        let index = u16::from_be_bytes(data[34..36].try_into().ok()?) as usize;
        let count = u16::from_be_bytes(data[36..38].try_into().ok()?) as usize;
        if count < 2
            || count > MAX_FRAGMENTS
            || index >= count
            || (index + 1 < count && data.len() != 38 + FRAGMENT_BYTES)
        {
            return None;
        }
        let key = (peer, id);
        let mut partial = self.partial.lock();
        let expired = partial.get(&key).map_or(false, |message| {
            now_secs().saturating_sub(message.started) >= SYNC_INTERVAL_SECS
        });
        if expired {
            partial.pop(&key);
        }
        if !partial.contains(&key) {
            partial.put(
                key,
                PartialMessage {
                    started: now_secs(),
                    parts: vec![None; count],
                },
            );
        }
        let message = partial.get_mut(&key)?;
        if message.parts.len() != count {
            partial.pop(&key);
            return None;
        }
        if let Some(existing) = &message.parts[index] {
            if existing.as_slice() != &data[38..] {
                partial.pop(&key);
                return None;
            }
        }
        message.parts[index] = Some(data[38..].to_vec());
        if message.parts.iter().any(Option::is_none) {
            return None;
        }
        let message = partial.pop(&key)?;
        let bytes: Vec<u8> = message.parts.into_iter().flatten().flatten().collect();
        if bytes.len() > MAX_POST_BYTES + 1024
            || bytes.len() < 2
            || bytes[0] != FORUM_PROTO_VER
            || bytes[1] == CMD_FRAGMENT
            || *blake3::hash(&bytes).as_bytes() != id
        {
            return None;
        }
        Some(bytes)
    }
    fn sync_peer(&self, peer: SocketAddr) -> bool {
        let mut topics: Vec<_> = self.subscriptions.read().iter().copied().collect();
        topics.sort_unstable();
        let offset = self
            .topic_cursor
            .read()
            .get(&peer)
            .copied()
            .unwrap_or(0)
            .min(topics.len());
        for (index, topic) in topics.iter().enumerate().skip(offset) {
            let mut packet = vec![FORUM_PROTO_VER, CMD_SYNC_OFFER];
            packet.extend(self.generate_sync_offer(*topic));
            if !self.send(peer, packet) {
                self.topic_cursor.write().insert(peer, index);
                return false;
            }
            self.topic_cursor.write().insert(peer, index + 1);
        }
        self.topic_cursor.write().remove(&peer);
        true
    }
}

impl CapabilityProvider for ForumFlavor {
    fn capability_id(&self) -> String {
        "etp.flavor.forum.v2".into()
    }
}

impl Flavor for ForumFlavor {
    fn priority(&self) -> u8 {
        50
    }

    fn on_stream_data(&self, ctx: FlavorContext, data: &[u8]) -> bool {
        if data.len() < 2 || data.len() > MAX_POST_BYTES + 1024 || data[0] != FORUM_PROTO_VER {
            return false;
        }

        if !admit_peer(&self.inbound_budget, ctx.src_addr, data.len()) {
            return true;
        }
        match data[1] {
            CMD_FRAGMENT => {
                if let Some(bytes) = self.receive_fragment(ctx.src_addr, data) {
                    self.on_stream_data(
                        FlavorContext {
                            data_len: bytes.len(),
                            ..ctx
                        },
                        &bytes,
                    );
                }
                true
            }
            CMD_POST_PUSH => {
                if let Ok(post) = decode::<ForumPost>(&data[2..]) {
                    if !post.verify() {
                        warn!("Forum: Received invalid post");
                        return true;
                    }

                    // 检查是否是我们订阅的话题
                    if self.subscriptions.read().contains(&post.topic_hash) {
                        if let Ok(is_new) = self.store.save_post(&post) {
                            if is_new {
                                info!("Forum: New post received in topic {:?}", post.topic_hash);
                                if let Some(parent) = post.parent_id {
                                    if self.store.get_post(&parent).is_none() {
                                        let mut packet = vec![FORUM_PROTO_VER, CMD_FETCH_REQ];
                                        packet.extend(parent);
                                        self.send(ctx.src_addr, packet);
                                    }
                                }
                                for peer in self.peers() {
                                    if peer != ctx.src_addr {
                                        self.send(peer, data.to_vec());
                                    }
                                }
                            }
                        }
                    }
                }
                true
            }
            CMD_SYNC_OFFER => {
                // 收到对方的 Bloom Filter
                if let Ok(remote_bf) = decode::<PostBloomFilter>(&data[2..]) {
                    if remote_bf.bits.len() != BLOOM_SIZE_BITS / 8
                        || remote_bf.timestamp_start < now_secs() as i64 - POST_TTL as i64 - 300
                        || remote_bf.timestamp_end > now_secs() as i64 + 300
                        || remote_bf.timestamp_start > remote_bf.timestamp_end
                    {
                        return true;
                    }
                    // 只有当我们也订阅了该话题时才处理
                    if let Some(topic) = remote_bf.topic_filter {
                        if self.subscriptions.read().contains(&topic) {
                            // 检查本地有哪些帖子是对方没有的 (I have, remote doesn't)
                            let local_posts = self.store.get_posts_in_range(
                                Some(topic),
                                remote_bf.timestamp_start,
                                remote_bf.timestamp_end,
                            );

                            // Exact inventory makes Bloom false positives recoverable.
                            if !local_posts.is_empty() {
                                let mut cursors = self.inventory_cursor.write();
                                // Only connected peers get persistent cursors (bounded by peer/topic limits).
                                let offset = if self.sync_status.read().contains(&ctx.src_addr) {
                                    *cursors.entry((ctx.src_addr, topic)).or_insert(0)
                                } else {
                                    0
                                };
                                let ids: Vec<[u8; 32]> = local_posts
                                    .iter()
                                    .cycle()
                                    .skip(offset % local_posts.len())
                                    .take(local_posts.len().min(32))
                                    .map(|p| p.id)
                                    .collect();
                                if let Ok(bytes) = bincode::serialize(&(topic, ids)) {
                                    let mut packet = vec![FORUM_PROTO_VER, CMD_INVENTORY];
                                    packet.extend(bytes);
                                    if self.send(ctx.src_addr, packet)
                                        && self.sync_status.read().contains(&ctx.src_addr)
                                    {
                                        cursors.insert(
                                            (ctx.src_addr, topic),
                                            (offset + 32) % local_posts.len(),
                                        );
                                    }
                                }
                            }
                            let mut push_count = 0;
                            for post in local_posts {
                                if !remote_bf.contains(&post.id) {
                                    // 对方缺失，推送给对方
                                    if push_count >= 20 {
                                        break;
                                    } // 限流

                                    if let Ok(bytes) = bincode::serialize(&post) {
                                        let mut pkg = vec![FORUM_PROTO_VER, CMD_POST_PUSH];
                                        pkg.extend(bytes);
                                        self.send(ctx.src_addr, pkg);
                                        push_count += 1;
                                    }
                                }
                            }
                            if push_count > 0 {
                                debug!("Forum: Synced {} posts to {}", push_count, ctx.src_addr);
                            }
                        }
                    }
                }
                true
            }
            CMD_INVENTORY => {
                if let Ok((topic, ids)) = decode::<([u8; 32], Vec<[u8; 32]>)>(&data[2..]) {
                    if ids.len() <= 128 && self.subscriptions.read().contains(&topic) {
                        for id in ids {
                            if self.store.get_post(&id).is_none() {
                                let mut packet = vec![FORUM_PROTO_VER, CMD_FETCH_REQ];
                                packet.extend(id);
                                self.send(ctx.src_addr, packet);
                            }
                        }
                    }
                }
                true
            }
            CMD_FETCH_REQ => {
                // Peer fallback: the existing Engine has no DHT GET operation.
                // Payload: [ID(32)]
                if data.len() != 34 {
                    return true;
                }
                let id = &data[2..34];

                if let Some(post) = self.store.get_post(id) {
                    if let Ok(bytes) = bincode::serialize(&post) {
                        let mut pkg = vec![FORUM_PROTO_VER, CMD_POST_PUSH];
                        pkg.extend(bytes);
                        self.send(ctx.src_addr, pkg);
                    }
                }
                true
            }
            _ => false,
        }
    }

    fn on_connection_open(&self, peer: SocketAddr) {
        let evicted = self.sync_status.write().push(peer, now_secs());
        if let Some((old, _)) = evicted {
            self.topic_cursor.write().remove(&old);
            self.inventory_cursor
                .write()
                .retain(|(addr, _), _| *addr != old);
        }
        if !self.sync_peer(peer) {
            self.sync_status.write().put(peer, 0);
        }
    }

    fn on_connection_close(&self, peer: SocketAddr) {
        self.topic_cursor.write().remove(&peer);
        self.outbox.lock().retain(|(addr, _)| *addr != peer);
        self.sync_status.write().pop(&peer);
        self.inventory_cursor
            .write()
            .retain(|(addr, _), _| *addr != peer);
        let stale: Vec<_> = self
            .partial
            .lock()
            .iter()
            .filter(|((addr, _), _)| *addr == peer)
            .map(|(key, _)| *key)
            .collect();
        for key in stale {
            self.partial.lock().pop(&key);
        }
    }

    fn poll(&self) {
        self.flush_outbox();
        let now = now_secs();
        let stale: Vec<_> = self
            .partial
            .lock()
            .iter()
            .filter(|(_, message)| now.saturating_sub(message.started) >= SYNC_INTERVAL_SECS)
            .map(|(key, _)| *key)
            .collect();
        for key in stale {
            self.partial.lock().pop(&key);
        }
        let due: Vec<_> = self
            .sync_status
            .read()
            .iter()
            .filter(|(_, last)| now.saturating_sub(**last) >= SYNC_INTERVAL_SECS)
            .map(|(peer, _)| *peer)
            .collect();
        for peer in due {
            if self.sync_peer(peer) {
                self.sync_status.write().put(peer, now);
            }
        }
        if let Err(e) = self.store.prune() {
            warn!("Forum cleanup failed: {}", e);
        }
    }
}
impl std::fmt::Debug for ForumFlavor {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ForumFlavor").finish_non_exhaustive()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::plugin::SystemContext;
    use tokio::net::UdpSocket;

    static NEXT: AtomicU64 = AtomicU64::new(0);
    struct Directory(std::path::PathBuf);
    impl Directory {
        fn new() -> Self {
            Self(std::env::temp_dir().join(format!(
                "etp-forum-{}-{}-{}",
                std::process::id(),
                now_secs(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            )))
        }
        fn path(&self) -> &str {
            self.0.to_str().unwrap()
        }
    }
    impl Drop for Directory {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }
    fn signed(content: &str) -> ForumPost {
        let mut post = ForumPost {
            id: [0; 32],
            topic_hash: [8; 32],
            author_id: None,
            timestamp: now_secs() as i64,
            content: content.into(),
            parent_id: None,
            signature: vec![],
        };
        post.sign(&SigningKey::from_bytes(&[42; 32]));
        post
    }
    #[test]
    fn application_inventory_verifies_scope_and_late_arrivals() {
        let dir = Directory::new();
        let store = ForumStore::open(dir.path()).unwrap();
        let first = signed("current");
        store.save_post(&first).unwrap();
        assert_eq!(
            store
                .snapshot_ids([8; 32], first.author_id.unwrap())
                .unwrap(),
            vec![first.id]
        );
        assert!(store
            .snapshot_ids([9; 32], first.author_id.unwrap())
            .unwrap()
            .is_empty());
        assert!(store.snapshot_ids([8; 32], [0; 32]).unwrap().is_empty());
        let mut late = signed("late timestamp");
        late.timestamp -= 3600;
        late.sign(&SigningKey::from_bytes(&[42; 32]));
        store.save_post(&late).unwrap();
        let mut expected = vec![first.id, late.id];
        expected.sort_unstable();
        assert_eq!(
            store
                .snapshot_ids([8; 32], first.author_id.unwrap())
                .unwrap(),
            expected
        );
        drop(store);
        let store = ForumStore::open(dir.path()).unwrap();
        assert_eq!(
            store
                .snapshot_ids([8; 32], first.author_id.unwrap())
                .unwrap(),
            expected
        );
    }

    #[test]
    fn subscriptions_persist_and_reopen_without_network_side_effects() {
        let dir = Directory::new();
        {
            let (tx, mut rx) = mpsc::channel(1);
            let (dht, _dht_rx) = mpsc::channel(1);
            let forum = ForumFlavor::new(dir.path(), dht, tx).unwrap();
            forum.try_subscribe("persisted").unwrap();
            assert!(rx.try_recv().is_err());
        }
        let (tx, mut rx) = mpsc::channel(1);
        let (dht, _dht_rx) = mpsc::channel(1);
        let forum = ForumFlavor::new(dir.path(), dht, tx).unwrap();
        assert!(forum
            .subscriptions
            .read()
            .contains(blake3::hash(b"persisted").as_bytes()));
        assert!(rx.try_recv().is_err());
        for index in 0..63 {
            forum.try_subscribe(&format!("topic-{index}")).unwrap();
        }
        assert!(forum.try_subscribe("overflow").is_err());
        assert_eq!(forum.subscriptions.read().len(), 64);
    }
    #[test]
    fn signatures_bind_identity_topic_parent_and_content() {
        let post = signed("signed");
        assert!(post.verify());
        for field in 0..6 {
            let mut changed = post.clone();
            match field {
                0 => changed.topic_hash[0] ^= 1,
                1 => changed.parent_id = Some([3; 32]),
                2 => changed.content.push('!'),
                3 => changed.author_id = Some([0; 32]),
                4 => changed.signature[40] ^= 1,
                _ => changed.timestamp += 1,
            }
            changed.id = changed.calculate_id();
            assert!(!changed.verify(), "tampered field {field}");
        }
        let mut anonymous = post.clone();
        anonymous.author_id = None;
        anonymous.id = anonymous.calculate_id();
        assert!(!anonymous.verify());
        anonymous.signature.clear();
        assert!(anonymous.verify());
        let mut legacy = post;
        legacy.signature = vec![1];
        assert!(!legacy.verify());
    }
    #[test]
    fn transactional_store_deduplicates_reopens_and_expires() {
        let dir = Directory::new();
        let post = signed("durable");
        {
            let store = ForumStore::open(dir.path()).unwrap();
            assert!(store.save_post(&post).unwrap());
            assert!(!store.save_post(&post).unwrap());
            assert_eq!(
                store.get_posts_in_range(Some(post.topic_hash), post.timestamp, post.timestamp),
                vec![post.clone()]
            );
            let mut old = signed("old");
            old.timestamp -= POST_TTL as i64 + 1;
            old.sign(&SigningKey::from_bytes(&[42; 32]));
            assert!(store.save_post(&old).is_err());
            let mut conflict = post.clone();
            conflict.content.push('x');
            assert!(store.save_post(&conflict).is_err());
        }
        let store = ForumStore::open(dir.path()).unwrap();
        assert_eq!(store.get_post(&post.id), Some(post));
    }
    #[test]
    fn retained_child_reports_expired_parent_without_claiming_complete_thread() {
        let dir = Directory::new();
        let store = ForumStore::open(dir.path()).unwrap();
        let mut parent = signed("expired parent");
        parent.timestamp -= POST_TTL as i64 + 1;
        parent.sign(&SigningKey::from_bytes(&[42; 32]));
        store
            .db
            .open_tree("posts")
            .unwrap()
            .insert(parent.id, bincode::serialize(&parent).unwrap())
            .unwrap();
        let mut child = signed("retained child");
        child.parent_id = Some(parent.id);
        child.sign(&SigningKey::from_bytes(&[42; 32]));
        assert!(store.save_post(&child).unwrap());
        assert!(child.verify());
        assert_eq!(store.parent_status(&child), ParentStatus::MissingOrExpired);
        store.last_cleanup.store(0, Ordering::Relaxed);
        store.prune().unwrap();
        assert!(store
            .db
            .open_tree("posts")
            .unwrap()
            .get(parent.id)
            .unwrap()
            .is_none());
        assert_eq!(store.get_post(&child.id), Some(child.clone()));
        assert_eq!(store.parent_status(&child), ParentStatus::MissingOrExpired);
    }
    #[test]
    fn legacy_records_are_quarantined_and_exported_without_loss() {
        let dir = Directory::new();
        let mut legacy = signed("historical content");
        legacy.id = [7; 32];
        legacy.signature = vec![1];
        let bytes = bincode::serialize(&legacy).unwrap();
        {
            let db = sled::open(dir.path()).unwrap();
            db.open_tree("posts")
                .unwrap()
                .insert(legacy.id, bytes.clone())
                .unwrap();
            db.flush().unwrap();
        }
        let store = ForumStore::open(dir.path()).unwrap();
        assert!(store.get_post(&legacy.id).is_none());
        let mut export = Vec::new();
        assert_eq!(store.export_quarantined_posts(&mut export).unwrap(), 1);
        let length = u64::from_be_bytes(export[..8].try_into().unwrap()) as usize;
        let (id, value): (Vec<u8>, Vec<u8>) = bincode::deserialize(&export[8..8 + length]).unwrap();
        assert_eq!(id, legacy.id);
        assert_eq!(value, bytes);
        let mut second = Vec::new();
        assert_eq!(store.export_quarantined_posts(&mut second).unwrap(), 1);
        assert_eq!(export, second);
    }
    #[test]
    fn peer_packet_and_byte_budgets_are_bounded() {
        let mut budget = PeerBudget::default();
        assert!(budget.admit(PEER_WINDOW_BYTES));
        assert!(!budget.admit(1));
        let mut budget = PeerBudget::default();
        for _ in 0..PEER_WINDOW_PACKETS {
            assert!(budget.admit(1));
        }
        assert!(!budget.admit(1));
        budget.start = now_secs().saturating_sub(SYNC_INTERVAL_SECS);
        assert!(budget.admit(1));
    }
    fn anonymous(content: String) -> ForumPost {
        let mut post = ForumPost {
            id: [0; 32],
            topic_hash: [8; 32],
            author_id: None,
            timestamp: now_secs() as i64,
            content,
            parent_id: None,
            signature: vec![],
        };
        post.id = post.calculate_id();
        post
    }
    #[test]
    fn bloom_budget_has_no_false_negatives_and_bounded_fixture_false_positives() {
        let mut bloom = PostBloomFilter::new(None, 0, 1);
        for index in 0..MAX_POSTS as u64 {
            bloom.insert(blake3::hash(&index.to_be_bytes()).as_bytes());
        }
        for index in 0..MAX_POSTS as u64 {
            assert!(bloom.contains(blake3::hash(&index.to_be_bytes()).as_bytes()));
        }
        let false_positives = (MAX_POSTS as u64..2 * MAX_POSTS as u64)
            .filter(|index| bloom.contains(blake3::hash(&index.to_be_bytes()).as_bytes()))
            .count();
        assert_eq!(bloom.bits.len(), 4096);
        assert_eq!(BLOOM_HASH_FUNCS, 5);
        assert!(
            false_positives < MAX_POSTS / 16,
            "deterministic false positive fixture: {false_positives}"
        );
    }
    #[test]
    fn real_sled_capacity_boundary_preserves_all_admitted_posts() {
        let dir = Directory::new();
        {
            let store = ForumStore::open(dir.path()).unwrap();
            for index in 0..MAX_POSTS {
                assert!(store
                    .save_post(&anonymous(format!("capacity-{index}")))
                    .unwrap());
            }
            assert_eq!(store.db.open_tree("posts").unwrap().len(), MAX_POSTS);
            assert_eq!(store.db.open_tree("indexes").unwrap().len(), MAX_POSTS);
            let existing = store
                .get_posts_in_range(Some([8; 32]), 0, now_secs() as i64)
                .pop()
                .unwrap();
            assert!(!store.save_post(&existing).unwrap());
            assert!(store
                .save_post(&anonymous("capacity-overflow".into()))
                .unwrap_err()
                .to_string()
                .contains("capacity"));
        }
        let store = ForumStore::open(dir.path()).unwrap();
        assert_eq!(
            store
                .get_posts_in_range(Some([8; 32]), 0, now_secs() as i64)
                .len(),
            MAX_POSTS
        );
        assert!(store
            .save_post(&anonymous("still-full-after-reopen".into()))
            .is_err());
    }
    #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
    async fn concurrent_publish_uses_real_sled_atomic_indexes() {
        let dir = Directory::new();
        let (tx, _rx) = mpsc::channel(1);
        let (dht, _dht_rx) = mpsc::channel(256);
        let flavor = ForumFlavor::new(dir.path(), dht, tx).unwrap();
        let mut writers = Vec::new();
        for worker in 0..16 {
            let flavor = flavor.clone();
            writers.push(tokio::spawn(async move {
                for index in 0..8 {
                    flavor
                        .publish_post(&format!("writer-{worker}-{index}"), "concurrent", None)
                        .await
                        .unwrap();
                }
            }));
        }
        for writer in writers {
            writer.await.unwrap();
        }
        let topic = blake3::hash(b"concurrent").into();
        let posts = flavor
            .store
            .get_posts_in_range(Some(topic), 0, now_secs() as i64);
        assert_eq!(posts.len(), 128);
        assert!(posts.iter().all(ForumPost::verify));
        assert_eq!(flavor.store.db.open_tree("indexes").unwrap().len(), 128);
        drop(flavor);
        let reopened = ForumStore::open(dir.path()).unwrap();
        assert_eq!(
            reopened
                .get_posts_in_range(Some(topic), 0, now_secs() as i64)
                .len(),
            128
        );
    }
    #[test]
    fn corrupted_lengths_and_bytes_are_quarantined_across_reopen() {
        let dir = Directory::new();
        let mut forged_length = bincode::serialize(&anonymous("length".into())).unwrap();
        // id32 + topic32 + author-option1 + timestamp8 precede the string length.
        forged_length[73..81].copy_from_slice(&u64::MAX.to_le_bytes());
        let garbage = vec![0xff; 17];
        {
            let db = sled::open(dir.path()).unwrap();
            let tree = db.open_tree("posts").unwrap();
            tree.insert([1; 32], forged_length.clone()).unwrap();
            tree.insert([2; 32], garbage.clone()).unwrap();
            db.flush().unwrap();
        }
        for _ in 0..2 {
            let store = ForumStore::open(dir.path()).unwrap();
            assert!(store.get_post(&[1; 32]).is_none());
            assert!(store.get_post(&[2; 32]).is_none());
            let quarantine = store.db.open_tree("quarantined_posts_v1").unwrap();
            assert_eq!(
                quarantine.get([1; 32]).unwrap().unwrap().as_ref(),
                forged_length.as_slice()
            );
            assert_eq!(
                quarantine.get([2; 32]).unwrap().unwrap().as_ref(),
                garbage.as_slice()
            );
            let mut export = Vec::new();
            assert_eq!(store.export_quarantined_posts(&mut export).unwrap(), 2);
        }
    }
    #[test]
    fn cross_protocol_signatures_and_retargeted_parent_proofs_are_rejected() {
        let key = SigningKey::from_bytes(&[42; 32]);
        let mut post = signed("cross-domain");
        let mut chat = crate::plugin::flavors::chat::ChatMessage {
            msg_id: 1,
            sender_pub_key: key.verifying_key().to_bytes(),
            receiver_id: [9; 32],
            timestamp: post.timestamp,
            content_type: "text/plain".into(),
            content: post.canonical(),
            signature: vec![],
        };
        let foreign = chat.signing_bytes();
        chat.signature = key.sign(&foreign).to_bytes().to_vec();
        assert!(chat.verify().is_ok());
        post.signature[32..].copy_from_slice(&chat.signature);
        assert!(!post.verify());
        let mut post = signed("reply");
        post.parent_id = Some([1; 32]);
        post.sign(&key);
        assert!(post.verify());
        post.parent_id = Some([2; 32]);
        post.id = post.calculate_id();
        assert!(!post.verify());
        let mut parent = signed("untrusted parent");
        parent.signature[32] ^= 1;
        let dir = Directory::new();
        let store = ForumStore::open(dir.path()).unwrap();
        assert!(store.save_post(&parent).is_err());
        let mut child = signed("valid reply to untrusted parent");
        child.parent_id = Some(parent.id);
        child.sign(&key);
        assert!(store.save_post(&child).unwrap());
        assert_eq!(store.parent_status(&child), ParentStatus::MissingOrExpired);
    }
    #[test]
    fn malformed_bloom_and_oversized_post_are_rejected() {
        let mut bloom = PostBloomFilter::new(None, 0, 1);
        bloom.bits.clear();
        assert!(!bloom.contains(&[1; 32]));
        let post = signed(&"x".repeat(MAX_POST_BYTES + 1));
        assert!(!post.verify());
        let mut bytes = bincode::serialize(&signed("trailing")).unwrap();
        bytes.push(0);
        assert!(decode::<ForumPost>(&bytes).is_err());
    }
    struct LocalSystem;
    impl SystemContext for LocalSystem {
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
    // These adapters transport actual Forum wire packets over loopback UDP; no
    // mocked store, signature verifier or protocol handler is used.
    struct Endpoint {
        flavor: Arc<ForumFlavor>,
        socket: UdpSocket,
        outgoing: mpsc::Receiver<(SocketAddr, Vec<u8>)>,
        _dht: mpsc::Receiver<DhtStoreRequest>,
        _dir: Directory,
    }
    impl Endpoint {
        async fn new() -> Self {
            Self::with_capacity(256).await
        }
        async fn with_capacity(capacity: usize) -> Self {
            let dir = Directory::new();
            let (tx, outgoing) = mpsc::channel(capacity);
            let (dht, receiver) = mpsc::channel(256);
            let flavor = ForumFlavor::new(dir.path(), dht, tx).unwrap();
            flavor.subscribe("integration");
            Self {
                flavor,
                socket: UdpSocket::bind("127.0.0.1:0").await.unwrap(),
                outgoing,
                _dht: receiver,
                _dir: dir,
            }
        }
        fn addr(&self) -> SocketAddr {
            self.socket.local_addr().unwrap()
        }
        async fn transmit(&mut self) -> usize {
            let mut sent = 0;
            while let Ok((addr, bytes)) = self.outgoing.try_recv() {
                assert!(
                    bytes.len() <= 1024,
                    "packet must fit actual Engine app-data limit"
                );
                self.socket.send_to(&bytes, addr).await.unwrap();
                sent += 1;
            }
            sent
        }
        async fn receive(&self) -> usize {
            let mut count = 0;
            let mut buffer = vec![0; MAX_POST_BYTES + 1024];
            while let Ok(Ok((size, src))) = tokio::time::timeout(
                std::time::Duration::from_millis(10),
                self.socket.recv_from(&mut buffer),
            )
            .await
            {
                self.flavor.on_stream_data(
                    FlavorContext {
                        src_addr: src,
                        stream_id: 1,
                        data_len: size,
                        system: &LocalSystem,
                    },
                    &buffer[..size],
                );
                count += 1;
            }
            count
        }
    }
    async fn drain(a: &mut Endpoint, b: &mut Endpoint) {
        for _ in 0..128 {
            a.flavor.flush_outbox();
            b.flavor.flush_outbox();
            let sent = a.transmit().await + b.transmit().await;
            let received = a.receive().await + b.receive().await;
            if sent + received == 0 {
                return;
            }
        }
        panic!("protocol failed to settle");
    }
    #[tokio::test]
    async fn loopback_push_fetch_reconnect_and_false_positive_recovery() {
        let mut a = Endpoint::new().await;
        let mut b = Endpoint::new().await;
        let key = SigningKey::from_bytes(&[42; 32]);
        a.flavor
            .publish_signed_post("parent", "integration", None, &key)
            .await
            .unwrap();
        let topic = blake3::hash(b"integration").into();
        let parent = a
            .flavor
            .store
            .get_posts_in_range(Some(topic), 0, now_secs() as i64)[0]
            .clone();
        a.flavor
            .publish_signed_post("child", "integration", Some(parent.id), &key)
            .await
            .unwrap();
        let posts = a
            .flavor
            .store
            .get_posts_in_range(Some(topic), 0, now_secs() as i64);
        let child = posts.iter().find(|p| p.parent_id.is_some()).unwrap();
        // Deliver a child first: real FETCH_REQ retrieves its absent parent.
        let mut packet = vec![FORUM_PROTO_VER, CMD_POST_PUSH];
        packet.extend(bincode::serialize(child).unwrap());
        a.socket.send_to(&packet, b.addr()).await.unwrap();
        b.receive().await;
        drain(&mut a, &mut b).await;
        assert!(b.flavor.store.get_post(&parent.id).is_some());
        a.flavor.on_connection_open(b.addr());
        b.flavor.on_connection_open(a.addr());
        drain(&mut a, &mut b).await;
        a.flavor
            .publish_signed_post("live push", "integration", None, &key)
            .await
            .unwrap();
        drain(&mut a, &mut b).await;
        assert_eq!(
            b.flavor
                .store
                .get_posts_in_range(Some(topic), 0, now_secs() as i64)
                .len(),
            3
        );
        // Exercise timed synchronization using the same loopback transport.
        b.flavor.sync_status.write().put(a.addr(), 0);
        b.flavor.poll();
        drain(&mut a, &mut b).await;
        a.flavor.on_connection_close(b.addr());
        b.flavor.on_connection_close(a.addr());
        a.flavor
            .publish_signed_post("offline", "integration", None, &key)
            .await
            .unwrap();
        // A deliberately saturated filter suppresses every Bloom push. Exact
        // inventory plus FETCH_REQ must still obtain the offline post.
        let mut bloom = PostBloomFilter::new(
            Some(topic),
            now_secs() as i64 - POST_TTL as i64,
            now_secs() as i64,
        );
        bloom.bits.fill(255);
        let mut offer = vec![FORUM_PROTO_VER, CMD_SYNC_OFFER];
        offer.extend(bincode::serialize(&bloom).unwrap());
        assert!(b.flavor.send(a.addr(), offer));
        drain(&mut a, &mut b).await;
        assert_eq!(
            b.flavor
                .store
                .get_posts_in_range(Some(topic), 0, now_secs() as i64)
                .len(),
            4
        );
        a.flavor.on_connection_open(b.addr());
        b.flavor.on_connection_open(a.addr());
        drain(&mut a, &mut b).await;
        assert_eq!(
            b.flavor
                .store
                .get_posts_in_range(Some(topic), 0, now_secs() as i64)
                .len(),
            4
        );
    }
    #[tokio::test]
    async fn loopback_fragmentation_and_native_dht_store_contract() {
        let mut a = Endpoint::new().await;
        let mut b = Endpoint::new().await;
        a.flavor.on_connection_open(b.addr());
        b.flavor.on_connection_open(a.addr());
        drain(&mut a, &mut b).await;
        a.flavor
            .publish_post("DHT compatible", "integration", None)
            .await
            .unwrap();
        let req = a._dht.try_recv().unwrap();
        assert_eq!(req.key, *blake3::hash(&req.value).as_bytes());
        assert!(req.value.len() <= 2048);
        assert_eq!(req.ttl_seconds, 86400);
        drain(&mut a, &mut b).await;
        let long = "x".repeat(MAX_POST_BYTES);
        let error = a
            .flavor
            .publish_signed_post(
                &long,
                "integration",
                None,
                &SigningKey::from_bytes(&[42; 32]),
            )
            .await
            .unwrap_err();
        assert!(error.to_string().contains("persisted locally"));
        // Reverse and duplicate actual datagrams: assembly cannot depend on order.
        let mut fragments = Vec::new();
        while let Ok((target, bytes)) = a.outgoing.try_recv() {
            assert_eq!(target, b.addr());
            assert!(bytes.len() <= 1024);
            fragments.push(bytes);
        }
        assert!(fragments.len() > 1);
        for bytes in fragments.iter().rev() {
            a.socket.send_to(bytes, b.addr()).await.unwrap();
        }
        a.socket.send_to(&fragments[0], b.addr()).await.unwrap();
        b.receive().await;
        drain(&mut a, &mut b).await;
        let posts = b.flavor.store.get_posts_in_range(
            Some(blake3::hash(b"integration").into()),
            0,
            now_secs() as i64,
        );
        assert!(posts
            .iter()
            .any(|post| post.content == long && post.verify()));
    }
    #[tokio::test]
    async fn loopback_single_slot_channel_does_not_starve_fragments() {
        let mut a = Endpoint::with_capacity(1).await;
        let mut b = Endpoint::with_capacity(1).await;
        a.flavor.on_connection_open(b.addr());
        b.flavor.on_connection_open(a.addr());
        drain(&mut a, &mut b).await;
        let content = "q".repeat(4096);
        assert!(a
            .flavor
            .publish_post(&content, "integration", None)
            .await
            .is_err());
        drain(&mut a, &mut b).await;
        let posts = b.flavor.store.get_posts_in_range(
            Some(blake3::hash(b"integration").into()),
            0,
            now_secs() as i64,
        );
        assert!(posts.iter().any(|post| post.content == content));
        assert!(a.flavor.outbox.lock().len() <= 512);
    }
    #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
    async fn independent_engines_route_forum_over_real_noise_udp_streams() {
        use crate::network::node::{EtpEngine, NodeConfig, UdpTransport};
        use crate::plugin::flavors::composite::CompositeFlavor;
        use crate::plugin::{PluginRegistry, StandardFlavor};
        use crate::transport::reliability::MultiplexingMode;
        let a_dir = Directory::new();
        let b_dir = Directory::new();
        let a_socket = Arc::new(UdpSocket::bind("127.0.0.1:0").await.unwrap());
        let b_socket = Arc::new(UdpSocket::bind("127.0.0.1:0").await.unwrap());
        let a_addr = a_socket.local_addr().unwrap();
        let b_addr = b_socket.local_addr().unwrap();
        let (a_tx, mut a_rx) = mpsc::channel(512);
        let (b_tx, mut b_rx) = mpsc::channel(512);
        let (a_dht, _a_dht_rx) = mpsc::channel(256);
        let (b_dht, _b_dht_rx) = mpsc::channel(256);
        let a_forum = ForumFlavor::new(a_dir.path(), a_dht, a_tx).unwrap();
        let b_forum = ForumFlavor::new(b_dir.path(), b_dht, b_tx).unwrap();
        a_forum.subscribe("engine");
        b_forum.subscribe("engine");
        let a_registry = Arc::new(PluginRegistry::new());
        let b_registry = Arc::new(PluginRegistry::new());
        for (registry, forum) in [(&a_registry, &a_forum), (&b_registry, &b_forum)] {
            let composite = Arc::new(CompositeFlavor::new(Arc::new(StandardFlavor)));
            composite.bind_stream(3, forum.clone());
            registry.register_flavor(forum.clone());
            registry.register_flavor(composite);
        }
        let mut a_config = NodeConfig::default();
        let mut b_config = NodeConfig::default();
        a_config.default_flavor = "etp.flavor.composite.v1".into();
        b_config.default_flavor = "etp.flavor.composite.v1".into();
        a_config.multiplexing_mode = MultiplexingMode::ParallelMulti;
        b_config.multiplexing_mode = MultiplexingMode::ParallelMulti;
        a_config.trusted_peers.insert(
            b_addr,
            b_config.keypair.public.as_slice().try_into().unwrap(),
        );
        b_config.trusted_peers.insert(
            a_addr,
            a_config.keypair.public.as_slice().try_into().unwrap(),
        );
        let b_public = b_config.keypair.public.clone();
        let (a_engine, a_handle, _a_legacy) =
            EtpEngine::new_with_transport(a_config, a_registry, Arc::new(UdpTransport(a_socket)))
                .await
                .unwrap();
        let (b_engine, b_handle, _b_legacy) =
            EtpEngine::new_with_transport(b_config, b_registry, Arc::new(UdpTransport(b_socket)))
                .await
                .unwrap();
        let mut a_task = tokio::spawn(a_engine.run());
        let mut b_task = tokio::spawn(b_engine.run());
        let a_sender = a_handle.clone();
        let b_sender = b_handle.clone();
        let a_relay = tokio::spawn(async move {
            while let Some((peer, packet)) = a_rx.recv().await {
                a_sender.send_stream(peer, 3, packet).await.unwrap();
            }
        });
        let b_relay = tokio::spawn(async move {
            while let Some((peer, packet)) = b_rx.recv().await {
                b_sender.send_stream(peer, 3, packet).await.unwrap();
            }
        });
        let exchange = async {
            let key = SigningKey::from_bytes(&[42; 32]);
            a_forum
                .publish_signed_post("Engine parent", "engine", None, &key)
                .await
                .unwrap();
            let topic = blake3::hash(b"engine").into();
            let parent = a_forum
                .store
                .get_posts_in_range(Some(topic), 0, now_secs() as i64)
                .pop()
                .unwrap();
            a_handle.connect(b_addr, b_public).await.unwrap();
            while b_forum.get_post(&parent.id).is_none() {
                tokio::time::sleep(std::time::Duration::from_millis(20)).await;
            }
            let content = "Engine-fragment-".repeat(512);
            assert!(a_forum
                .publish_signed_post(&content, "engine", Some(parent.id), &key)
                .await
                .unwrap_err()
                .to_string()
                .contains("persisted locally"));
            let child = a_forum
                .store
                .get_posts_in_range(Some(topic), 0, now_secs() as i64)
                .into_iter()
                .find(|p| p.parent_id == Some(parent.id))
                .unwrap();
            while b_forum.get_post(&child.id).is_none() {
                tokio::time::sleep(std::time::Duration::from_millis(20)).await;
            }
            assert!(b_forum.get_post(&child.id).unwrap().verify());
            assert_eq!(b_forum.parent_status(&child), ParentStatus::Available);
            b_forum
                .publish_post("Engine return", "engine", None)
                .await
                .unwrap();
            while !a_forum
                .store
                .get_posts_in_range(Some(topic), 0, now_secs() as i64)
                .iter()
                .any(|post| post.content == "Engine return")
            {
                tokio::time::sleep(std::time::Duration::from_millis(20)).await;
            }
        };
        let result = tokio::time::timeout(std::time::Duration::from_secs(15), exchange).await;
        let _ = a_handle.shutdown().await;
        let _ = b_handle.shutdown().await;
        let a_stopped = tokio::time::timeout(std::time::Duration::from_secs(3), &mut a_task).await;
        let b_stopped = tokio::time::timeout(std::time::Duration::from_secs(3), &mut b_task).await;
        a_task.abort();
        b_task.abort();
        a_relay.abort();
        b_relay.abort();
        result.expect("two real Engine instances failed Forum exchange");
        a_stopped.unwrap().unwrap().unwrap();
        b_stopped.unwrap().unwrap().unwrap();
        assert!(a_forum.peers().is_empty());
        assert!(b_forum.peers().is_empty());
    }
    #[cfg(feature = "extensions")]
    #[tokio::test]
    async fn identity_manager_signs_original_publish_api() {
        let dir = Directory::new();
        let (tx, _rx) = mpsc::channel(8);
        let (dht, _dht_rx) = mpsc::channel(8);
        let identity = crate::extensions::identity::IdentityManager::create_anchor();
        let author = identity.node_id();
        let flavor = ForumFlavor::new_with_identity(dir.path(), dht, tx, identity).unwrap();
        assert_eq!(flavor.local_author_id(), Some(author));
        flavor
            .publish_post("identity API", "integration", Some(author))
            .await
            .unwrap();
        let post = flavor
            .store
            .get_posts_in_range(
                Some(blake3::hash(b"integration").into()),
                0,
                now_secs() as i64,
            )
            .pop()
            .unwrap();
        assert_eq!(post.author_id, Some(author));
        assert!(post.verify());
        assert!(flavor
            .publish_post("impersonation", "integration", Some([0; 32]))
            .await
            .is_err());
        let ghost = crate::extensions::identity::IdentityManager::create_ghost();
        let (tx, _rx) = mpsc::channel(8);
        let (dht, _rx_dht) = mpsc::channel(8);
        assert!(ForumFlavor::new_with_identity(dir.path(), dht, tx, ghost).is_err());
    }
    #[tokio::test]
    async fn dht_failure_reports_local_persistence() {
        let dir = Directory::new();
        let (tx, _rx) = mpsc::channel(8);
        let (dht, rx) = mpsc::channel(1);
        drop(rx);
        let flavor = ForumFlavor::new(dir.path(), dht, tx).unwrap();
        let error = flavor
            .publish_post("retained", "integration", None)
            .await
            .unwrap_err();
        assert!(error.to_string().contains("persisted locally"));
        assert_eq!(
            flavor
                .store
                .get_posts_in_range(
                    Some(blake3::hash(b"integration").into()),
                    0,
                    now_secs() as i64
                )
                .len(),
            1
        );
        assert!(flavor
            .publish_post("forged", "integration", Some([0; 32]))
            .await
            .is_err());
    }
}
