// etp-core/src/network/node.rs

use std::collections::{HashMap, VecDeque};
use std::future::Future;
use std::net::SocketAddr;
use std::pin::Pin;
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::net::UdpSocket;
use tokio::sync::{mpsc, oneshot};

use anyhow::{anyhow, Context, Result};
use blake3;
use chacha20poly1305::{aead::Aead, AeadInPlace, ChaCha20Poly1305, KeyInit};
use dashmap::DashMap;
use log::{debug, error, info, trace, warn};
use parking_lot::RwLock; // 注意：这是同步锁，需要小心跨 await 使用
use rand::Rng;
use serde::{Deserialize, Serialize};

use crate::error::EtpError;
use bincode::Options;

// --- ETP Core Module Imports ---

use crate::crypto::noise::{KeyPair, NoiseSession};
use crate::wire::frame::{Frame, InjectionCommand, NatSignalType};
use crate::wire::packet::{
    acquire_buffer, release_buffer, DecryptedPacket, RawPacket, StatefulPacket, StatelessPacket,
    TokenManager,
};

// Plugin System Interfaces
use crate::plugin::{
    Agent, AgentContext, CapabilityProvider, Dialect, Flavor, FlavorContext, Interceptor,
    InterceptorContext, PluginRegistry, SystemContext,
};

// Control Plane Constants & Categories
use crate::plugin::flavors::control::{ControlCategory, VIRTUAL_STREAM_SIDE_CHANNEL};

// Transport Layer Components
use crate::transport::congestion::CongestionControlAlgo;
use crate::transport::injection::AclManager;
use crate::transport::reliability::{MultiplexingMode, ReliabilityLayer};
use crate::transport::shaper::{SecurityProfile, TrafficShaper};
use crate::transport::side_channel::{ChannelMode, SideChannelManager, SideChannelPolicy};

// Network Logic
use crate::common::NodeInfo;
use crate::network::discovery::RoutingTable;
use crate::network::nat::NatManager;
use crate::NodeID;

// ============================================================================
//  1. Constants & Configurations
// ============================================================================

const DEFAULT_TICK_MS: u64 = 20;
const DEFAULT_KEEPALIVE: Duration = Duration::from_secs(25);
const DEFAULT_SESSION_TIMEOUT: Duration = Duration::from_secs(120);
const DEFAULT_MTU: usize = 1350;
const DEFAULT_RECV_BUF: usize = 8 * 1024 * 1024;
const DEFAULT_SEND_BUF: usize = 8 * 1024 * 1024;

// Side Channel Payload Limit (1MB as requested)
const MAX_SIDE_CHANNEL_PAYLOAD: usize = 1024 * 1024;

// Rekey Constraints
const SOFT_REKEY_LIMIT: u64 = 256 * 1024 * 1024; // 256MB triggers background rekey
const HARD_REKEY_LIMIT: u64 = 512 * 1024 * 1024; // 512MB triggers blocking rekey

// --- Deep Configurations (New Features) ---

/// 深度匿名化配置：针对高级流量分析 (Traffic Analysis) 的防御
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeepAnonymityConfig {
    /// 启用掩护流量 (Cover Traffic)
    /// 即便没有业务数据，也会发送加密的垃圾数据以维持流量特征
    pub enable_cover_traffic: bool,

    /// 目标最小比特率 (bps)
    /// 如果实际流量低于此值，引擎将填充垃圾数据
    pub target_min_bitrate: u64,

    /// 传输层抖动范围 (毫秒)
    /// 强制增加随机延迟以破坏时序指纹
    pub jitter_ms_range: (u64, u64),
}

impl Default for DeepAnonymityConfig {
    fn default() -> Self {
        Self {
            enable_cover_traffic: false,
            target_min_bitrate: 0,
            jitter_ms_range: (0, 0),
        }
    }
}

/// 深度安全配置：针对主动探测和密钥破解的防御
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeepSecurityConfig {
    /// 强制密钥轮换间隔 (秒)
    /// 无论流量多少，每隔 N 秒强制重新协商 Noise 会话
    pub strict_rekey_interval_secs: u64,

    /// 零容忍模式
    /// 如果收到格式错误的握手包，是否将源 IP 加入内存黑名单 (Ban Duration)
    pub handshake_zero_tolerance: bool,

    /// 是否允许未知的 SideChannel ID
    /// true: 允许自动创建信道 (Lazy)
    /// false: 必须是预定义的信道 (Strict)
    pub allow_dynamic_side_channels: bool,
}

impl Default for DeepSecurityConfig {
    fn default() -> Self {
        Self {
            strict_rekey_interval_secs: 3600, // 1 hour
            handshake_zero_tolerance: false,
            allow_dynamic_side_channels: true,
        }
    }
}

#[derive(Clone)]
pub struct NodeConfig {
    pub bind_addr: String,
    pub keypair: KeyPair,
    pub profile: SecurityProfile,
    pub bootstrap_peers: Vec<SocketAddr>,
    pub trusted_peers: std::collections::HashMap<SocketAddr, [u8; 32]>,
    pub enable_onion_relay: bool,
    pub default_dialect: String,
    pub default_flavor: String,
    pub stateless_secret: [u8; 32],

    // Multiplexing
    pub multiplexing_mode: MultiplexingMode,

    // Strategy Configuration (IDs)
    pub congestion_algo: String,
    pub padding_strategy: String,

    // Resources
    pub recv_buffer_size: usize,
    pub send_buffer_size: usize,
    pub mtu: usize,
    pub session_timeout: Duration,
    pub max_sessions: usize,

    // --- New Deep Configs ---
    pub anonymity: DeepAnonymityConfig,
    pub security: DeepSecurityConfig,
}

impl Default for NodeConfig {
    fn default() -> Self {
        Self {
            bind_addr: "0.0.0.0:0".to_string(),
            keypair: KeyPair::generate(),
            profile: SecurityProfile::Balanced,
            bootstrap_peers: vec![],
            trusted_peers: std::collections::HashMap::new(),
            enable_onion_relay: false,
            default_dialect: "etp.dialect.noise.std".to_string(),
            default_flavor: "etp.flavor.core".to_string(),
            stateless_secret: [0u8; 32],
            multiplexing_mode: MultiplexingMode::StrictSingle,

            congestion_algo: "etp.mod.congestion.newreno".to_string(),
            padding_strategy: "etp.mod.padding.none".to_string(),

            recv_buffer_size: DEFAULT_RECV_BUF,
            send_buffer_size: DEFAULT_SEND_BUF,
            mtu: DEFAULT_MTU,
            session_timeout: DEFAULT_SESSION_TIMEOUT,
            max_sessions: 10000,

            anonymity: DeepAnonymityConfig::default(),
            security: DeepSecurityConfig::default(),
        }
    }
}

#[derive(Debug, Default)]
pub struct NodeMetrics {
    pub bytes_ingress: AtomicU64,
    pub bytes_egress: AtomicU64,
    pub control_bytes_ingress: AtomicU64,
    pub control_bytes_egress: AtomicU64,
    pub cover_traffic_bytes: AtomicU64, // New: wasted/cover bytes
    pub active_sessions: AtomicUsize,
    pub handshake_success: AtomicU64,
    pub handshake_failed: AtomicU64,
    pub packet_drop_acl: AtomicU64,
    pub packet_drop_format: AtomicU64,
}

// ============================================================================
//  2. Transport Abstraction
// ============================================================================

#[async_trait::async_trait]
pub trait PacketTransport: Send + Sync + std::fmt::Debug {
    async fn send_to(&self, buf: &[u8], target: SocketAddr) -> std::io::Result<usize>;
    async fn recv_from(&self, buf: &mut [u8]) -> std::io::Result<(usize, SocketAddr)>;
    fn local_addr(&self) -> std::io::Result<SocketAddr>;
}

#[derive(Debug)]
pub struct UdpTransport(pub Arc<UdpSocket>);
#[async_trait::async_trait]
impl PacketTransport for UdpTransport {
    async fn send_to(&self, buf: &[u8], target: SocketAddr) -> std::io::Result<usize> {
        self.0.send_to(buf, target).await
    }
    async fn recv_from(&self, buf: &mut [u8]) -> std::io::Result<(usize, SocketAddr)> {
        self.0.recv_from(buf).await
    }
    fn local_addr(&self) -> std::io::Result<SocketAddr> {
        self.0.local_addr()
    }
}

pub trait PacketHandler: Send + Sync {
    fn handle<'a>(
        &'a self,
        data: &'a [u8],
        src: SocketAddr,
        transport: &'a Arc<dyn PacketTransport>,
    ) -> Pin<Box<dyn Future<Output = bool> + Send + 'a>>;
}

pub struct NoOpHandler;
impl PacketHandler for NoOpHandler {
    fn handle<'a>(
        &'a self,
        _data: &'a [u8],
        _src: SocketAddr,
        _transport: &'a Arc<dyn PacketTransport>,
    ) -> Pin<Box<dyn Future<Output = bool> + Send + 'a>> {
        Box::pin(async move { false })
    }
}

// ============================================================================
//  3. Session Management (The Core State)
// ============================================================================

/// 掩护流量生成器 (State Machine)
struct CoverTrafficEngine {
    enabled: bool,
    target_bps: u64,
    bytes_sent_in_window: u64,
    last_check: Instant,
}

impl CoverTrafficEngine {
    fn new(config: &DeepAnonymityConfig) -> Self {
        Self {
            enabled: config.enable_cover_traffic,
            target_bps: config.target_min_bitrate,
            bytes_sent_in_window: 0,
            last_check: Instant::now(),
        }
    }

