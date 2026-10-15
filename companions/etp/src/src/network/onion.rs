//! Opt-in onion forwarding over authenticated, approved neighbour links.
//! Each relay opens one layer. Only the exit reassembles opaque application records.
use super::node::{NodeConfig, PacketTransport};
use crate::crypto::onion::{OnionConfig, OnionCrypto, PaddingStrategy};
use anyhow::{ensure, Result};
use bincode::Options;
use parking_lot::Mutex;
use rand::RngCore;
use serde::{Deserialize, Serialize};
use std::{
    collections::{HashMap, HashSet},
    net::SocketAddr,
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::sync::mpsc;
use x25519_dalek::{PublicKey, StaticSecret};
use zeroize::Zeroize;
const CHUNK: usize = 1024;
const MAX_RECORD: usize = 65536;
const MAX_PACKET: usize = 4096;
#[derive(Serialize, Deserialize)]
enum Layer {
    Relay {
        next: SocketAddr,
        packet: Vec<u8>,
    },
    Deliver {
        id: [u8; 16],
        index: u16,
        count: u16,
        total: u32,
        digest: [u8; 32],
        chunk: Vec<u8>,
    },
}
struct Assembly {
    started: Instant,
    total: usize,
    digest: [u8; 32],
    chunks: Vec<Option<Vec<u8>>>,
}
#[derive(Default)]
struct State {
    seen: HashMap<[u8; 32], Instant>,
    completed: HashMap<[u8; 16], Instant>,
    assemblies: HashMap<[u8; 16], Assembly>,
}
pub(crate) struct OnionRouter {
    config: Arc<NodeConfig>,
    transport: Arc<dyn PacketTransport>,
    data: mpsc::Sender<(SocketAddr, Vec<u8>)>,
    state: Mutex<State>,
}
impl OnionRouter {
    pub fn new(
        config: Arc<NodeConfig>,
        transport: Arc<dyn PacketTransport>,
        data: mpsc::Sender<(SocketAddr, Vec<u8>)>,
    ) -> Self {
        Self {
            config,
            transport,
            data,
            state: Mutex::new(State::default()),
        }
    }
    fn link_key(&self, peer: SocketAddr) -> Result<[u8; 32]> {
        let public = self
            .config
            .trusted_peers
            .get(&peer)
            .ok_or_else(|| anyhow::anyhow!("unapproved onion neighbour"))?;
        let secret = StaticSecret::from(<[u8; 32]>::try_from(
            self.config.keypair.private.as_slice(),
        )?);
        let shared = secret.diffie_hellman(&PublicKey::from(*public));
        ensure!(shared.was_contributory(), "invalid neighbour key");
        Ok(blake3::derive_key(
            "ETP authenticated onion neighbour v1",
            shared.as_bytes(),
        ))
    }
    fn envelope(&self, peer: SocketAddr, packet: &[u8]) -> Result<Vec<u8>> {
        ensure!(packet.len() <= MAX_PACKET - 48, "onion packet budget");
        let mut out = vec![0; 48];
        rand::rngs::OsRng.fill_bytes(&mut out[..16]);
        out.extend_from_slice(packet);
        let mut key = self.link_key(peer)?;
        let mut mac = blake3::Hasher::new_keyed(&key);
        mac.update(&out[..16]);
        mac.update(packet);
        out[16..48].copy_from_slice(mac.finalize().as_bytes());
        key.zeroize();
        Ok(out)
    }
    pub async fn send(&self, path: Vec<(SocketAddr, Vec<u8>)>, bytes: Vec<u8>) -> Result<()> {
        ensure!(
            (2..=4).contains(&path.len()) && !bytes.is_empty() && bytes.len() <= MAX_RECORD,
            "bounded private route required"
        );
        let mut seen = HashSet::new();
        for (address, key) in &path {
            ensure!(
                seen.insert(*address)
                    && self
                        .config
                        .trusted_peers
                        .get(address)
                        .map(|k| k.as_slice() == key.as_slice())
                        .unwrap_or(false),
                "approved distinct route required"
            );
        }
        let id = rand::random::<[u8; 16]>();
        let digest = *blake3::hash(&bytes).as_bytes();
        let count = bytes.len().div_ceil(CHUNK) as u16;
        let onion_config = OnionConfig {
            padding: PaddingStrategy::BlockAligned(256),
            ..OnionConfig::default()
        };
        for (index, chunk) in bytes.chunks(CHUNK).enumerate() {
            let mut layer = Layer::Deliver {
                id,
                index: index as u16,
                count,
                total: bytes.len() as u32,
                digest,
                chunk: chunk.to_vec(),
            };
            let mut packet = Vec::new();
            for i in (0..path.len()).rev() {
                packet =
                    OnionCrypto::seal(&path[i].1, &bincode::serialize(&layer)?, &onion_config)?;
                if i > 0 {
                    layer = Layer::Relay {
                        next: path[i].0,
                        packet: packet.clone(),
                    };
                }
            }
            let packet = self.envelope(path[0].0, &packet)?;
            self.transport.send_to(&packet, path[0].0).await?;
        }
        Ok(())
    }
    // True means authenticated onion traffic was consumed, including invalid/replayed layers.
    pub async fn receive(&self, packet: &[u8], src: SocketAddr) -> bool {
        if !self.config.enable_onion_relay || !(97..=MAX_PACKET).contains(&packet.len()) {
            return false;
        }
        let Ok(mut key) = self.link_key(src) else {
            return false;
        };
        let mut mac = blake3::Hasher::new_keyed(&key);
        mac.update(&packet[..16]);
        mac.update(&packet[48..]);
        key.zeroize();
        if !constant_time_eq::constant_time_eq(mac.finalize().as_bytes(), &packet[16..48]) {
            return false;
        }
        let fingerprint = *blake3::hash(packet).as_bytes();
        {
            let mut state = self.state.lock();
            state
                .seen
                .retain(|_, t| t.elapsed() < Duration::from_secs(60));
            state
                .completed
                .retain(|_, t| t.elapsed() < Duration::from_secs(60));
            state
                .assemblies
                .retain(|_, a| a.started.elapsed() < Duration::from_secs(30));
            if state.seen.contains_key(&fingerprint) || state.seen.len() >= 8192 {
                return true;
            }
            state.seen.insert(fingerprint, Instant::now());
        }
        let result: Result<()> = async {
            let plain = OnionCrypto::open(&packet[48..], &self.config.keypair.private)?;
            let layer: Layer = bincode::DefaultOptions::new()
                .with_fixint_encoding()
                .with_limit(MAX_PACKET as u64)
                .reject_trailing_bytes()
                .deserialize(&plain)?;
            match layer {
                Layer::Relay { next, packet } => {
                    ensure!(
                        next != src && next != self.transport.local_addr()?,
                        "relay loop"
                    );
                    let envelope = self.envelope(next, &packet)?;
                    self.transport.send_to(&envelope, next).await?;
                }
                Layer::Deliver {
                    id,
                    index,
                    count,
                    total,
                    digest,
                    chunk,
                } => {
                    ensure!(
                        total > 0
                            && total as usize <= MAX_RECORD
                            && count as usize == (total as usize).div_ceil(CHUNK)
                            && index < count,
                        "invalid fragment layout"
                    );
                    let expected = if index + 1 == count {
                        total as usize - index as usize * CHUNK
                    } else {
                        CHUNK
                    };
                    ensure!(chunk.len() == expected, "fragment size");
                    let mut state = self.state.lock();
                    if state.completed.contains_key(&id) {
                        return Ok(());
                    }
                    ensure!(
                        state.assemblies.contains_key(&id) || state.assemblies.len() < 16,
                        "reassembly budget"
                    );
                    let assembly = state.assemblies.entry(id).or_insert_with(|| Assembly {
                        started: Instant::now(),
                        total: total as usize,
                        digest,
                        chunks: vec![None; count as usize],
                    });
                    ensure!(
                        assembly.digest == digest
                            && assembly.total == total as usize
                            && assembly.chunks.len() == count as usize,
                        "conflicting record"
                    );
                    if let Some(existing) = &assembly.chunks[index as usize] {
                        ensure!(*existing == chunk, "conflicting fragment");
                    } else {
                        assembly.chunks[index as usize] = Some(chunk);
                    }
                    if assembly.chunks.iter().all(Option::is_some) {
                        let bytes = assembly
                            .chunks
                            .iter()
                            .flat_map(|v| v.as_ref().unwrap().iter().copied())
                            .collect::<Vec<_>>();
                        ensure!(*blake3::hash(&bytes).as_bytes() == digest, "record digest");
                        // Reserve receiver capacity before marking completion; never await with the lock.
                        self.data.try_send((src, bytes))?;
                        state.assemblies.remove(&id);
                        ensure!(state.completed.len() < 8192, "completion budget");
                        state.completed.insert(id, Instant::now());
                    }
                }
            }
            Ok(())
        }
        .await;
        let _ = result;
        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::crypto::noise::KeyPair;
    #[derive(Debug)]
    struct Capture {
        address: SocketAddr,
        tx: mpsc::Sender<(SocketAddr, Vec<u8>)>,
    }
    #[async_trait::async_trait]
    impl PacketTransport for Capture {
        async fn send_to(&self, bytes: &[u8], target: SocketAddr) -> std::io::Result<usize> {
            self.tx
                .send((target, bytes.to_vec()))
                .await
                .map_err(|_| std::io::Error::from(std::io::ErrorKind::BrokenPipe))?;
            Ok(bytes.len())
        }
        async fn recv_from(&self, _: &mut [u8]) -> std::io::Result<(usize, SocketAddr)> {
            unreachable!()
        }
        fn local_addr(&self) -> std::io::Result<SocketAddr> {
            Ok(self.address)
        }
    }
    #[tokio::test]
    async fn three_hops_hide_content_reassemble_reordered_fragments_and_reject_replays() {
        let keys: Vec<_> = (0..4).map(|_| KeyPair::generate()).collect();
        let addresses: Vec<SocketAddr> = (0..4)
            .map(|i| format!("127.0.0.1:{}", 19000 + i).parse().unwrap())
            .collect();
        let (tx, mut wire) = mpsc::channel(256);
        let mut routers = Vec::new();
        let mut receivers = Vec::new();
        for i in 0..4 {
            let mut config = NodeConfig::default();
            config.keypair = keys[i].clone();
            config.enable_onion_relay = true;
            config.trusted_peers = addresses
                .iter()
                .enumerate()
                .filter(|(j, _)| *j != i)
                .map(|(j, a)| (*a, keys[j].public.as_slice().try_into().unwrap()))
                .collect();
            let (data, rx) = mpsc::channel(4);
            receivers.push(rx);
            routers.push(OnionRouter::new(
                Arc::new(config),
                Arc::new(Capture {
                    address: addresses[i],
                    tx: tx.clone(),
                }),
                data,
            ));
        }
        let bytes = (0..65536).map(|i| (i % 251) as u8).collect::<Vec<_>>();
        let path = (1..4)
            .map(|i| (addresses[i], keys[i].public.clone()))
            .collect();
        routers[0].send(path, bytes.clone()).await.unwrap();
        for hop in 1..4 {
            let mut packets = Vec::new();
            while let Ok((target, packet)) = wire.try_recv() {
                assert_eq!(target, addresses[hop]);
                assert!(packet.len() <= MAX_PACKET);
                assert!(!packet.windows(128).any(|p| p == &bytes[..128]));
                packets.push(packet);
            }
            assert_eq!(packets.len(), 64);
            packets.reverse();
            for packet in packets {
                let mut tampered = packet.clone();
                *tampered.last_mut().unwrap() ^= 1;
                assert!(!routers[hop].receive(&tampered, addresses[hop - 1]).await);
                assert!(routers[hop].receive(&packet, addresses[hop - 1]).await);
                assert!(routers[hop].receive(&packet, addresses[hop - 1]).await);
            }
        }
        assert_eq!(receivers[3].try_recv().unwrap().1, bytes);
        assert!(receivers.iter_mut().all(|rx| rx.try_recv().is_err()));
        assert!(routers[3].state.lock().assemblies.is_empty());
        assert!(routers[0]
            .send(vec![(addresses[1], keys[1].public.clone()); 2], vec![1])
            .await
            .is_err());
    }
}
