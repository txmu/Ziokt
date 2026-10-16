// etp-core/src/anonymity/facade.rs

use anyhow::{anyhow, Context, Result};
use log::{error, info, warn};
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;
use tokio::sync::{mpsc, RwLock};

// Core
use crate::network::node::UdpTransport; // 需要手动构建 UDP Transport
use crate::network::node::{EtpEngine, EtpHandle, NodeConfig};
use crate::plugin::PluginRegistry;
use crate::transport::injection::AclManager;

// Anonymity Module
use super::{
    adapter::{HybridTransport, TorDynamicTransport},
    canary::CanaryInterceptor,
    isolation::{IsolationManager, SecurityLevel},
    DeepProfile,
};

/// 门面当前状态
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FacadeState {
    Initializing,
    Running,
    EmergencyLockdown,
}

/// 深度匿名门面 (The Facade)
pub struct DeepAnonymityFacade {
    /// 动态配置
    profile: RwLock<DeepProfile>,

    /// 状态标志
    state: RwLock<FacadeState>,

    /// 隔离管理器 (Dom0)
    isolation_mgr: Arc<IsolationManager>,

    /// 全局 ACL (防火墙联动)
    global_acl: Arc<AclManager>,

    /// Retain onion mappings for both strict external and explicitly mixed modes.
    tor_transport: RwLock<Option<Arc<TorDynamicTransport>>>,
}

impl DeepAnonymityFacade {
    pub fn new(profile: DeepProfile, storage_base: PathBuf) -> Self {
        Self {
            profile: RwLock::new(profile),
            state: RwLock::new(FacadeState::Initializing),
            isolation_mgr: Arc::new(IsolationManager::new(storage_base)),
            global_acl: Arc::new(AclManager::new(true)),
            tor_transport: RwLock::new(None),
        }
    }

    // ========================================================================
    //  主节点启动逻辑
    // ========================================================================

    pub async fn spawn_main_node(
        &self,
        config: NodeConfig,
        mut registry: PluginRegistry,
    ) -> Result<(EtpHandle, mpsc::Receiver<(SocketAddr, Vec<u8>)>)> {
        let mut state = self.state.write().await;
        if *state == FacadeState::EmergencyLockdown {
            return Err(anyhow!("Cannot spawn node: System in LOCKDOWN mode"));
        }

        let profile = self.profile.read().await.clone();

        // 1. 注入主动防御 (Canary)
        if profile.enable_canary_traps {
            let canary = Arc::new(CanaryInterceptor::new(self.global_acl.clone(), None));
            registry.register_default_interceptor(canary);
            info!("Facade: Canary defense activated.");
        }

        // 2. 配置传输层
        let (engine, handle, rx) = if profile.enable_external_anonymity {
            // --- Darknet / Hybrid Mode ---
            let proxy = profile
                .proxy_addr
                .ok_or_else(|| anyhow!("Anonymity enabled but no proxy address configured"))?;

            // 创建 Tor 传输层
            let tor_trans =
                TorDynamicTransport::new(&proxy).context("Failed to initialize Tor Transport")?;

            *self.tor_transport.write().await = Some(tor_trans.clone());
            if profile.allow_clearnet_fallback {
                warn!("Facade: explicit mixed mode permits clearnet UDP for unmapped peers");

                // 初始化 UDP
                let udp_sock = tokio::net::UdpSocket::bind(&config.bind_addr).await?;
                // 优化 UDP buffer
                let udp_trans = Arc::new(UdpTransport(Arc::new(udp_sock)));

                // 组合
                let hybrid = HybridTransport::new(udp_trans, tor_trans.clone());

                // 注入 Engine
                EtpEngine::new_with_transport(config, Arc::new(registry), hybrid).await?
            } else {
                // Strict external anonymity: no UDP socket is created.
                EtpEngine::new_with_transport(config, Arc::new(registry), tor_trans).await?
            }
        } else {
            // --- Clearnet Mode ---
            EtpEngine::new(config, Arc::new(registry)).await?
        };

        *state = FacadeState::Running;

        // 3. 后台运行
        tokio::spawn(async move {
            if let Err(e) = engine.run().await {
                error!("Main Node Engine stopped: {}", e);
            }
        });

        Ok((handle, rx))
    }

    // ========================================================================
    //  动态功能 API
    // ========================================================================