    fn record_sent(&mut self, bytes: usize) {
        if self.enabled {
            self.bytes_sent_in_window += bytes as u64;
        }
    }

    /// 计算需要发送的掩护流量大小
    fn calculate_padding_needed(&mut self) -> usize {
        if !self.enabled || self.target_bps == 0 {
            return 0;
        }

        let now = Instant::now();
        let elapsed = now.duration_since(self.last_check).as_secs_f64();
        if elapsed < 0.1 {
            return 0;
        } // Check every 100ms roughly

        let expected_bytes = (self.target_bps as f64 * elapsed) as u64;
        let needed = if expected_bytes > self.bytes_sent_in_window {
            (expected_bytes - self.bytes_sent_in_window) as usize
        } else {
            0
        };

        // Reset window
        self.bytes_sent_in_window = 0;
        self.last_check = now;

        // Cap burst to MTU * 4 to avoid congestion self-DoS
        needed.min(1350 * 4)
    }
}

struct SessionContext {
    crypto: NoiseSession,
    reliability: ReliabilityLayer,
    shaper: TrafficShaper,
    side_channels: SideChannelManager,
    cover_engine: CoverTrafficEngine, // New Feature

    handshake_completed: bool,
    last_activity: Instant,
    created_at: Instant,

    // Security Counters
    bytes_sent_total: u64,
    bytes_sent_since_rekey: u64,
    last_rekey_time: Instant,

    dialect: Arc<dyn Dialect>,
    flavor: Arc<dyn Flavor>,
    pending_queue: VecDeque<Frame>,
    stream_offsets: HashMap<u32, u64>,
    handshake_flight: Vec<u8>,
    handshake_sent: Instant,
    handshake_attempts: u8,

    interceptors: Vec<Arc<dyn Interceptor>>,
    config_snapshot: NodeConfig, // Snapshot for runtime logic
}

impl SessionContext {
    fn new(
        crypto: NoiseSession,
        config: &NodeConfig,
        dialect: Arc<dyn Dialect>,
        flavor: Arc<dyn Flavor>,
        interceptors: Vec<Arc<dyn Interceptor>>,
        registry: &Arc<PluginRegistry>,
    ) -> Self {
        let mut reliability = ReliabilityLayer::new(config.multiplexing_mode);

        if let Some(algo) = registry.create_congestion_algo(&config.congestion_algo) {
            reliability.set_congestion_algo(algo);
        } else {
            debug!(
                "Using default congestion algo, ID '{}' not found",
                config.congestion_algo
            );
        }

        if let Some(strategy) = registry.create_padding_strategy(&config.padding_strategy) {
            reliability.set_padding_strategy(strategy);
        } else {
            debug!(
                "Using default padding strategy, ID '{}' not found",
                config.padding_strategy
            );
        }

        Self {
            crypto,
            reliability,
            shaper: TrafficShaper::new(config.profile),
            side_channels: SideChannelManager::new(),
            cover_engine: CoverTrafficEngine::new(&config.anonymity),

            handshake_completed: false,
            last_activity: Instant::now(),
            created_at: Instant::now(),

            bytes_sent_total: 0,
            bytes_sent_since_rekey: 0,
            last_rekey_time: Instant::now(),

            dialect,
            flavor,
            pending_queue: VecDeque::new(),
            stream_offsets: HashMap::new(),
            handshake_flight: Vec::new(),
            handshake_sent: Instant::now(),
            handshake_attempts: 0,
            interceptors,
            config_snapshot: config.clone(),
        }
    }

    fn run_ingress_interceptors(&self, stream_id: u32, mut data: Vec<u8>) -> Option<Vec<u8>> {
        let ctx = InterceptorContext {
            stream_id,
            is_handshake: self.handshake_completed,
        };
        for interceptor in &self.interceptors {
            match interceptor.on_ingress(&ctx, data) {
                Ok(Some(d)) => data = d,
                Ok(None) => return None,
                Err(e) => {
                    error!(
                        "Interceptor {} ingress error: {}",
                        interceptor.capability_id(),
                        e
                    );
                    return None;
                }
            }
        }
        Some(data)
    }

    fn run_egress_interceptors(&self, stream_id: u32, mut data: Vec<u8>) -> Option<Vec<u8>> {
        let ctx = InterceptorContext {
            stream_id,
            is_handshake: self.handshake_completed,
        };
        for interceptor in &self.interceptors {
            match interceptor.on_egress(&ctx, data) {
                Ok(Some(d)) => data = d,
                Ok(None) => return None,
                Err(e) => {
                    error!(
                        "Interceptor {} egress error: {}",
                        interceptor.capability_id(),
                        e
                    );
                    return None;
                }
            }
        }
        Some(data)
    }

    /// Check if strict rekey is required (Deep Security)
    fn needs_strict_rekey(&self) -> bool {
        let bytes_limit = HARD_REKEY_LIMIT;
        let time_limit =
            Duration::from_secs(self.config_snapshot.security.strict_rekey_interval_secs);

        self.bytes_sent_since_rekey >= bytes_limit
            || (!time_limit.is_zero() && self.last_rekey_time.elapsed() >= time_limit)
    }
}

// ============================================================================
//  4. Command Interface
// ============================================================================

pub enum Command {
    // Data Plane
    SendData {
        target: SocketAddr,
        data: Vec<u8>,
    },
    SendStream {
        target: SocketAddr,
        stream_id: u32,
        data: Vec<u8>,
    },

    // Control Plane (Side Channel)
    SendControl {
        target: SocketAddr,
        category: ControlCategory,
        data: Vec<u8>,
    },

    // Management
    Connect {
        target: SocketAddr,
        remote_pub: Vec<u8>,
    },
    SendOnion {
        path: Vec<(SocketAddr, Vec<u8>)>,
        data: Vec<u8>,
        reply: oneshot::Sender<Result<(), String>>,
    },
    DhtFindNode {
        target_id: NodeID,
        reply: oneshot::Sender<Result<Vec<NodeInfo>>>,
    },
    DhtStore {
        key: NodeID,
        value: Vec<u8>,
        ttl: u32,
    },
    GetStats {
        reply: oneshot::Sender<String>,
    },
    Shutdown,
}

#[derive(Clone)]
pub struct EtpHandle {
    data_tx: mpsc::Sender<(SocketAddr, Vec<u8>)>,
    cmd_tx: mpsc::Sender<Command>,
}

impl EtpHandle {
    /// 发送应用层数据（默认流）
    pub async fn send_data(&self, target: SocketAddr, data: Vec<u8>) -> Result<(), EtpError> {
        self.data_tx
            .send((target, data))
            .await
            .map_err(|_| EtpError::Internal("Engine channel closed (Node stopped)".into()))
    }

    /// 发送指定流数据（多路复用）
    pub async fn send_stream(
        &self,
        target: SocketAddr,
        id: u32,
        data: Vec<u8>,
    ) -> Result<(), EtpError> {
        self.cmd_tx
            .send(Command::SendStream {
                target,
                stream_id: id,
                data,
            })
            .await
            .map_err(|_| EtpError::Internal("Engine channel closed".into()))
    }

    /// 发送控制指令 (SideChannel)
    /// 包含载荷大小预检查
    pub async fn send_control_cmd(
        &self,
        target: SocketAddr,
        category: ControlCategory,
        data: Vec<u8>,
    ) -> Result<(), EtpError> {
        if data.len() > MAX_SIDE_CHANNEL_PAYLOAD {
            return Err(EtpError::PayloadTooLarge(
                data.len(),
                MAX_SIDE_CHANNEL_PAYLOAD,
            ));
        }
        self.cmd_tx
            .send(Command::SendControl {
                target,
                category,
                data,
            })
            .await
            .map_err(|_| EtpError::Internal("Engine channel closed".into()))
    }

    /// 主动发起连接
    pub async fn connect(&self, target: SocketAddr, remote_pub: Vec<u8>) -> Result<(), EtpError> {
        self.cmd_tx
            .send(Command::Connect { target, remote_pub })
            .await
            .map_err(|_| EtpError::Internal("Engine channel closed".into()))
    }

    /// 发送洋葱路由包
    pub async fn send_onion(
        &self,
        path: Vec<(SocketAddr, Vec<u8>)>,
        data: Vec<u8>,
    ) -> Result<(), EtpError> {
        let (reply, result) = oneshot::channel();
        self.cmd_tx
            .send(Command::SendOnion { path, data, reply })
            .await
            .map_err(|_| EtpError::Internal("Engine channel closed".into()))?;
        tokio::time::timeout(Duration::from_secs(5), result)
            .await
            .map_err(|_| EtpError::Internal("onion send deadline".into()))?
            .map_err(|_| EtpError::Internal("onion send cancelled".into()))?
            .map_err(EtpError::Internal)
    }

    /// 执行 DHT 节点查找
    /// 返回明确的 Timeout 错误
    pub async fn dht_find_node(&self, target_id: NodeID) -> Result<Vec<NodeInfo>, EtpError> {
        let (tx, rx) = oneshot::channel();

        // 1. 发送请求给 Engine
        self.cmd_tx
            .send(Command::DhtFindNode {
                target_id,
                reply: tx,
            })
            .await
            .map_err(|_| EtpError::Internal("Engine stopped before sending command".into()))?;

        // 2. 等待回包 (处理超时)
        // 注意：这里的 rx.await 错误通常意味着 sender 被 drop 了（即 Engine 处理过程中崩溃或忽略了请求）
        let internal_result = rx.await.map_err(|_| EtpError::Timeout)?;

        // 3. 处理业务逻辑错误 (anyhow -> EtpError::Internal)
        internal_result.map_err(|e| EtpError::Internal(format!("DHT Lookup failed: {}", e)))
    }

