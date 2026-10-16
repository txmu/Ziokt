// etp-core/src/plugin/flavors/chat.rs

#![cfg(feature = "persistence")]

use anyhow::{anyhow, Context, Result};
use blake3;
use chrono::Utc;
use ed25519_dalek::{Signature, Signer, SigningKey, Verifier, VerifyingKey};
use log::{debug, error, info, trace, warn};
use rand::Rng;
use serde::{Deserialize, Serialize};
use sled::{Db, IVec};
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::sync::{broadcast, mpsc};
use x25519_dalek::{PublicKey as XPublicKey, StaticSecret};

use crate::common::DhtStoreRequest;
use crate::crypto::onion::{OnionConfig, OnionCrypto};
use crate::plugin::{CapabilityProvider, Flavor, FlavorContext};
use crate::NodeID;
use sled::transaction::{ConflictableTransactionError, Transactional};

// --- 条件编译引入模块 ---

#[cfg(feature = "countermeasures")]
use crate::countermeasures::entropy::EntropyReducer;

// --- 协议常量 ---
const CHAT_PROTO_VER: u8 = 0x03;
const CMD_MSG: u8 = 0x01;
const CMD_SYNC: u8 = 0x02;
const CMD_ACK: u8 = 0x03;
const CMD_COVER_NOISE: u8 = 0xFF; // 新增：掩护流量指令

const MAX_DIRECT_RETRIES: u32 = 3;
const RETRY_INTERVAL_SECS: u64 = 10;
const MSG_TTL_SECS: u64 = 86400 * 7; // 7天过期

// --- 数据结构 ---

/// 聊天消息实体 (存储与传输)
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ChatMessage {
    /// 全局唯一 ID (u128 UUID)
    pub msg_id: u128,
    /// 发送者身份公钥 (Ed25519)
    pub sender_pub_key: [u8; 32],
    /// 接收者 ID
    pub receiver_id: NodeID,
    /// 时间戳 (UTC)
    pub timestamp: i64,
    /// 内容类型 (MIME)
    pub content_type: String,
    /// 实际内容 (UTF-8 文本或二进制)
    pub content: Vec<u8>,
    /// v3 domain signature over sender, receiver, ID, timestamp, MIME and content.
    pub signature: Vec<u8>,
}

impl ChatMessage {
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut bytes = b"ETP/CHAT/MESSAGE/v3\0".to_vec();
        bytes.extend(self.msg_id.to_be_bytes());
        bytes.extend(self.sender_pub_key);
        bytes.extend(self.receiver_id);
        bytes.extend(self.timestamp.to_be_bytes());
        bytes.extend((self.content_type.len() as u64).to_be_bytes());
        bytes.extend(self.content_type.as_bytes());
        bytes.extend((self.content.len() as u64).to_be_bytes());
        bytes.extend(&self.content);
        bytes
    }
    pub fn verify(&self) -> Result<()> {
        let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs() as i64;
        anyhow::ensure!(
            self.content.len() <= 32768
                && !self.content.is_empty()
                && !self.content_type.is_empty()
                && self.content_type.len() <= 128
                && self.timestamp <= now + 300
                && self.timestamp >= now - MSG_TTL_SECS as i64,
            "Chat field or time budget"
        );
        VerifyingKey::from_bytes(&self.sender_pub_key)?.verify_strict(
            &self.signing_bytes(),
            &Signature::from_slice(&self.signature)?,
        )?;
        Ok(())
    }

    /// 获取发送者的 NodeID (Pubkey Hash)
    pub fn sender_node_id(&self) -> NodeID {
        blake3::hash(&self.sender_pub_key).into()
    }
}

