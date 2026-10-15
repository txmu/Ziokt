// etp-core/src/network/nat.rs

use anyhow::{anyhow, Result};
use governor::clock::DefaultClock;
use governor::state::{InMemoryState, NotKeyed};
use governor::{Quota, RateLimiter};
use igd_next::{search_gateway, SearchOptions};
use log::{debug, error, info, warn};
use std::net::{IpAddr, SocketAddr};
use std::num::NonZeroU32;
use std::sync::Arc;
use std::time::Duration;

/// NAT 穿透管理器
pub struct NatManager {
    /// 速率限制器 (全局 NAT 操作限制，防止 API 滥用)
    rate_limiter: Arc<RateLimiter<NotKeyed, InMemoryState, DefaultClock>>,
    /// 外部地址缓存
    public_addr: Option<SocketAddr>,
}

impl NatManager {
    pub fn new() -> Self {
        // 配置限流：每秒最多 2 次 NAT 操作 (UPnP 请求或重映射)
        let quota = Quota::per_second(NonZeroU32::new(2).unwrap());
        Self {
            rate_limiter: Arc::new(RateLimiter::direct(quota)),
            public_addr: None,
        }
    }

    /// 尝试通过 UPnP 映射端口
    /// local_port: 本地监听的 UDP 端口
    /// lease_duration: 映射有效期 (秒)
    pub fn map_port_upnp(&mut self, local_port: u16, lease_duration: u64) -> Result<SocketAddr> {
        // Anti-Spam Check
        if self.rate_limiter.check().is_err() {
            return Err(anyhow!("NAT rate limit exceeded"));
        }

        info!("Attempting UPnP port mapping for port {}...", local_port);

        let opts = SearchOptions {
            timeout: Some(Duration::from_secs(2)),
            ..Default::default()
        };

        match search_gateway(opts) {
            Ok(gateway) => {
                let route = std::net::UdpSocket::bind("0.0.0.0:0")?;
                route.connect(gateway.addr)?;
                let local_ip = route.local_addr()?.ip();
                let lease =
                    u32::try_from(lease_duration).map_err(|_| anyhow!("UPnP lease overflow"))?;
                if local_port == 0 || lease == 0 {
                    return Err(anyhow!("explicit bounded UPnP mapping required"));
                }
                // 外部端口建议与内部一致，如果不一致网关会分配
                gateway.add_port(
                    igd_next::PortMappingProtocol::UDP,
                    local_port,
                    SocketAddr::new(local_ip, local_port),
                    lease,
                    "ETP Node",
                )?;

                let external_ip = gateway.get_external_ip()?;
                let public_socket = SocketAddr::new(external_ip, local_port);

                info!("UPnP Success: External address is {}", public_socket);
                self.public_addr = Some(public_socket);
                Ok(public_socket)
            }
            Err(e) => {
                warn!("UPnP failed: {}", e);
                Err(anyhow!("UPnP failed: {}", e))
            }
        }
    }

    /// 生成 STUN 探测包 (Hole Punching Payload)
    /// 生产级应包含 Cookie 和 Transaction ID
    pub fn generate_stun_probe(&self) -> Vec<u8> {
        // 简单实现：[Magic(4)][TxID(12)]
        let mut buf = Vec::with_capacity(16);
        buf.extend_from_slice(&[0xDE, 0xAD, 0xBE, 0xEF]); // Magic Cookie
        let tx_id: [u8; 12] = rand::random();
        buf.extend_from_slice(&tx_id);
        buf
    }

    /// 验证接收到的探测包是否合法 (Anti-Spam: Drop garbage)
    pub fn validate_stun_probe(data: &[u8]) -> bool {
        if data.len() < 16 {
            return false;
        }
        if &data[0..4] != &[0xDE, 0xAD, 0xBE, 0xEF] {
            return false;
        }
        true
    }
}