    /// DHT 存储数据
    pub async fn dht_store(&self, key: NodeID, value: Vec<u8>, ttl: u32) -> Result<(), EtpError> {
        self.cmd_tx
            .send(Command::DhtStore { key, value, ttl })
            .await
            .map_err(|_| EtpError::Internal("Engine channel closed".into()))
    }

    /// 获取节点统计信息
    pub async fn get_stats(&self) -> Result<String, EtpError> {
        let (tx, rx) = oneshot::channel();
        self.cmd_tx
            .send(Command::GetStats { reply: tx })
            .await
            .map_err(|_| EtpError::Internal("Engine stopped".into()))?;

        rx.await.map_err(|_| EtpError::Timeout)
    }

    /// 优雅停机
    pub async fn shutdown(&self) -> Result<(), EtpError> {
        self.cmd_tx
            .send(Command::Shutdown)
            .await
            .map_err(|_| EtpError::Internal("Engine already stopped".into()))
    }
}

// ============================================================================
//  5. Engine Implementation
// ============================================================================

#[derive(Clone)]
struct ProcessingContext {
    transport: Arc<dyn PacketTransport>,
    config: Arc<NodeConfig>,
    routing_table: Arc<RoutingTable>,
    onion: Arc<super::onion::OnionRouter>,
    sessions: Arc<DashMap<SocketAddr, Arc<tokio::sync::Mutex<SessionContext>>>>,
    nat_manager: Arc<RwLock<NatManager>>,
    acl: Arc<AclManager>,
    plugins: Arc<PluginRegistry>,
    data_tx: mpsc::Sender<(SocketAddr, Vec<u8>)>,
    dht_pending_queries: Arc<
        DashMap<
            u64,
            (
                Vec<SocketAddr>,
                Instant,
                oneshot::Sender<Result<Vec<NodeInfo>>>,
            ),
        >,
    >,
    token_manager: Arc<TokenManager>,
    dht_store: Arc<DashMap<NodeID, (Vec<u8>, std::time::SystemTime)>>,
    metrics: Arc<NodeMetrics>,
    incoming_slots: Arc<tokio::sync::Semaphore>,
    handshakes: Arc<parking_lot::Mutex<HashMap<(SocketAddr, [u8; 32]), (Instant, Vec<u8>)>>>,

    default_handler: Option<Arc<dyn PacketHandler>>,
    fallback_handler: Option<Arc<dyn PacketHandler>>,

    // Security: Banned IPs from Zero Tolerance
    banned_ips: Arc<DashMap<SocketAddr, Instant>>,
}

impl SystemContext for ProcessingContext {
    fn lookup_peer(&self, node_id: &NodeID) -> Option<SocketAddr> {
        self.routing_table.lookup(node_id)
    }
    fn is_connected(&self, addr: SocketAddr) -> bool {
        self.sessions.contains_key(&addr)
    }
    fn my_node_id(&self) -> NodeID {
        blake3::hash(&self.config.keypair.public).into()
    }
}

pub struct EtpEngine {
    ctx: ProcessingContext,
    data_rx: mpsc::Receiver<(SocketAddr, Vec<u8>)>,
    cmd_rx: mpsc::Receiver<Command>,
}

impl EtpEngine {
    const DHT_OP_FIND_NODE: u8 = 0x01;
    const DHT_OP_STORE: u8 = 0x02;
    const DHT_OP_PING: u8 = 0x03;

    const DHT_OP_FIND_NODE_RESP: u8 = 0x81;
    const DHT_OP_PONG: u8 = 0x83;

    pub async fn new(
        mut config: NodeConfig,
        plugins: Arc<PluginRegistry>,
    ) -> Result<(Self, EtpHandle, mpsc::Receiver<(SocketAddr, Vec<u8>)>)> {
        // Defaults
        if config.recv_buffer_size == 0 {
            config.recv_buffer_size = DEFAULT_RECV_BUF;
        }
        if config.send_buffer_size == 0 {
            config.send_buffer_size = DEFAULT_SEND_BUF;
        }
        if config.mtu == 0 {
            config.mtu = DEFAULT_MTU;
        }

        // 初始化 UDP Transport
        let socket = UdpSocket::bind(&config.bind_addr)
            .await
            .context(format!("Failed to bind UDP socket on {}", config.bind_addr))?;

        // 尝试设置缓冲区，忽略错误（某些 OS 可能不支持）
        // Tokio owns the socket; platform receive/send queues retain OS defaults.
        let transport = Arc::new(UdpTransport(Arc::new(socket)));

        info!(
            "ETP Kernel booted on {}. Mode: {:?}. Anonymity: {}",
            config.bind_addr, config.multiplexing_mode, config.anonymity.enable_cover_traffic
        );

        // 调用通用构造逻辑
        Self::new_with_transport(config, plugins, transport).await
    }

    /// 高级构造器：支持自定义传输层 (Tor/I2P/TCP/Memory)
    /// 这是实现深度匿名模块的关键入口
    pub async fn new_with_transport(
        mut config: NodeConfig,
        plugins: Arc<PluginRegistry>,
        transport: Arc<dyn PacketTransport>, // <--- 关键：依赖注入
    ) -> Result<(Self, EtpHandle, mpsc::Receiver<(SocketAddr, Vec<u8>)>)> {
        anyhow::ensure!(
            config.keypair.private.len() == 32
                && config.keypair.public.len() == 32
                && config.trusted_peers.len() <= 128,
            "bounded valid node identity required"
        );
        anyhow::ensure!(
            config.anonymity.jitter_ms_range.0 <= config.anonymity.jitter_ms_range.1
                && config.anonymity.jitter_ms_range.1 <= 10000,
            "jitter range"
        );
        if config.stateless_secret == [0; 32] {
            rand::RngCore::fill_bytes(&mut rand::rngs::OsRng, &mut config.stateless_secret);
        }
        if plugins.get_dialect(&config.default_dialect).is_none()
            && config.default_dialect == "etp.dialect.noise.std"
        {
            plugins.register_dialect(Arc::new(crate::plugin::StandardDialect));
        }
        if plugins.get_flavor(&config.default_flavor).is_none()
            && config.default_flavor == "etp.flavor.core"
        {
            plugins.register_flavor(Arc::new(crate::plugin::StandardFlavor));
        }
        anyhow::ensure!(
            plugins.get_dialect(&config.default_dialect).is_some()
                && plugins.get_flavor(&config.default_flavor).is_some(),
            "configured plugins unavailable"
        );
        // 1. 初始化核心组件
        let my_id = blake3::hash(&config.keypair.public).into();

        info!("ETP Kernel Booting... ID: {}", hex::encode(my_id));
        info!(
            "Profile: {:?} | Anonymity: CoverTraffic={}, Jitter={:?}",
            config.profile, config.anonymity.enable_cover_traffic, config.anonymity.jitter_ms_range
        );

        // 2. 启动智能体 (Autonomous Agents)
        let agents = plugins.get_agents();
        for agent in agents {
            info!("Booting Agent: {:?}", agent.capability_id());
            let context = AgentContext { node_id: my_id };
            let agent_clone = agent.clone();
            tokio::spawn(async move {
                agent_clone.run(context).await;
            });
        }

        // 3. 构建共享状态
        let token_manager = Arc::new(TokenManager::new(config.stateless_secret));
        let routing_table = Arc::new(RoutingTable::new());
        for (address, key) in &config.trusted_peers {
            routing_table.add_node(NodeInfo::new(*blake3::hash(key).as_bytes(), *address));
        }
        let acl = Arc::new(AclManager::new(true));
        for key in config.trusted_peers.values() {
            acl.trust_node(*key, 0);
        } // 默认开启严格 ACL 模式
        let nat_mgr = Arc::new(RwLock::new(NatManager::new()));
        let sessions = Arc::new(DashMap::new());
        let dht_store = Arc::new(DashMap::new());
        let dht_pending = Arc::new(DashMap::new());
        let metrics = Arc::new(NodeMetrics::default());
        let banned_ips = Arc::new(DashMap::new());

        // 4. 构建通信通道
        let (app_tx, data_rx) = mpsc::channel(4096); // Outbound Data (App -> Net)
        let (data_tx, app_rx) = mpsc::channel(4096); // Inbound Data (Net -> App)
        let (cmd_tx, cmd_rx) = mpsc::channel(256); // Commands

        // 5. 组装上下文
        let config = Arc::new(config);
        let onion = Arc::new(super::onion::OnionRouter::new(
            config.clone(),
            transport.clone(),
            data_tx.clone(),
        ));
        let ctx = ProcessingContext {
            onion,
            transport, // 使用传入的 Transport
            config,
            routing_table,
            sessions,
            nat_manager: nat_mgr,
            acl,
            plugins,
            data_tx: data_tx, // 注意：这是给 Session 用的，将解密数据发给 App
            dht_pending_queries: dht_pending,
            token_manager,
            dht_store,
            metrics,
            incoming_slots: Arc::new(tokio::sync::Semaphore::new(128)),
            handshakes: Arc::new(parking_lot::Mutex::new(HashMap::new())),
            default_handler: None,
            fallback_handler: None,
            banned_ips,
        };

        let handle = EtpHandle {
            data_tx: app_tx,
            cmd_tx,
        };
        let engine = Self {
            ctx,
            data_rx,
            cmd_rx,
        };

        Ok((engine, handle, app_rx))
    }

    pub fn set_default_handler(&mut self, handler: Arc<dyn PacketHandler>) {
        self.ctx.default_handler = Some(handler);
    }

    pub fn set_fallback_handler(&mut self, handler: Arc<dyn PacketHandler>) {
        self.ctx.fallback_handler = Some(handler);
    }