/// 发件箱条目 (用于重试状态管理)
#[derive(Debug, Clone, Serialize, Deserialize)]
struct OutboxEntry {
    msg: ChatMessage,
    target_node_id: NodeID,
    target_enc_pub: [u8; 32], // 对方的 X25519 公钥 (用于加密重传)
    attempts: u32,
    last_attempt: u64, // Unix Timestamp
    status: MsgStatus,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
enum MsgStatus {
    Pending,
    SentToDHT, // 已转为离线投递
    Delivered, // 收到 ACK
}

/// 聊天存储引擎 (基于 Sled)
pub struct ChatStore {
    db: Db,
}

impl ChatStore {
    pub fn open(path: &str) -> Result<Self> {
        let db = sled::open(path).context("Failed to open Chat DB")?;
        let store = Self { db };
        store.quarantine_legacy()?;
        Ok(store)
    }

    fn quarantine_legacy(&self) -> Result<()> {
        let quarantine = self.db.open_tree("quarantined_chat_v2")?;
        for source in ["inbox", "outbox", "history"] {
            let tree = self.db.open_tree(source)?;
            for item in tree.iter() {
                let (key, bytes) = item?;
                let valid = if source == "outbox" {
                    crate::common::safe_deserialize::<OutboxEntry>(&bytes)
                        .map(|entry| entry.msg.verify().is_ok())
                        .unwrap_or(false)
                } else {
                    crate::common::safe_deserialize::<ChatMessage>(&bytes)
                        .map(|msg| msg.verify().is_ok())
                        .unwrap_or(false)
                };
                if !valid {
                    let record = bincode::serialize(&(source, key.to_vec(), bytes.to_vec()))?;
                    let record_id = blake3::hash(&record);
                    (&tree, &quarantine)
                        .transaction(|(active, isolated)| {
                            isolated.insert(record_id.as_bytes().as_slice(), record.as_slice())?;
                            active.remove(key.as_ref())?;
                            Ok::<_, ConflictableTransactionError<()>>(())
                        })
                        .map_err(|error| anyhow!("Chat legacy quarantine: {:?}", error))?;
                }
            }
        }
        self.db.flush()?;
        Ok(())
    }

    /// 保存收到消息 (Inbox)
    pub fn save_inbox(&self, msg: &ChatMessage) -> Result<()> {
        msg.verify()?;
        let tree = self.db.open_tree("inbox")?;
        // Key: Timestamp(BE) + MsgID (按时间排序)
        // 使用 BigEndian 确保 Sled 的字节序排序符合时间顺序
        let mut key = Vec::with_capacity(24);
        key.extend_from_slice(&msg.timestamp.to_be_bytes());
        key.extend_from_slice(&msg.msg_id.to_be_bytes());

        let value = bincode::serialize(msg)?;
        tree.insert(key, value)?;
        Ok(())
    }

    /// 保存待发送消息 (Outbox)
    fn save_outbox(&self, entry: &OutboxEntry) -> Result<()> {
        let tree = self.db.open_tree("outbox")?;
        // Key: MsgID (用于 ACK 快速查找)
        let key = entry.msg.msg_id.to_be_bytes();
        let value = bincode::serialize(entry)?;
        tree.insert(key, value)?;
        Ok(())
    }

    /// 标记消息已送达 (收到 ACK)
    pub fn mark_delivered(&self, msg_id: u128) -> Result<()> {
        let tree = self.db.open_tree("outbox")?;
        let key = msg_id.to_be_bytes();
        if let Some(val_bytes) = tree.get(&key)? {
            let mut entry: OutboxEntry = crate::common::safe_deserialize(&val_bytes)?;
            entry.status = MsgStatus::Delivered;
            // 实际上可以直接删除，或者移入 "sent_history"
            // 这里为了简洁，直接从 outbox 删除
            tree.remove(&key)?;

            // 存入历史记录
            let history = self.db.open_tree("history")?;
            history.insert(key, bincode::serialize(&entry.msg)?)?;
        }
        Ok(())
    }