    /// 注册一个 Onion 地址，并获取可用于 send_data 的虚拟 SocketAddr
    /// 仅在 Hybrid 或 Darknet 模式下有效
    pub async fn register_onion_peer(&self, onion_domain: &str) -> Result<SocketAddr> {
        let guard = self.tor_transport.read().await;
        if let Some(trans) = guard.as_ref() {
            let addr = trans.map_domain(onion_domain);
            info!("Facade: Mapped {} -> {}", onion_domain, addr);
            Ok(addr)
        } else {
            Err(anyhow!(
                "Transport does not support onion mapping (Check if Anonymity is enabled)"
            ))
        }
    }

    /// 紧急关停 (Panic Button)
    /// level 0: 停止网络
    /// level 1: 停止 + 内存清理
    /// level 2: 停止 + 内存清理 + 磁盘销毁
    pub async fn emergency_shutdown(&self, level: u8) {
        warn!("!!! EMERGENCY SHUTDOWN TRIGGERED (Level {}) !!!", level);

        let mut state = self.state.write().await;
        *state = FacadeState::EmergencyLockdown;

        // 1. 封锁网络：通过 ACL 禁止所有新握手
        // 实际上 ACL 需要一个 clear_all_whitelist 方法
        // 这里演示逻辑：
        // self.global_acl.clear_whitelist();
        // self.global_acl.enable_strict_mode();

        // 2. 销毁隔离域
        if level >= 2 {
            self.isolation_mgr.panic_nuke(SecurityLevel::Vault).await;
            self.isolation_mgr.panic_nuke(SecurityLevel::Standard).await;
            self.isolation_mgr
                .panic_nuke(SecurityLevel::Untrusted)
                .await;
        }

        // 3. 进程退出 (Optional)
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::network::node::PacketTransport;
    use tokio::net::{TcpListener, UdpSocket};
    use tokio::time::{timeout, Duration};

    #[tokio::test]
    async fn strict_external_mode_never_binds_or_sends_clearnet() {
        let udp = UdpSocket::bind("127.0.0.1:0").await.unwrap();
        let proxy = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let profile: DeepProfile = serde_json::from_value(serde_json::json!({
            "enable_external_anonymity": true,
            "proxy_addr": proxy.local_addr().unwrap().to_string(),
            "enable_domain_isolation": false,
            "enable_canary_traps": false
        }))
        .unwrap();
        assert!(!profile.allow_clearnet_fallback);
        let facade = DeepAnonymityFacade::new(profile, std::env::temp_dir());
        let config = NodeConfig {
            bind_addr: udp.local_addr().unwrap().to_string(),
            ..NodeConfig::default()
        };
        // This port is already occupied: any implicit UDP bind would fail.
        let (_handle, _inbox) = facade
            .spawn_main_node(config, PluginRegistry::new())
            .await
            .unwrap();
        let virtual_peer = facade
            .register_onion_peer(&format!("{}.onion:443", "a".repeat(56)))
            .await
            .unwrap();
        let transport = facade.tor_transport.read().await.clone().unwrap();
        assert!(transport
            .resolve_ip(&virtual_peer)
            .unwrap()
            .0
            .ends_with(".onion"));
        assert!(transport
            .send_to(b"must not leak", udp.local_addr().unwrap())
            .await
            .is_err());
        assert!(
            timeout(Duration::from_millis(50), udp.recv_from(&mut [0u8; 64]))
                .await
                .is_err()
        );
        assert!(timeout(Duration::from_millis(50), proxy.accept())
            .await
            .is_err());
    }

    #[tokio::test]
    async fn mixed_transport_requires_explicit_permission() {
        let occupied = UdpSocket::bind("127.0.0.1:0").await.unwrap();
        let profile = DeepProfile {
            enable_external_anonymity: true,
            allow_clearnet_fallback: true,
            proxy_addr: Some("127.0.0.1:9050".into()),
            enable_canary_traps: false,
            ..DeepProfile::default()
        };
        let facade = DeepAnonymityFacade::new(profile, std::env::temp_dir());
        let config = NodeConfig {
            bind_addr: occupied.local_addr().unwrap().to_string(),
            ..NodeConfig::default()
        };
        assert!(facade
            .spawn_main_node(config, PluginRegistry::new())
            .await
            .is_err());
    }
}
