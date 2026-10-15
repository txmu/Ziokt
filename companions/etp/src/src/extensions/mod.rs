// etp-core/src/extensions/mod.rs

// 1. 基础扩展模块
pub mod adapter;
pub mod bus;
pub mod config;
pub mod state;

// 2. 条件编译模块 (ENS 网关)
#[cfg(feature = "ens-gateway")]
pub mod ens;

// 3. 核心身份与命名系统
pub mod identity;
pub mod kns;

// 4. [新增] KNS-TNS 适配器
// 只有当启用了持久化存储(Sled)时，TnsFlavor 才可用，该适配器才有意义
#[cfg(feature = "persistence")]
pub mod kns_adapter;

// 5. 传输层构建套件
pub mod transport_kit;

// 6. 其它扩展内容
pub mod huoban;
pub mod pool_memory;

pub mod ufs_adapter;

// [New] TC-16 Virtual Machine & Smart Contract Engine
#[cfg(feature = "tc16-tcc")]
pub mod tc16_tcc;

// 新增 DSL 运行时模块
#[cfg(feature = "dsl-runtime")]
pub mod dsl;

// ============================================================================
//  统一导出 (Re-exports)
// ============================================================================

// --- Adapter (流适配器) ---
pub use adapter::{ProtocolStream, StreamAdapter};

// --- Bus (事件总线) ---
pub use bus::{EventBus, SystemEvent};

// --- State (共享状态) ---
pub use state::SharedState;

// --- Config (动态配置) ---
pub use config::{ConfigManager, ConfigWatcher, DynamicConfig};

// --- ENS (以太坊域名服务网关) ---
#[cfg(feature = "ens-gateway")]
pub use ens::gateway::{run_server as run_ens_gateway, EnsGatewayConfig};

// --- Identity (多态身份系统) ---
pub use identity::{
    // 十种具体身份实现
    AnchorIdentity, // 基石
    AnonymityLevel,

    AvatarIdentity,    // 化身
    ChameleonIdentity, // 拟态 (隐写)
    CitizenIdentity,   // 公民 (PoW)
    EtpIdentity,
    FortressIdentity, // 堡垒 (Post-Quantum)
    GhostIdentity,    // 幽灵 (一次性)
    HiveIdentity,     // 蜂群 (多签/MPC)
    // 核心接口与枚举
    IdentityManager,
    IdentityType,
    ProxyIdentity,   // 代理 (Delegated)
    TokenIdentity,   // 盲视 (Blind Token)
    WhisperIdentity, // 否认 (HMAC)
};

// --- KNS (内核命名系统) ---
pub use kns::{
    AccessControl,

    ExternalResolver,
    // 核心组件
    KnsKernel,
    KnsPath,
    KnsRecord,

    // 类型与接口
    RecordKind,
    ResolutionPriority,
    // 域与权限
    SecurityDomain,
};

// --- KNS Adapter ---
#[cfg(feature = "persistence")]
pub use kns_adapter::TnsBackedKnsResolver;

// --- UFS Adapter ---
pub use ufs_adapter::{DirectoryListing, FileMetadata, UltraFileServerFlavor};

// --- Transport Kit (自定义传输层构建器) ---
pub use transport_kit::{
    AddressRegistry,
    LogLayer,
    SimpleTcpLink,
    // 内置组件
    TcpLink,
    // 核心构建器
    TransportKit,
    TransportKitBuilder,
    TransportLayer,
    // 接口
    VirtualLink,
    VirtualStream,
    XorLayer,
};

pub use huoban::{HuoBanBoard, User as HuobanUser};
pub use pool_memory::{get_global_pool, SharedMemoryPool};

#[cfg(feature = "tc16-tcc")]
pub use tc16_tcc::{Tc16Cpu, Tc16Flavor}; // TccCompiler is internal helper