    /// 获取所有挂起的消息 (用于重试)
    fn get_pending_messages(&self) -> Vec<OutboxEntry> {
        let tree = match self.db.open_tree("outbox") {
            Ok(t) => t,
            Err(_) => return vec![],
        };

        tree.iter()
            .filter_map(|res| res.ok())
            .filter_map(|(_, v)| crate::common::safe_deserialize::<OutboxEntry>(&v).ok())
            .filter(|e| e.status == MsgStatus::Pending && e.msg.verify().is_ok())
            .collect()
    }

    /// 获取目标为特定 ID 的所有消息 (用于 SYNC 响应)
    fn get_messages_for_target(&self, target_id: &NodeID) -> Vec<ChatMessage> {
        self.get_pending_messages()
            .into_iter()
            .filter(|e| e.target_node_id == *target_id)
            .map(|e| e.msg)
            .collect()
    }

    /// 更新 Outbox 条目
    fn update_outbox_entry(&self, entry: &OutboxEntry) -> Result<()> {
        self.save_outbox(entry)
    }

    /// 检查消息是否已存在 (去重)
    pub fn exists_in_inbox(&self, msg_id: u128) -> bool {
        // MVP Optimization: 暂时不做全表扫描去重，依赖上层逻辑
        false
    }

    // ========================================================================
    //  [NEW] GUI Data API
    // ========================================================================

    /// 获取历史消息列表 (支持分页，按时间倒序)
    /// 用于 GUI 客户端渲染界面
    pub fn get_history(&self, limit: usize, offset: usize) -> Result<Vec<ChatMessage>> {
        let tree = self.db.open_tree("inbox")?;

        // Sled 的迭代器是按 Key 排序的 (Timestamp 升序)。
        // 为了显示最新消息，我们需要 rev() (Timestamp 降序)。
        let iter = tree.iter().rev();

        let messages: Vec<ChatMessage> = iter
            .skip(offset)
            .take(limit)
            .filter_map(|res| res.ok())
            .filter_map(|(_, v)| crate::common::safe_deserialize::<ChatMessage>(&v).ok())
            .filter(|msg| msg.verify().is_ok())
            .collect();

        Ok(messages)
    }
}

// --- Chat Flavor ---

pub struct ChatFlavor {
    /// 身份密钥
    signing_key: SigningKey,
    verifying_key: VerifyingKey,
    /// 加密密钥
    decryption_key: StaticSecret,

    /// 存储
    store: Arc<ChatStore>,

    /// 通道
    ui_tx: broadcast::Sender<ChatMessage>,
    dht_tx: mpsc::Sender<DhtStoreRequest>,
    /// 网络发送通道 (用于主动发包，如 Retry 或 Sync)
    network_tx: mpsc::Sender<(SocketAddr, Vec<u8>)>,

    // --- 新特性状态 ---
    #[cfg(feature = "anonymity")]
    last_real_traffic: parking_lot::Mutex<std::time::Instant>,
}

impl ChatFlavor {
    pub fn new(
        db_path: &str,
        signing_key_bytes: &[u8; 32],
        decryption_key_bytes: &[u8; 32],
        dht_tx: mpsc::Sender<DhtStoreRequest>,
        network_tx: mpsc::Sender<(SocketAddr, Vec<u8>)>,
    ) -> Result<Arc<Self>> {
        let store = Arc::new(ChatStore::open(db_path)?);
        let (ui_tx, _) = broadcast::channel(1024);

        let signing_key = SigningKey::from_bytes(signing_key_bytes);
        let verifying_key = signing_key.verifying_key();
        let decryption_key = StaticSecret::from(*decryption_key_bytes);

        Ok(Arc::new(Self {
            signing_key,
            verifying_key,
            decryption_key,
            store,
            ui_tx,
            dht_tx,
            network_tx,
            #[cfg(feature = "anonymity")]
            last_real_traffic: parking_lot::Mutex::new(std::time::Instant::now()),
        }))
    }

    /// [NEW] 公开 API: 获取历史记录
    pub fn get_history(&self, limit: usize, offset: usize) -> Result<Vec<ChatMessage>> {
        self.store.get_history(limit, offset)
    }

