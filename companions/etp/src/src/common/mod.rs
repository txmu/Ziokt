use serde::{Serialize, Deserialize};
use std::net::SocketAddr;
use crate::NodeID;

/// 节点基本信息
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct NodeInfo {
    pub id: NodeID,
    pub addr: SocketAddr,
    pub latency_ms: u16,
    // 信誉分不传输，仅本地存储，所以这里不含NRS
}

impl NodeInfo {
    pub fn new(id: NodeID, addr: SocketAddr) -> Self {
        Self {
            id,
            addr,
            latency_ms: 0,
        }
    }
}

/// DHT 离线存储请求 (通用结构体)
/// 用于 Flavor 通知 Engine 将数据推送到 DHT
#[derive(Debug, Clone)]
pub struct DhtStoreRequest {
    pub key: NodeID,
    pub value: Vec<u8>,
    pub ttl_seconds: u32,
}
/// Bounded native deserialization; retain the wire codec's legacy little-endian fixint encoding.
pub fn safe_deserialize<T: serde::de::DeserializeOwned>(bytes: &[u8]) -> Result<T, bincode::Error> {
    use bincode::Options;
    if bytes.len() > 1024 * 1024 { return Err(Box::new(bincode::ErrorKind::SizeLimit)); }
    bincode::DefaultOptions::new().with_fixint_encoding().with_limit(1024 * 1024).allow_trailing_bytes().deserialize(bytes)
}