    // 找到 impl EtpEngine 块，替换或修改以下方法

    pub async fn run(mut self) -> Result<()> {
        let mut tick_interval = tokio::time::interval(Duration::from_millis(DEFAULT_TICK_MS));
        let mut dht_refresh_interval = tokio::time::interval(Duration::from_secs(600)); // 修正之前的常量未定义问题
        let mut recv_buf = vec![0u8; 65535];

        info!("ETP Engine loop started.");

        loop {
            tokio::select! {
                // 1. 网络包接收
                recv_result = self.ctx.transport.recv_from(&mut recv_buf) => {
                    match recv_result {
                        Ok((len, src)) => {
                            // Deep Security: Ban List Check
                            if let Some(expiry) = self.ctx.banned_ips.get(&src) {
                                if Instant::now() < *expiry { continue; }
                                else { self.ctx.banned_ips.remove(&src); }
                            }

                            self.ctx.metrics.bytes_ingress.fetch_add(len as u64, Ordering::Relaxed);
                            let data = recv_buf[..len].to_vec();
                            self.spawn_incoming_handler(data, src);
                        }
                        Err(e) => error!("Transport IO Error: {}", e),
                    }
                }

                // 2. 应用层数据发送
                app_msg = self.data_rx.recv() => {
                    match app_msg {
                        Some((target, data)) => self.handle_app_data(target, 1, data).await,
                        None => {
                            info!("Data channel closed, shutting down engine...");
                            break;
                        },
                    }
                }

                // 3. 控制指令
                cmd = self.cmd_rx.recv() => {
                    match cmd {
                        Some(cmd) => {
                            if matches!(cmd, Command::Shutdown) {
                                info!("Received Shutdown command.");
                                self.handle_shutdown().await;
                                break; // 退出主循环
                            }
                            self.handle_command(cmd).await;
                        },
                        None => {
                            info!("Command channel closed, shutting down engine...");
                            break;
                        },
                    }
                }

                // 4. 定时任务
                _ = tick_interval.tick() => self.handle_tick().await,
                _ = dht_refresh_interval.tick() => self.dht_maintenance().await,

                // 5. (可选) 可以在这里添加 tokio::signal::ctrl_c() 的监听，
                // 但作为库，最好不要自作主张劫持信号。
            }
        }

        // --- 优雅退出阶段 ---
        info!("ETP Engine stopping. Cleaning up resources...");

        // 显式清空 Sessions。
        // 这会导致所有 SessionContext 被 Drop -> Flavor 被 Drop -> Sled Db 被 Drop -> 数据刷盘。
        self.ctx.sessions.clear();
        info!("Sessions cleared. Persistence layers should have flushed.");

        Ok(())
    }

    /// 优雅停机处理逻辑
    async fn handle_shutdown(&self) {
        info!(
            "Broadcasting Close frames to {} active sessions...",
            self.ctx.sessions.len()
        );

        // 收集所有活跃连接的地址，避免在迭代中死锁
        let targets: Vec<SocketAddr> = self.ctx.sessions.iter().map(|k| *k.key()).collect();

        for addr in targets {
            // 发送 CONNECTION_CLOSE 帧
            // 这是一个“尽力而为”的操作，不等待 ACK
            let frame = Frame::Close {
                error_code: 0,
                reason: "Node Shutdown".into(),
            };

            // 使用 send_frames 可能会被流控阻塞，这里我们尝试直接构造一个终结包
            // 或者简单调用 send_frames 并忽略错误
            if let Err(e) = self.send_frames(addr, vec![frame]).await {
                debug!("Failed to send close frame to {}: {}", addr, e);
            }
        }

        // 给网络栈一点时间把包发出去 (50ms)
        tokio::time::sleep(Duration::from_millis(50)).await;
    }

    fn spawn_incoming_handler(&self, data: Vec<u8>, src: SocketAddr) {
        let ctx = self.ctx.clone();
        let Ok(permit) = ctx.incoming_slots.clone().try_acquire_owned() else {
            return;
        };
        tokio::spawn(async move {
            let _permit = permit;
            for dialect in ctx.plugins.all_dialects() {
                if let Ok(plain) = dialect.open(&data) {
                    if let Ok(plain) = ctx.onion.open_control(src, &plain) {
                        if let Ok(packet) = bincode::DefaultOptions::new()
                            .with_fixint_encoding()
                            .with_limit(4096)
                            .reject_trailing_bytes()
                            .deserialize::<StatelessPacket>(&plain)
                        {
                            if packet.frames.len() <= 8 && packet.token.is_empty() {
                                Self::handle_stateless_packet(packet, src, &ctx).await;
                            }
                        }
                        return;
                    }
                }
            }
            if ctx.onion.receive(&data, src).await {
                return;
            }
            if let Some(handler) = &ctx.default_handler {
                if handler.handle(&data, src, &ctx.transport).await {
                    return;
                }
            }
            if ctx.sessions.contains_key(&src) {
                Self::process_existing_session(ctx, data, src).await;
            } else {
                Self::process_new_connection_or_fallback(ctx, data, src).await;
            }
        });
    }

    async fn process_existing_session(ctx: ProcessingContext, data: Vec<u8>, src: SocketAddr) {
        let session_lock = match ctx.sessions.get(&src).map(|s| s.value().clone()) {
            Some(s) => s,
            None => return,
        };

        // Note: Using RwLock write lock during processing
        let mut session = session_lock.lock().await;
        if !ctx
            .sessions
            .get(&src)
            .map(|current| Arc::ptr_eq(current.value(), &session_lock))
            .unwrap_or(false)
        {
            return;
        }
        session.last_activity = Instant::now();

        if session.dialect.probe(&data) {
            if let Ok(plain_data) = session.dialect.open(&data) {
                if !session.handshake_completed {
                    if plain_data.len() == 128 {
                        let remote = ctx.config.trusted_peers.get(&src);
                        if remote
                            .map(|k| ctx.config.keypair.public.as_slice() > k.as_slice())
                            .unwrap_or(false)
                        {
                            drop(session);
                            Self::process_new_connection_or_fallback(ctx, data, src).await;
                        }
                        return;
                    }
                    // Handshake processing...
                    let mut out = acquire_buffer();
                    out.resize(1024, 0);

                    let res = session.crypto.read_handshake_message(&plain_data, &mut out);
                    match res {
                        Ok((_len, fin)) => {
                            // ACL Check
                            if let Some(pubk) = session.crypto.get_remote_static() {
                                if !ctx.acl.allow_connection(pubk) {
                                    ctx.metrics.packet_drop_acl.fetch_add(1, Ordering::Relaxed);
                                    release_buffer(out);
                                    return;
                                }
                            }
                            // Check finish or write next
                            let mut complete = fin;
                            if !complete {
                                if let Ok((wlen, wfin)) =
                                    session.crypto.write_handshake_message(&[], &mut out)
                                {
                                    if wlen > 0 {
                                        let mut resp = out[..wlen].to_vec();
                                        session.dialect.seal(&mut resp);
                                        let _ = ctx.transport.send_to(&resp, src).await;
                                    }
                                    if wfin {
                                        complete = true;
                                    }
                                }
                            }

                            if complete {
                                session.handshake_completed = true;
                                ctx.metrics
                                    .handshake_success
                                    .fetch_add(1, Ordering::Relaxed);
                                session.flavor.on_connection_open(src);
                                // Flush pending frames if any
                                let pending = std::mem::take(&mut session.pending_queue);
                                drop(session); // release lock before sending
                                release_buffer(out);
                                Self::flush_pending_frames(ctx, src, pending).await;
                                return;
                            }
                        }
                        Err(_) => {
                            // Deep Security: Zero Tolerance
                            if ctx.config.security.handshake_zero_tolerance {
                                warn!("Zero Tolerance: Banning {} for invalid handshake", src);
                                ctx.banned_ips
                                    .insert(src, Instant::now() + Duration::from_secs(300));
                                ctx.sessions.remove(&src);
                            }
                        }
                    }
                    release_buffer(out);
                    return;
                }

                // Transport Phase
                let mut plaintext_buf = acquire_buffer();
                plaintext_buf.resize(plain_data.len(), 0);

                let decrypted = session.crypto.decrypt(&plain_data, &mut plaintext_buf);
                if decrypted.is_err() && plain_data.len() == 128 {
                    release_buffer(plaintext_buf);
                    drop(session);
                    Self::process_new_connection_or_fallback(ctx, data, src).await;
                    return;
                }
                if let Ok(len) = decrypted {
                    plaintext_buf.truncate(len);
                    if let Ok(pkt) = bincode::DefaultOptions::new()
                        .with_fixint_encoding()
                        .with_limit(65536)
                        .allow_trailing_bytes()
                        .deserialize::<StatefulPacket>(&plaintext_buf)
                    {
                        if pkt.session_id != 0 {
                            // Reliability Layer
                            let (dup, chunks) = session
                                .reliability
                                .on_packet_received(pkt.packet_number, pkt.frames.clone());
                            if dup {
                                release_buffer(plaintext_buf);
                                return;
                            }

                            // Process Control Frames
                            for frame in pkt.frames {
                                match frame {
                                    Frame::Ack {
                                        largest_acknowledged,
                                        ranges,
                                        ..
                                    } => session
                                        .reliability
                                        .on_ack_frame_received(largest_acknowledged, &ranges),
                                    Frame::Close { .. } => info!("Session closed by {}", src),
                                    Frame::Injection { .. } => {
                                        if ctx.acl.verify_frame(&frame).unwrap_or(false) {}
                                    }
                                    // [Side Channel Ingress]
                                    Frame::SideChannel { channel_id, data } => {
                                        let allowed =
                                            if ctx.config.security.allow_dynamic_side_channels {
                                                session
                                                    .side_channels
                                                    .on_frame_received(channel_id, data)
                                            } else {
                                                // TODO: Check against registered list logic
                                                session
                                                    .side_channels
                                                    .on_frame_received(channel_id, data)
                                            };
                                        if allowed {
                                            ctx.metrics
                                                .control_bytes_ingress
                                                .fetch_add(1, Ordering::Relaxed);
                                        }
                                    }
                                    _ => {}
                                }
                            }

                            // [Feature: Virtual Stream Bridging]
                            // Extract messages from SideChannelManager and bridge to Flavor
                            let active_ids = session.side_channels.active_channel_ids();
                            let mut control_events = Vec::new();
                            for id in active_ids {
                                while let Some(msg) = session.side_channels.recv_message(id) {
                                    // Protocol: [ChannelID 4B][Payload]
                                    let mut bridged = Vec::with_capacity(4 + msg.len());
                                    bridged.extend_from_slice(&id.to_be_bytes());
                                    bridged.extend_from_slice(&msg);
                                    control_events.push(bridged);
                                }
                            }

                            // Deliver Data to Flavor

                            // 1. Data Streams
                            for (stream_id, chunk_data) in chunks {
                                if let Some(processed) =
                                    session.run_ingress_interceptors(stream_id, chunk_data)
                                {
                                    let f_ctx = FlavorContext {
                                        src_addr: src,
                                        stream_id,
                                        data_len: processed.len(),
                                        system: &ctx,
                                    };
                                    if !session.flavor.on_stream_data(f_ctx, &processed) {
                                        // Fallback legacy
                                        if stream_id == 1 {
                                            let _ = ctx.data_tx.send((src, processed)).await;
                                        }
                                    }
                                }
                            }

                            // 2. Control Stream (Stream 0)
                            for event_data in control_events {
                                let f_ctx = FlavorContext {
                                    src_addr: src,
                                    stream_id: VIRTUAL_STREAM_SIDE_CHANNEL,
                                    data_len: event_data.len(),
                                    system: &ctx,
                                };
                                session.flavor.on_stream_data(f_ctx, &event_data);
                            }
                        }
                    }
                }
                release_buffer(plaintext_buf);
                return;
            }
        }
        ctx.metrics
            .packet_drop_format
            .fetch_add(1, Ordering::Relaxed);
    }