    pub fn subscribe(&self) -> broadcast::Receiver<ChatMessage> {
        self.ui_tx.subscribe()
    }

    /// 生成 E2EE 加密包
    /// v3 payload: [Ver][CMD][complete OnionCrypto packet].
    fn pack_message(&self, msg: &ChatMessage, receiver_enc_pub: [u8; 32]) -> Result<Vec<u8>> {
        let mut plain_bytes = bincode::serialize(msg)?;

        // [Feature] Countermeasures: 熵减 (Entropy Reduction)
        // 在 Onion 加密之前，先对 Plaintext 做熵减处理（例如 Base64 或加盐混淆），
        // 这样即使外层被破解，内部看起来也像是一段文本而不是二进制。
        // *注意*：虽然 Onion 会再次加密，但这一步是为了对抗深度的载荷分析。
        #[cfg(feature = "countermeasures")]
        {
            // 使用 EntropyReducer 降低特征 (mode=true 表示使用自定义字符集)
            // 注意：这里我们覆盖了 plain_bytes
            plain_bytes = EntropyReducer::reduce(&plain_bytes, true);
        }

        let ciphertext =
            OnionCrypto::seal(&receiver_enc_pub, &plain_bytes, &OnionConfig::default())
                .context("Encryption failed")?;

        let mut payload = Vec::with_capacity(1 + 1 + 32 + ciphertext.len());
        payload.push(CHAT_PROTO_VER);
        payload.push(CMD_MSG);
        payload.extend_from_slice(&ciphertext);
        Ok(payload)
    }

    /// 用户接口：发送消息
    pub fn send_message(
        &self,
        content: &str,
        target_id: NodeID,
        target_enc_pub: [u8; 32],
    ) -> Result<Vec<u8>> {
        let msg_id = rand::random::<u128>();
        let timestamp = Utc::now().timestamp();
        let content_bytes = content.as_bytes().to_vec();

        let mut msg = ChatMessage {
            msg_id,
            sender_pub_key: self.verifying_key.to_bytes(),
            receiver_id: target_id,
            timestamp,
            content_type: "text/plain".into(),
            content: content_bytes,
            signature: vec![],
        };
        msg.signature = self
            .signing_key
            .sign(&msg.signing_bytes())
            .to_bytes()
            .to_vec();
        msg.verify()?;

        // 存入发件箱
        let entry = OutboxEntry {
            msg: msg.clone(),
            target_node_id: target_id,
            target_enc_pub,
            attempts: 0,
            last_attempt: timestamp as u64, // Initial send
            status: MsgStatus::Pending,
        };
        self.store.save_outbox(&entry)?;

        // 更新活跃时间 (Anonymity)
        #[cfg(feature = "anonymity")]
        {
            *self.last_real_traffic.lock() = std::time::Instant::now();
        }

        // 打包
        self.pack_message(&msg, target_enc_pub)
    }

    /// 发送 ACK
    async fn send_ack(&self, target_addr: SocketAddr, msg_id: u128) {
        let mut payload = Vec::new();
        payload.push(CHAT_PROTO_VER);
        payload.push(CMD_ACK);
        payload.extend_from_slice(&msg_id.to_be_bytes());

        let _ = self.network_tx.send((target_addr, payload)).await;
    }

    /// 发送 SYNC 请求
    async fn send_sync(&self, target_addr: SocketAddr) {
        let my_id: NodeID = blake3::hash(self.verifying_key.as_bytes()).into();
        let mut payload = Vec::new();
        payload.push(CHAT_PROTO_VER);
        payload.push(CMD_SYNC);
        payload.extend_from_slice(&my_id);

        info!("ChatFlavor: Sending SYNC request to {}", target_addr);
        let _ = self.network_tx.send((target_addr, payload)).await;
    }

