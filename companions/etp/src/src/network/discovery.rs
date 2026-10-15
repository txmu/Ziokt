// etp-core/src/network/discovery.rs

use crate::common::NodeInfo;
use crate::NodeID;
use rand::seq::SliceRandom;
use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::{Arc, RwLock};
use std::time::{Duration, Instant};

/// 路由表：存储已知节点
#[derive(Debug, Clone)]
pub struct RoutingTable {
    // NodeID -> NodeInfo
    peers: Arc<RwLock<HashMap<NodeID, NodeInfo>>>,
    seen: Arc<RwLock<HashMap<NodeID, Instant>>>,
}

impl RoutingTable {
    pub fn new() -> Self {
        Self {
            peers: Arc::new(RwLock::new(HashMap::new())),
            seen: Arc::new(RwLock::new(HashMap::new())),
        }
    }

    /// 添加或更新节点
    pub fn add_node(&self, info: NodeInfo) {
        if info.id == [0; 32]
            || info.addr.port() == 0
            || info.addr.ip().is_unspecified()
            || info.addr.ip().is_multicast()
        {
            return;
        }
        let mut table = self.peers.write().unwrap();
        if table.len() >= 1024 && !table.contains_key(&info.id) {
            return;
        }
        self.seen.write().unwrap().insert(info.id, Instant::now());
        // 实际逻辑中可能需要检查是否更新 (比如 latency 更低)
        table.insert(info.id, info);
    }

    /// 查找节点地址 (Session 6 新增)
    pub fn lookup(&self, id: &NodeID) -> Option<SocketAddr> {
        let table = self.peers.read().unwrap();
        table.get(id).map(|info| info.addr)
    }

    /// 随机获取 N 个节点（用于 Gossip 分享）
    pub fn get_random_peers(&self, n: usize) -> Vec<NodeInfo> {
        let table = self.peers.read().unwrap();
        let mut nodes: Vec<NodeInfo> = table.values().cloned().collect();
        let mut rng = rand::thread_rng();
        nodes.shuffle(&mut rng);
        nodes.into_iter().take(n).collect()
    }

    /// 获取所有已知节点的地址
    pub fn get_all_addresses(&self) -> Vec<SocketAddr> {
        self.peers
            .read()
            .unwrap()
            .values()
            .map(|n| n.addr)
            .collect()
    }
}
impl RoutingTable {
    pub fn find_closest(&self, target: &NodeID, count: usize) -> Vec<NodeInfo> {
        let mut peers: Vec<_> = self.peers.read().unwrap().values().cloned().collect();
        peers.sort_by_key(|peer| {
            let mut distance = [0; 32];
            for i in 0..32 {
                distance[i] = peer.id[i] ^ target[i];
            }
            distance
        });
        peers.truncate(count.min(64));
        peers
    }
    pub fn get_refresh_ids(&self) -> Vec<NodeID> {
        (0..8).map(|_| rand::random()).collect()
    }
    pub fn get_stale_nodes(&self) -> Vec<NodeID> {
        self.peers
            .read()
            .unwrap()
            .keys()
            .take(64)
            .copied()
            .collect()
    }
}