    async fn process_new_connection_or_fallback(
        ctx: ProcessingContext,
        data: Vec<u8>,
        src: SocketAddr,
    ) {
        if !ctx.config.trusted_peers.contains_key(&src) {
            return;
        }
        let mut handled = false;

        // Dynamic dialect probing
        let candidates = ctx.plugins.all_dialects();

        for dialect in candidates {
            if !dialect.probe(&data) {
                continue;
            }
            let plain_data = match dialect.open(&data) {
                Ok(d) => d,
                Err(_) => continue,
            };

            if plain_data.len() != 128 {
                continue;
            }
            let fingerprint = *blake3::hash(&plain_data).as_bytes();
            let cached = {
                let mut cache = ctx.handshakes.lock();
                cache.retain(|_, (time, _)| time.elapsed() < Duration::from_secs(36));
                cache
                    .get(&(src, fingerprint))
                    .map(|(_, reply)| reply.clone())
            };
            if let Some(reply) = cached {
                let _ = ctx.transport.send_to(&reply, src).await;
                return;
            }
            if ctx.sessions.len() >= ctx.config.max_sessions && !ctx.sessions.contains_key(&src) {
                return;
            }

            let default_flavor = ctx
                .plugins
                .get_flavor(&ctx.config.default_flavor)
                .unwrap_or(Arc::new(crate::plugin::StandardFlavor));
            let interceptors = ctx.plugins.get_default_interceptors();

            let mut session = SessionContext::new(
                NoiseSession::new_responder(&ctx.config.keypair).unwrap(),
                &ctx.config,
                dialect.clone(),
                default_flavor.clone(),
                interceptors,
                &ctx.plugins,
            );

            // Respond to handshake
            let mut out = acquire_buffer();
            out.resize(1024, 0);

            if let Ok((payload_len, finished)) =
                session.crypto.read_handshake_message(&plain_data, &mut out)
            {
                let now = std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_secs();
                if payload_len != 32 || &out[..8] != b"ETPIK3\0\0" {
                    release_buffer(out);
                    continue;
                }
                let issued = u64::from_be_bytes(out[8..16].try_into().unwrap());
                if issued > now.saturating_add(5) || now > issued.saturating_add(30) {
                    release_buffer(out);
                    continue;
                }
                if session.crypto.get_remote_static()
                    != ctx.config.trusted_peers.get(&src).map(|key| key.as_slice())
                {
                    release_buffer(out);
                    continue;
                }
                if ctx.handshakes.lock().len() >= 4096 {
                    release_buffer(out);
                    return;
                }

                if let Some(pubk) = session.crypto.get_remote_static() {
                    if !ctx.acl.allow_connection(pubk) {
                        ctx.metrics.packet_drop_acl.fetch_add(1, Ordering::Relaxed);
                        release_buffer(out);
                        return;
                    }
                }
                if let Ok((wlen, wfin)) = session.crypto.write_handshake_message(&[], &mut out) {
                    if wlen > 0 {
                        let mut resp = out[..wlen].to_vec();
                        dialect.seal(&mut resp);
                        ctx.handshakes
                            .lock()
                            .insert((src, fingerprint), (Instant::now(), resp.clone()));
                        if let Some(previous) = ctx.sessions.get(&src).map(|s| s.value().clone()) {
                            let mut previous = previous.lock().await;
                            std::mem::swap(&mut session.reliability, &mut previous.reliability);
                            session.stream_offsets = std::mem::take(&mut previous.stream_offsets);
                            session.pending_queue = std::mem::take(&mut previous.pending_queue);
                        }
                        let _ = ctx.transport.send_to(&resp, src).await;
                    }
                    session.handshake_completed = wfin || finished;
                    if session.handshake_completed {
                        ctx.metrics
                            .handshake_success
                            .fetch_add(1, Ordering::Relaxed);
                        session.flavor.on_connection_open(src);
                    }
                    ctx.sessions
                        .insert(src, Arc::new(tokio::sync::Mutex::new(session)));
                    ctx.metrics.active_sessions.fetch_add(1, Ordering::Relaxed);
                    handled = true;
                    release_buffer(out);
                    break;
                }
            }
            release_buffer(out);
        }

        if handled {
            return;
        }
        if let Some(handler) = &ctx.fallback_handler {
            handler.handle(&data, src, &ctx.transport).await;
        }
    }

    async fn handle_stateless_packet(
        pkt: StatelessPacket,
        src: SocketAddr,
        ctx: &ProcessingContext,
    ) {
        for frame in pkt.frames {
            match frame {
                Frame::SideChannel {
                    channel_id: 0,
                    data,
                } => {
                    Self::handle_dht_rpc(data, src, ctx).await;
                }
                Frame::NatSignal {
                    signal_type: NatSignalType::Ping,
                    ..
                } => {
                    let pong = Frame::NatSignal {
                        signal_type: NatSignalType::Pong,
                        payload: vec![],
                    };
                    let _ = Self::send_stateless_packet_internal(ctx, src, vec![pong]).await;
                }
                _ => {}
            }
        }
    }