    /// 处理离线投递 (DHT)
    async fn trigger_dht_fallback(&self, entry: &mut OutboxEntry) -> Result<()> {
        info!(
            "ChatFlavor: Message {} timed out, falling back to DHT",
            entry.msg.msg_id
        );

        // 重新加密 (注意：DHT 存储的内容也是 E2EE 的)
        let payload = self.pack_message(&entry.msg, entry.target_enc_pub)?;

        let req = DhtStoreRequest {
            key: entry.target_node_id, // 对方 ID 作为 Key
            value: payload,
            ttl_seconds: MSG_TTL_SECS as u32,
        };

        self.dht_tx
            .send(req)
            .await
            .map_err(|_| anyhow!("DHT busy"))?;

        entry.status = MsgStatus::SentToDHT;
        self.store.update_outbox_entry(entry)?;
        Ok(())
    }

    /// [Feature] Extensions: 验证身份
    #[cfg(feature = "extensions")]
    fn verify_identity_extension(&self, msg: &ChatMessage) -> Result<()> {
        // 如果 Extensions 模块启用，我们可以通过 IdentityManager 进行更复杂的验证
        // 例如：检查该 PubKey 是否在本地的 Trust Anchor 中，或者是否符合特定的 Policy
        // 这里仅作演示：打印日志
        trace!("Extensions: Verifying identity for msg {}", msg.msg_id);
        Ok(())
    }
}

impl CapabilityProvider for ChatFlavor {
    fn capability_id(&self) -> String {
        "etp.flavor.chat.v3".into()
    }
}

impl Flavor for ChatFlavor {
    fn priority(&self) -> u8 {
        150
    }

    fn on_stream_data(&self, ctx: FlavorContext, data: &[u8]) -> bool {
        if data.len() < 2 || data.len() > 65536 || data[0] != CHAT_PROTO_VER {
            return false;
        }

        // 更新接收活跃状态
        #[cfg(feature = "anonymity")]
        {
            *self.last_real_traffic.lock() = std::time::Instant::now();
        }

        match data[1] {
            CMD_MSG => {
                // v3: [Ver][CMD][complete versioned OnionCrypto packet]
                if data.len() < 34 {
                    return true;
                } // Malformed

                let ciphertext = &data[2..];

                // 尝试解密
                let my_priv = self.decryption_key.to_bytes();

                // Onion Open
                let mut plaintext = match OnionCrypto::open(ciphertext, &my_priv) {
                    Ok(pt) => pt,
                    Err(e) => {
                        debug!("Chat: Decrypt fail: {}", e);
                        return false;
                    }
                };

                // [Feature] Countermeasures: 熵还原
                #[cfg(feature = "countermeasures")]
                {
                    match EntropyReducer::restore(&plaintext, true) {
                        Ok(original) => plaintext = original,
                        Err(e) => {
                            warn!("Chat: Entropy restoration failed: {}", e);
                            return true; // 数据损坏
                        }
                    }
                }

                if let Ok(msg) = crate::common::safe_deserialize::<ChatMessage>(&plaintext) {
                    // 验签
                    if msg.verify().is_ok()
                        && msg.receiver_id
                            == *blake3::hash(self.verifying_key.as_bytes()).as_bytes()
                    {
                        // [Feature] Extensions: 额外身份检查
                        #[cfg(feature = "extensions")]
                        {
                            if let Err(e) = self.verify_identity_extension(&msg) {
                                warn!("Chat: Identity extension check failed: {}", e);
                                // 根据策略，可能拒绝处理
                            }
                        }

                        info!(
                            "Chat: Received Msg from {:?}",
                            hex::encode(msg.sender_pub_key)
                        );

                        // 去重与存储
                        if !self.store.exists_in_inbox(msg.msg_id) {
                            let _ = self.store.save_inbox(&msg);
                            let _ = self.ui_tx.send(msg.clone());
                        }

                        // 立即发送 ACK
                        let sender_addr = ctx.src_addr;
                        let msg_id = msg.msg_id;
                        let net_tx = self.network_tx.clone();
                        tokio::spawn(async move {
                            // 构造 ACK 包
                            let mut ack = Vec::new();
                            ack.push(CHAT_PROTO_VER);
                            ack.push(CMD_ACK);
                            ack.extend_from_slice(&msg_id.to_be_bytes());
                            let _ = net_tx.send((sender_addr, ack)).await;
                        });
                    }
                }
                true
            }
            CMD_ACK => {
                // 格式: [Ver][CMD][MsgID(16)]
                if data.len() < 18 {
                    return true;
                }
                let mut id_bytes = [0u8; 16];
                id_bytes.copy_from_slice(&data[2..18]);
                let msg_id = u128::from_be_bytes(id_bytes);

                info!("Chat: Received ACK for MsgID {}", msg_id);
                let _ = self.store.mark_delivered(msg_id);
                true
            }
            CMD_SYNC => {
                // 格式: [Ver][CMD][RequesterNodeID(32)]
                if data.len() < 34 {
                    return true;
                }
                let mut node_id = [0u8; 32];
                node_id.copy_from_slice(&data[2..34]);

                info!("Chat: Received SYNC request from {:?}", node_id);

                // 查找待发送给该 ID 的消息
                let pending = self.store.get_messages_for_target(&node_id);
                if !pending.is_empty() {
                    info!(
                        "Chat: Syncing {} messages to {}",
                        pending.len(),
                        ctx.src_addr
                    );
                    // 逻辑省略：重新加密并发送 (需要对方 EncKey，通常 OutboxEntry 里有)
                }
                true
            }
            CMD_COVER_NOISE => {
                // [Feature] Anonymity: 收到掩护流量
                // 静默丢弃，不做任何处理。
                // 仅仅它的到达本身就已经起到了混淆流量模式的作用。
                trace!("Chat: Received cover traffic noise.");
                true
            }
            _ => false,
        }
    }

    fn on_connection_open(&self, peer: SocketAddr) {
        // 主动发送 SYNC 请求
        let net_tx = self.network_tx.clone();
        let my_id = blake3::hash(self.verifying_key.as_bytes())
            .as_bytes()
            .clone();

        tokio::spawn(async move {
            let mut payload = Vec::new();
            payload.push(CHAT_PROTO_VER);
            payload.push(CMD_SYNC);
            payload.extend_from_slice(&my_id);
            let _ = net_tx.send((peer, payload)).await;
        });
    }

    fn on_connection_close(&self, _peer: SocketAddr) {}

    /// 后台轮询 (由 Node Tick 驱动)
    fn poll(&self) {
        let now = SystemTime::now()
            .duration_since(SystemTime::UNIX_EPOCH)
            .unwrap()
            .as_secs();

        // 1. [Feature] Anonymity: 生成掩护流量 (Cover Traffic)
        #[cfg(feature = "anonymity")]
        {
            let last_active = *self.last_real_traffic.lock();
            // 如果过去 5 秒没有真实流量，且随机概率触发
            if last_active.elapsed() > Duration::from_secs(5) {
                let mut rng = rand::thread_rng();
                if rng.gen_bool(0.1) {
                    // 10% 概率触发
                    trace!("Chat: Generating cover noise...");
                    let noise_len = rng.gen_range(100..1024);
                    let mut noise = vec![0u8; noise_len];
                    rng.fill(&mut noise[..]);

                    let mut payload = Vec::with_capacity(2 + noise_len);
                    payload.push(CHAT_PROTO_VER);
                    payload.push(CMD_COVER_NOISE);
                    payload.extend(noise);

                    // 发送给随机 Peer?
                    // Flavor 无法直接遍历所有 Peers。
                    // 这是一个架构限制。通常 Cover Traffic 由 Engine 处理。
                    // 但 Flavor 可以向已知的特定地址（如 Gateway）发送应用层噪声。
                    // 这里仅作逻辑展示。
                }
            }
        }

        // 2. 消息重试逻辑
        let pending = self.store.get_pending_messages();
        for mut entry in pending {
            // 如果已经在 DHT 状态，跳过
            if entry.status != MsgStatus::Pending {
                continue;
            }

            // 检查间隔
            if now.saturating_sub(entry.last_attempt) > RETRY_INTERVAL_SECS {
                entry.attempts += 1;
                entry.last_attempt = now;
                info!(
                    "Chat: Retrying message {}, attempt {}",
                    entry.msg.msg_id, entry.attempts
                );

                if entry.attempts > MAX_DIRECT_RETRIES {
                    // 降级到 DHT
                    let dht_tx = self.dht_tx.clone();
                    let store = self.store.clone();

                    // 重新打包 (需要处理可能的 feature 加密逻辑)
                    let payload_res = self.pack_message(&entry.msg, entry.target_enc_pub);

                    if let Ok(payload) = payload_res {
                        let req = DhtStoreRequest {
                            key: entry.target_node_id,
                            value: payload,
                            ttl_seconds: MSG_TTL_SECS as u32,
                        };

                        let dht_ch = self.dht_tx.clone();
                        tokio::spawn(async move {
                            let _ = dht_ch.send(req).await;
                        });

                        // Update status sync
                        entry.status = MsgStatus::SentToDHT;
                        let _ = self.store.update_outbox_entry(&entry);
                    } else {
                        error!("Chat: Failed to pack message for DHT fallback");
                    }
                }
            }
        }
    }
}
impl std::fmt::Debug for ChatFlavor {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ChatFlavor").finish_non_exhaustive()
    }
}