    async fn handle_command(&self, cmd: Command) {
        match cmd {
            Command::SendData { target, data } => self.handle_app_data(target, 1, data).await,
            Command::SendStream {
                target,
                stream_id,
                data,
            } => self.handle_app_data(target, stream_id, data).await,

            // [New] Control Plane Logic
            Command::SendControl {
                target,
                category,
                data,
            } => {
                if let Some(session_ref) = self.ctx.sessions.get(&target).map(|s| s.value().clone())
                {
                    let mut session = session_ref.lock().await;
                    let sc_manager = &mut session.side_channels;
                    let channel_id = category.id();

                    // Lazy Creation Logic
                    if !sc_manager.send_message(channel_id, data.clone()) {
                        debug!(
                            "Control: Initializing side channel {} for {}",
                            channel_id, target
                        );
                        let policy = category.policy();
                        if sc_manager.register_or_update_channel(channel_id, policy) {
                            if !sc_manager.send_message(channel_id, data) {
                                warn!("Control: Dropped command to {} (Buffer full)", target);
                            } else {
                                self.ctx
                                    .metrics
                                    .control_bytes_egress
                                    .fetch_add(1, Ordering::Relaxed);
                            }
                        } else {
                            warn!(
                                "Control: Failed to register channel {} for {}",
                                channel_id, target
                            );
                        }
                    } else {
                        self.ctx
                            .metrics
                            .control_bytes_egress
                            .fetch_add(1, Ordering::Relaxed);
                    }

                    // Trigger immediate send if critical
                    if matches!(category, ControlCategory::Critical) {
                        // In a real loop, we might signal a condition variable to wake up handle_tick
                    }
                } else {
                    warn!("Control: Session not found for {}", target);
                }
            }

            Command::Connect { target, remote_pub } => {
                let _ = self.initiate_handshake(target, &remote_pub).await;
            }
            Command::SendOnion { path, data, reply } => {
                let _ = reply.send(
                    self.handle_onion_send(path, data)
                        .await
                        .map_err(|_| "onion route rejected".to_string()),
                );
            }
            Command::DhtFindNode { target_id, reply } => {
                // Simplified DHT logic for example
                let nonce = rand::random::<u64>();
                let neighbors = self.ctx.routing_table.find_closest(&target_id, 3);
                if neighbors.is_empty() {
                    let _ = reply.send(Ok(Vec::new()));
                    return;
                }
                if self.ctx.dht_pending_queries.len() >= 128 {
                    let _ = reply.send(Err(anyhow!("query budget")));
                    return;
                }
                self.ctx.dht_pending_queries.insert(
                    nonce,
                    (
                        neighbors.iter().map(|n| n.addr).collect(),
                        Instant::now(),
                        reply,
                    ),
                );
                for node in neighbors {
                    let mut payload = vec![0x01];
                    payload.extend_from_slice(&nonce.to_be_bytes());
                    payload.extend_from_slice(&self.ctx.my_node_id());
                    payload.extend_from_slice(&target_id);
                    let frame = Frame::SideChannel {
                        channel_id: 0,
                        data: payload,
                    }; // Stateless uses Ch 0
                    let _ = Self::send_stateless_packet_internal(&self.ctx, node.addr, vec![frame])
                        .await;
                }
            }
            Command::DhtStore { key, value, ttl } => {
                if value.len() > 2048
                    || ttl == 0
                    || ttl > 86400
                    || *blake3::hash(&value).as_bytes() != key
                {
                    return;
                }
                let neighbors = self.ctx.routing_table.find_closest(&key, 5);
                for node in neighbors {
                    let mut payload = vec![0x02];
                    payload.extend_from_slice(&self.ctx.my_node_id());
                    payload.extend_from_slice(&key);
                    payload.extend_from_slice(&ttl.to_be_bytes());
                    payload.extend_from_slice(&value);
                    let frame = Frame::SideChannel {
                        channel_id: 0,
                        data: payload,
                    };
                    let _ = Self::send_stateless_packet_internal(&self.ctx, node.addr, vec![frame])
                        .await;
                }
            }
            Command::GetStats { reply } => {
                let m = &self.ctx.metrics;
                let s = format!(
                    "Sessions: {} | Ctrl TX: {} | Cover: {}",
                    m.active_sessions.load(Ordering::Relaxed),
                    m.control_bytes_egress.load(Ordering::Relaxed),
                    m.cover_traffic_bytes.load(Ordering::Relaxed)
                );
                let _ = reply.send(s);
            }
            Command::Shutdown => {
                info!("Shutdown command received.");
            }
        }
    }

    async fn handle_app_data(&self, target: SocketAddr, stream_id: u32, data: Vec<u8>) {
        if data.len() > 1024 || stream_id > 4095 {
            return;
        }
        if !self.ctx.sessions.contains_key(&target) {
            let Some(key) = self.ctx.config.trusted_peers.get(&target) else {
                return;
            };
            if self.initiate_handshake(target, key).await.is_err() {
                return;
            }
        }
        let session = self.ctx.sessions.get(&target).map(|s| s.value().clone());
        if let Some(session) = session {
            let offset = {
                let mut guard = session.lock().await;
                let offset = guard.stream_offsets.entry(stream_id).or_insert(0);
                let previous = *offset;
                *offset = offset.saturating_add(data.len() as u64);
                previous
            };
            let _ = self
                .send_frames(
                    target,
                    vec![Frame::Stream {
                        stream_id,
                        offset,
                        fin: false,
                        data,
                    }],
                )
                .await;
        }
    }

    async fn send_frames(&self, target: SocketAddr, frames: Vec<Frame>) -> Result<()> {
        let session_ref = self
            .ctx
            .sessions
            .get(&target)
            .map(|s| s.value().clone())
            .ok_or(anyhow!("Session lost"))?;
        let mut ctx = session_ref.lock().await;

        // 1. Handshake check
        if !ctx.handshake_completed {
            anyhow::ensure!(
                ctx.pending_queue.len() + frames.len() <= 1024,
                "pending frame budget"
            );
            ctx.pending_queue.extend(frames);
            return Ok(());
        }

        // 2. Feature: Strict PFS Ratchet (Deep Security)
        if ctx.needs_strict_rekey() {
            let remote = ctx
                .crypto
                .get_remote_static()
                .ok_or_else(|| anyhow!("missing authenticated peer key"))?
                .to_vec();
            if ctx.pending_queue.len() + frames.len() > 1024 {
                return Err(anyhow!("pending frame budget"));
            }
            ctx.pending_queue.extend(frames);
            drop(ctx);
            drop(session_ref);
            self.initiate_handshake(target, &remote).await?;
            return Ok(());
        }

        // 3. Congestion Check
        if !ctx.reliability.can_send()
            && frames
                .iter()
                .any(|f| !matches!(f, Frame::Ack { .. } | Frame::Padding(_)))
        {
            anyhow::ensure!(
                ctx.pending_queue.len() + frames.len() <= 1024,
                "pending frame budget"
            );
            ctx.pending_queue.extend(frames);
            return Ok(());
        }

        let mut processed_frames = Vec::new();

        // 4. Interceptors
        for frame in frames {
            match frame {
                Frame::Stream {
                    stream_id,
                    offset,
                    fin,
                    data,
                } => {
                    if let Some(mod_data) = ctx.run_egress_interceptors(stream_id, data) {
                        processed_frames.push(Frame::Stream {
                            stream_id,
                            offset,
                            fin,
                            data: mod_data,
                        });
                    }
                }
                _ => processed_frames.push(frame),
            }
        }

        // 5. [Priority Scheduling] Extract Side Channel frames FIRST
        let mtu = self.ctx.config.mtu;
        let side_capacity = mtu.saturating_sub(100);
        let mut side_frames = ctx.side_channels.pop_outgoing_frames(side_capacity);

        // Merge: Side Channels go first!
        let mut final_frames = side_frames;
        final_frames.append(&mut processed_frames);

        // 6. Feature: Cover Traffic (Deep Anonymity)
        // If packet is too small or empty, inject chaff?
        if final_frames.is_empty() {
            let padding_needed = ctx.cover_engine.calculate_padding_needed();
            if padding_needed > 0 {
                // Use a datagram side channel for chaff (ID 0xFF or just Padding frame)
                // Frame::Padding is simpler
                final_frames.push(Frame::new_padding(padding_needed));
                self.ctx
                    .metrics
                    .cover_traffic_bytes
                    .fetch_add(padding_needed as u64, Ordering::Relaxed);
            } else {
                return Ok(());
            }
        }

        // 7. Pacing & Jitter (Deep Anonymity)
        let mut delay = Duration::ZERO;
        if let Some(pacing_delay) = ctx.shaper.wait_for_slot().await {
            if pacing_delay > 0 {
                final_frames.push(Frame::new_padding(pacing_delay)); // Use size hint as padding
            }
        }

        // Apply Jitter
        let (min_j, max_j) = ctx.config_snapshot.anonymity.jitter_ms_range;
        if max_j > 0 {
            let jitter_ms = rand::thread_rng().gen_range(min_j..=max_j);
            tokio::time::sleep(Duration::from_millis(jitter_ms)).await;
        }

        // 8. Finalize & Send
        let pn = ctx.reliability.get_next_packet_num();
        let est_size: usize = final_frames.iter().map(|_| 100).sum();
        if final_frames
            .iter()
            .any(|f| !matches!(f, Frame::Ack { .. } | Frame::Padding(_)))
        {
            ctx.reliability
                .on_packet_sent(pn, final_frames.clone(), est_size);
        }

        let packet = DecryptedPacket::Stateful(StatefulPacket {
            session_id: 1,
            packet_number: pn,
            frames: final_frames,
        });

        let dialect = ctx.dialect.clone();
        let raw = RawPacket::encrypt_and_seal(&packet, &mut ctx.crypto, None, dialect.as_ref())?;
        let len = raw.data.len();

        // Update stats
        ctx.bytes_sent_since_rekey += len as u64;
        ctx.bytes_sent_total += len as u64;
        ctx.cover_engine.record_sent(len); // Notify cover engine of activity

        self.ctx.transport.send_to(&raw.data, target).await?;
        self.ctx
            .metrics
            .bytes_egress
            .fetch_add(len as u64, Ordering::Relaxed);
        ctx.last_activity = Instant::now();
        Ok(())
    }

    async fn initiate_handshake(&self, target: SocketAddr, remote_pub: &[u8]) -> Result<()> {
        let d_dial = self
            .ctx
            .plugins
            .get_dialect(&self.ctx.config.default_dialect)
            .unwrap();
        let d_flav = self
            .ctx
            .plugins
            .get_flavor(&self.ctx.config.default_flavor)
            .unwrap();
        let interceptors = self.ctx.plugins.get_default_interceptors();

        let mut session = SessionContext::new(
            NoiseSession::new_initiator(&self.ctx.config.keypair, remote_pub)?,
            &self.ctx.config,
            d_dial,
            d_flav,
            interceptors,
            &self.ctx.plugins,
        );
        if let Some(previous) = self.ctx.sessions.get(&target).map(|s| s.value().clone()) {
            let mut previous = previous.lock().await;
            session.pending_queue = std::mem::take(&mut previous.pending_queue);
            session.stream_offsets = std::mem::take(&mut previous.stream_offsets);
            std::mem::swap(&mut session.reliability, &mut previous.reliability);
        }
        let mut buf = acquire_buffer();
        buf.resize(1024, 0);
        let mut hello = b"ETPIK3\0\0".to_vec();
        hello.extend_from_slice(
            &std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)?
                .as_secs()
                .to_be_bytes(),
        );
        let random: [u8; 16] = rand::random();
        hello.extend_from_slice(&random);
        let (len, _) = session.crypto.write_handshake_message(&hello, &mut buf)?;