#[cfg(test)]
mod protocol_regression_tests {
    use super::*;
    fn signed() -> ChatMessage {
        let key = SigningKey::from_bytes(&[42; 32]);
        let mut message = ChatMessage {
            msg_id: 1,
            sender_pub_key: key.verifying_key().to_bytes(),
            receiver_id: [7; 32],
            timestamp: Utc::now().timestamp(),
            content_type: "text/plain".into(),
            content: b"real chat signature".to_vec(),
            signature: vec![],
        };
        message.signature = key.sign(&message.signing_bytes()).to_bytes().to_vec();
        message
    }
    #[test]
    fn chat_v3_signature_binds_routing_and_rejects_legacy_proof() {
        let message = signed();
        assert!(message.verify().is_ok());
        for field in 0..3 {
            let mut changed = message.clone();
            match field {
                0 => changed.receiver_id[0] ^= 1,
                1 => changed.content_type.push('x'),
                _ => changed.content.push(0),
            }
            assert!(changed.verify().is_err());
        }
        let mut old = message;
        let mut legacy = old.msg_id.to_be_bytes().to_vec();
        legacy.extend(old.timestamp.to_be_bytes());
        legacy.extend(&old.content);
        old.signature = SigningKey::from_bytes(&[42; 32])
            .sign(&legacy)
            .to_bytes()
            .to_vec();
        assert!(old.verify().is_err());
    }
    #[test]
    fn old_chat_records_move_to_lossless_quarantine_on_open() {
        let path = std::env::temp_dir().join(format!(
            "etp-chat-migration-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let mut old = signed();
        old.signature = vec![1];
        let bytes = bincode::serialize(&old).unwrap();
        {
            let db = sled::open(&path).unwrap();
            db.open_tree("inbox")
                .unwrap()
                .insert(b"legacy-key", bytes.clone())
                .unwrap();
            db.flush().unwrap();
        }
        {
            let store = ChatStore::open(path.to_str().unwrap()).unwrap();
            assert!(store.get_history(10, 0).unwrap().is_empty());
            let tree = store.db.open_tree("quarantined_chat_v2").unwrap();
            assert_eq!(tree.len(), 1);
            let (_, record) = tree.iter().next().unwrap().unwrap();
            let (source, key, value): (String, Vec<u8>, Vec<u8>) =
                bincode::deserialize(&record).unwrap();
            assert_eq!(source, "inbox");
            assert_eq!(key, b"legacy-key");
            assert_eq!(value, bytes);
        }
        std::fs::remove_dir_all(path).unwrap();
    }
}