        let mut message = buf[..len].to_vec();
        session.dialect.seal(&mut message);
        session.handshake_flight = message.clone();
        session.handshake_sent = Instant::now();
        session.handshake_attempts = 1;
        self.ctx
            .sessions
            .insert(target, Arc::new(tokio::sync::Mutex::new(session)));
        self.ctx.transport.send_to(&message, target).await?;
        self.ctx
            .metrics
            .active_sessions
            .fetch_add(1, Ordering::Relaxed);
        release_buffer(buf);
        Ok(())
    }

    async fn flush_pending_frames(
        ctx: ProcessingContext,
        target: SocketAddr,
        mut frames: VecDeque<Frame>,
    ) {
        if let Some(s) = ctx.sessions.get(&target).map(|s| s.value().clone()) {
            let mut session = s.lock().await;
            let mut batch = Vec::new();
            while let Some(f) = frames.pop_front() {
                batch.push(f);
                if batch.len() >= 5 {
                    let pn = session.reliability.get_next_packet_num();
                    session.reliability.on_packet_sent(pn, batch.clone(), 500);
                    let pkt = DecryptedPacket::Stateful(StatefulPacket {
                        session_id: 1,
                        packet_number: pn,
                        frames: batch.clone(),
                    });
                    let dialect = session.dialect.clone();
                    if let Ok(raw) = RawPacket::encrypt_and_seal(
                        &pkt,
                        &mut session.crypto,
                        None,
                        dialect.as_ref(),
                    ) {
                        let _ = ctx.transport.send_to(&raw.data, target).await;
                    }
                    batch.clear();
                }
            }
            if !batch.is_empty() {
                let pn = session.reliability.get_next_packet_num();
                session.reliability.on_packet_sent(pn, batch.clone(), 500);
                let pkt = DecryptedPacket::Stateful(StatefulPacket {
                    session_id: 1,
                    packet_number: pn,
                    frames: batch,
                });
                let dialect = session.dialect.clone();
                if let Ok(raw) =
                    RawPacket::encrypt_and_seal(&pkt, &mut session.crypto, None, dialect.as_ref())
                {
                    let _ = ctx.transport.send_to(&raw.data, target).await;
                }
            }
        }
    }

    async fn send_stateless_packet_internal(
        ctx: &ProcessingContext,
        target: SocketAddr,
        frames: Vec<Frame>,
    ) -> Result<()> {
        let token = Vec::new();
        let nonce = rand::random::<u64>();
        let packet = StatelessPacket {
            token,
            nonce,
            frames,
        };
        let plain = ctx
            .onion
            .seal_control(target, &bincode::serialize(&packet)?)?;
        let default_dialect = ctx
            .plugins
            .get_dialect(&ctx.config.default_dialect)
            .unwrap();
        let mut masked = plain;
        default_dialect.seal(&mut masked);
        ctx.transport.send_to(&masked, target).await?;
        Ok(())
    }

    async fn handle_dht_rpc(data: Vec<u8>, src: SocketAddr, ctx: &ProcessingContext) {
        if data.is_empty() {
            return;
        }

        let op = data[0];
        let payload = &data[1..];
        let Some(public) = ctx.config.trusted_peers.get(&src) else {
            return;
        };
        let expected = *blake3::hash(public).as_bytes();
        let claimed = if op == Self::DHT_OP_STORE {
            payload.get(..32)
        } else {
            payload.get(8..40)
        };
        if claimed != Some(expected.as_slice()) {
            return;
        }

        let my_id = ctx.my_node_id();

        // 辅助闭包：更新路由表 (被动发现)
        // 只有当 sender_id 不是我们自己时才添加
        let update_routing = |sender_id: NodeID| {
            if sender_id != my_id {
                let node_info = NodeInfo::new(sender_id, src);
                // add_node 内部会自动处理 Bucket 逻辑和活跃时间更新
                ctx.routing_table.add_node(node_info);
            }
        };

        match op {
            Self::DHT_OP_FIND_NODE => {
                // Request: [Nonce(8)] [SenderID(32)] [TargetID(32)]
                // Min Len: 8 + 32 + 32 = 72
                if payload.len() < 72 {
                    return;
                }

                let nonce_bytes: [u8; 8] = payload[0..8].try_into().unwrap();
                let sender_id: NodeID = payload[8..40].try_into().unwrap();
                let target_id: NodeID = payload[40..72].try_into().unwrap();

                // 1. 被动更新路由表
                update_routing(sender_id);

                // 2. 查找逻辑
                let neighbors = ctx.routing_table.find_closest(&target_id, 8);

                // 3. 构造响应: [OP_RESP] [Nonce] [ResponderID(Me)] [NodesData]
                if let Ok(nodes_data) = bincode::serialize(&neighbors) {
                    let mut resp = Vec::with_capacity(1 + 8 + 32 + nodes_data.len());
                    resp.push(Self::DHT_OP_FIND_NODE_RESP);
                    resp.extend_from_slice(&nonce_bytes);
                    resp.extend_from_slice(&my_id);
                    resp.extend(nodes_data);

                    let frame = Frame::SideChannel {
                        channel_id: 0,
                        data: resp,
                    };
                    let _ = Self::send_stateless_packet_internal(ctx, src, vec![frame]).await;
                }
            }

            Self::DHT_OP_STORE => {
                // Request: [SenderID(32)] [Key(32)] [TTL(4)] [Value...]
                // Min Len: 32 + 32 + 4 = 68
                if payload.len() < 68 {
                    return;
                }

                let sender_id: NodeID = payload[0..32].try_into().unwrap();
                let key: NodeID = payload[32..64].try_into().unwrap();
                let ttl_bytes: [u8; 4] = payload[64..68].try_into().unwrap();
                let ttl = u32::from_be_bytes(ttl_bytes);
                let value = payload[68..].to_vec();

                // 1. 被动更新路由表
                update_routing(sender_id);

                // 2. 存储逻辑
                if value.len() > 2048
                    || ttl == 0
                    || ttl > 86400
                    || *blake3::hash(&value).as_bytes() != key
                    || (ctx.dht_store.len() >= 1024 && !ctx.dht_store.contains_key(&key))
                {
                    return;
                }
                let expiry = std::time::SystemTime::now() + Duration::from_secs(ttl as u64);
                ctx.dht_store.insert(key, (value, expiry));

                trace!("DHT: Stored key {:?} from {}", hex::encode(&key[0..4]), src);
            }

            Self::DHT_OP_PING => {
                // Request: [Nonce(8)] [SenderID(32)]
                // Min Len: 8 + 32 = 40
                if payload.len() < 40 {
                    return;
                }

                let nonce_bytes = &payload[0..8];
                let sender_id: NodeID = payload[8..40].try_into().unwrap();

                // 1. 被动更新路由表
                update_routing(sender_id);

                // 2. 发送 PONG: [OP_PONG] [Nonce] [ResponderID(Me)]
                let mut resp = Vec::with_capacity(1 + 8 + 32);
                resp.push(Self::DHT_OP_PONG);
                resp.extend_from_slice(nonce_bytes);
                resp.extend_from_slice(&my_id);

                let frame = Frame::SideChannel {
                    channel_id: 0,
                    data: resp,
                };
                let _ = Self::send_stateless_packet_internal(ctx, src, vec![frame]).await;
            }

            Self::DHT_OP_FIND_NODE_RESP => {
                // Response: [Nonce(8)] [ResponderID(32)] [NodesData...]
                // Min Len: 8 + 32 = 40
                if payload.len() < 40 {
                    return;
                }

                let mut nonce_bytes = [0u8; 8];
                nonce_bytes.copy_from_slice(&payload[0..8]);
                let nonce_val = u64::from_be_bytes(nonce_bytes);

                let responder_id: NodeID = payload[8..40].try_into().unwrap();

                // 1. 被动更新路由表 (确认对方活着)
                update_routing(responder_id);

                // 2. 触发回调
                let expected = ctx
                    .dht_pending_queries
                    .get(&nonce_val)
                    .map(|q| q.0.contains(&src) && q.1.elapsed() < Duration::from_secs(5))
                    .unwrap_or(false);
                if !expected {
                    return;
                }
                let Ok(nodes) = bincode::DefaultOptions::new()
                    .with_fixint_encoding()
                    .with_limit(4096)
                    .reject_trailing_bytes()
                    .deserialize::<Vec<NodeInfo>>(&payload[40..])
                else {
                    return;
                };
                if nodes.len() > 64 {
                    return;
                }
                let mut nodes: Vec<_> = nodes
                    .into_iter()
                    .filter(|node| {
                        ctx.config
                            .trusted_peers
                            .get(&node.addr)
                            .map(|key| *blake3::hash(key).as_bytes() == node.id)
                            .unwrap_or(false)
                    })
                    .collect();
                if !nodes.iter().any(|n| n.addr == src) {
                    nodes.push(NodeInfo::new(responder_id, src));
                }
                nodes.truncate(64);
                if let Some((_, (_, _, sender))) = ctx.dht_pending_queries.remove(&nonce_val) {
                    for node in &nodes {
                        ctx.routing_table.add_node(node.clone());
                    }
                    let _ = sender.send(Ok(nodes));
                }
            }

            Self::DHT_OP_PONG => {
                // Response: [Nonce(8)] [ResponderID(32)]
                if payload.len() < 40 {
                    return;
                }
                let responder_id: NodeID = payload[8..40].try_into().unwrap();

                // 收到 Pong，证明对方在线，刷新路由表
                update_routing(responder_id);
            }

            _ => {
                debug!("DHT: Unknown OpCode {} from {}", op, src);
            }
        }
    }

    async fn handle_onion_send(
        &self,
        path: Vec<(SocketAddr, Vec<u8>)>,
        data: Vec<u8>,
    ) -> Result<()> {
        self.ctx.onion.send(path, data).await
    }

    fn encrypt_stateless_payload(data: &[u8], nonce: u64, secret: &[u8]) -> Result<Vec<u8>> {
        let mut hasher = blake3::Hasher::new();
        hasher.update(secret);
        hasher.update(&nonce.to_le_bytes());
        let key = hasher.finalize();
        let cipher = ChaCha20Poly1305::new(key.as_bytes().into());
        let n = [0u8; 12];
        cipher
            .encrypt(&n.into(), data)
            .map_err(|_| anyhow!("Enc fail"))
    }

    fn decrypt_stateless_payload(data: &[u8], nonce: u64, secret: &[u8]) -> Result<Vec<u8>> {
        let mut hasher = blake3::Hasher::new();
        hasher.update(secret);
        hasher.update(&nonce.to_le_bytes());
        let key = hasher.finalize();
        let cipher = ChaCha20Poly1305::new(key.as_bytes().into());
        let n = [0u8; 12];
        cipher
            .decrypt(&n.into(), data)
            .map_err(|_| anyhow!("Dec fail"))
    }

    async fn handle_tick(&self) {
        self.ctx
            .dht_pending_queries
            .retain(|_, q| q.1.elapsed() < Duration::from_secs(5));
        let mut remove_list = Vec::new();
        let mut tasks = Vec::new();
        let mut flights = Vec::new();
        let timeout = self.ctx.config.session_timeout;

        let sessions: Vec<_> = self
            .ctx
            .sessions
            .iter()
            .map(|e| (*e.key(), e.value().clone()))
            .collect();
        for (target, session) in sessions {
            let mut ctx = session.lock().await;
            // Timeout Check
            if ctx.last_activity.elapsed() > timeout {
                remove_list.push(target);
                continue;
            }

            ctx.side_channels.maintenance();

            if !ctx.handshake_completed {
                if !ctx.handshake_flight.is_empty()
                    && ctx.handshake_sent.elapsed() > Duration::from_millis(300)
                {
                    if ctx.handshake_attempts >= 5 {
                        remove_list.push(target);
                    } else {
                        flights.push((target, ctx.handshake_flight.clone()));
                        ctx.handshake_attempts += 1;
                        ctx.handshake_sent = Instant::now();
                    }
                }
                continue;
            }

            let mut frames = Vec::new();
            if ctx.reliability.can_send() {
                for _ in 0..5 {
                    if let Some(frame) = ctx.pending_queue.pop_front() {
                        frames.push(frame);
                    } else {
                        break;
                    }
                }
            }

            // 1. Reliability Maintenance
            frames.append(&mut ctx.reliability.get_lost_frames());
            if ctx.reliability.should_send_ack() {
                frames.push(ctx.reliability.generate_ack());
            }

            // 2. Poll Flavors (Might push data to tx queue)
            ctx.flavor.poll();

            // 3. Keepalive / Cover Traffic Check
            let is_idle = ctx.last_activity.elapsed() > DEFAULT_KEEPALIVE;
            let needs_cover = ctx.cover_engine.calculate_padding_needed() > 0;

            if frames.is_empty() && (is_idle || needs_cover) {
                // If idle or needs cover, send empty packet which might be padded in send_frames
                // We push an empty frame list to trigger send_frames,
                // where CoverEngine and Shaper will add padding.
                tasks.push((target, vec![]));
            } else if !frames.is_empty() {
                tasks.push((target, frames));
            }
        }

        for target in remove_list {
            self.ctx.sessions.remove(&target);
            self.ctx
                .metrics
                .active_sessions
                .fetch_sub(1, Ordering::Relaxed);
        }

        for (target, packet) in flights {
            let _ = self.ctx.transport.send_to(&packet, target).await;
        }
        for (t, f) in tasks {
            let _ = self.send_frames(t, f).await;
        }
    }

    async fn dht_maintenance(&self) {
        let now_sys = std::time::SystemTime::now();

        // 1. 存储清理 (Garbage Collection)
        let mut expired_keys = Vec::new();
        // DashMap 迭代器可能会锁住分片，收集 key 后再删除是比较安全的做法
        for entry in self.ctx.dht_store.iter() {
            if entry.value().1 < now_sys {
                expired_keys.push(*entry.key());
            }
        }
        let expired_count = expired_keys.len();
        for k in expired_keys {
            self.ctx.dht_store.remove(&k);
        }

        // 2. 路由表刷新 (Bucket Refresh)
        let refresh_ids = self.ctx.routing_table.get_refresh_ids();
        let refresh_count = refresh_ids.len();

        // 我们的 ID，用于在请求中表明身份
        let my_id = self.ctx.my_node_id();

        for target_id in refresh_ids {
            let nonce = rand::random::<u64>();

            // 记录 Pending，虽然对于 Refresh 我们可能不关心结果，
            // 但为了防止收到回复时被当作无关包丢弃，最好还是注册一下
            self.ctx
                .dht_pending_queries
                .retain(|_, q| q.1.elapsed() < Duration::from_secs(5));

            let neighbors = self.ctx.routing_table.find_closest(&target_id, 3);

            // 构造请求包: [OP][Nonce][SenderID][TargetID]
            let mut payload = Vec::with_capacity(1 + 8 + 32 + 32);
            payload.push(Self::DHT_OP_FIND_NODE);
            payload.extend_from_slice(&nonce.to_be_bytes());
            payload.extend_from_slice(&my_id); // 携带我的 ID
            payload.extend_from_slice(&target_id);

            let frame = Frame::SideChannel {
                channel_id: 0,
                data: payload,
            };

            for node in neighbors {
                let _ =
                    Self::send_stateless_packet_internal(&self.ctx, node.addr, vec![frame.clone()])
                        .await;
            }

            // 平滑流量
            tokio::time::sleep(Duration::from_millis(20)).await;
        }

        // 3. 节点探活 (Ping Stale Nodes)
        let stale_nodes = self.ctx.routing_table.get_stale_nodes();
        let ping_count = stale_nodes.len();

        for node_id in stale_nodes {
            if let Some(node_info) = self.ctx.routing_table.lookup(&node_id) {
                let nonce = rand::random::<u64>();
                // 构造 Ping 包: [OP][Nonce][SenderID]
                let mut payload = Vec::with_capacity(1 + 8 + 32);
                payload.push(Self::DHT_OP_PING);
                payload.extend_from_slice(&nonce.to_be_bytes());
                payload.extend_from_slice(&my_id); // 携带我的 ID

                let frame = Frame::SideChannel {
                    channel_id: 0,
                    data: payload,
                };
                let _ =
                    Self::send_stateless_packet_internal(&self.ctx, node_info, vec![frame]).await;
            }
        }

        if expired_count > 0 || refresh_count > 0 || ping_count > 0 {
            debug!(
                "DHT Maintenance: Expired {} keys, Refreshed {} buckets, Pinged {} stale peers.",
                expired_count, refresh_count, ping_count
            );
        }
    }
}

#[cfg(test)]
mod runtime_regression_tests {
    use super::*;
    #[tokio::test]
    async fn real_udp_noise_stream_offsets_and_authenticated_dht_work_together() {
        let a_socket = Arc::new(UdpSocket::bind("127.0.0.1:0").await.unwrap());
        let b_socket = Arc::new(UdpSocket::bind("127.0.0.1:0").await.unwrap());
        let a_address = a_socket.local_addr().unwrap();
        let b_address = b_socket.local_addr().unwrap();
        let mut a_config = NodeConfig::default();
        let mut b_config = NodeConfig::default();
        a_config.trusted_peers.insert(
            b_address,
            b_config.keypair.public.as_slice().try_into().unwrap(),
        );
        b_config.trusted_peers.insert(
            a_address,
            a_config.keypair.public.as_slice().try_into().unwrap(),
        );
        a_config.security.strict_rekey_interval_secs = 1;
        b_config.security.strict_rekey_interval_secs = 1;
        let b_id = *blake3::hash(&b_config.keypair.public).as_bytes();
        let (a, a_handle, _) = EtpEngine::new_with_transport(
            a_config,
            Arc::new(PluginRegistry::new()),
            Arc::new(UdpTransport(a_socket)),
        )
        .await
        .unwrap();
        let (b, b_handle, mut received) = EtpEngine::new_with_transport(
            b_config,
            Arc::new(PluginRegistry::new()),
            Arc::new(UdpTransport(b_socket)),
        )
        .await
        .unwrap();
        let a_task = tokio::spawn(a.run());
        let b_task = tokio::spawn(b.run());
        let exchange = async {
            // Auto-connect uses the pinned remote key, not a zero key.
            a_handle
                .send_data(b_address, b"first".to_vec())
                .await
                .unwrap();
            assert_eq!(received.recv().await.unwrap().1, b"first");
            a_handle
                .send_data(b_address, b"second".to_vec())
                .await
                .unwrap();
            assert_eq!(received.recv().await.unwrap().1, b"second");
            let found = a_handle.dht_find_node(b_id).await.unwrap();
            assert!(found.iter().any(|n| n.id == b_id && n.addr == b_address));
            tokio::time::sleep(Duration::from_millis(1100)).await;
            a_handle
                .send_data(b_address, b"after rekey".to_vec())
                .await
                .unwrap();
            assert_eq!(received.recv().await.unwrap().1, b"after rekey");
            b_handle
                .send_data(a_address, b"return".to_vec())
                .await
                .unwrap();
        };
        let result = tokio::time::timeout(Duration::from_secs(5), exchange).await;
        a_task.abort();
        b_task.abort();
        result.unwrap();
    }
}
