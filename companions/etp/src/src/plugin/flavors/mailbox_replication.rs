//! Optional bounded durable replication for Mailbox v2.
//! Only opaque recipient tags, ciphertext, expiry and tombstones cross peers.
//! Node IDs/peer endpoints are operator-authorized; recipient keys never leave v2 proofs.
use anyhow::{ensure, Result};
use ed25519_dalek::{Signature, Signer, SigningKey, VerifyingKey};
use std::{collections::BTreeMap, net::SocketAddr};
use tokio::sync::mpsc;

pub const REPLICA_PUT: u8 = 7;
pub const REPLICA_ACK: u8 = 8;
pub const REPLICA_SYNC: u8 = 9;
pub const REPLICA_PAGE: u8 = 10;
const DOMAIN: &[u8] = b"ETP_MAILBOX_REPLICATION_V1\0";
const MAX_LOG: usize = 16384;
#[derive(Clone)]
pub struct ReplicaConfig {
    /// Total durable copies INCLUDING the local node: 1, 3 or 5.
    pub copies: usize,
    pub key: [u8; 32],
    /// Exactly copies-1 authorized peers, identified by signing public key.
    pub peers: BTreeMap<[u8; 32], SocketAddr>,
}
pub struct Replicas {
    config: ReplicaConfig,
    log: sled::Tree,
    seen: sled::Tree,
    tombstones: sled::Tree,
    receipts: sled::Tree,
    latest: sled::Tree,
    cursors: sled::Tree,
    db: sled::Db,
    tx: mpsc::Sender<(SocketAddr, Vec<u8>)>,
}
fn signature(key: &SigningKey, body: &[u8]) -> Vec<u8> {
    let mut scoped = DOMAIN.to_vec();
    scoped.extend_from_slice(body);
    key.sign(&scoped).to_bytes().to_vec()
}
impl Replicas {
    pub fn new(
        db: &sled::Db,
        config: ReplicaConfig,
        tx: mpsc::Sender<(SocketAddr, Vec<u8>)>,
    ) -> Result<Self> {
        ensure!(
            [1, 3, 5].contains(&config.copies) && config.peers.len() + 1 == config.copies,
            "replica mode must match explicitly authorized membership"
        );
        let public = SigningKey::from_bytes(&config.key)
            .verifying_key()
            .to_bytes();
        ensure!(
            !config.peers.contains_key(&public),
            "local identity cannot count as a remote replica"
        );
        let unique: std::collections::BTreeSet<_> = config.peers.values().collect();
        ensure!(
            unique.len() == config.peers.len(),
            "independent replica endpoints required"
        );
        Ok(Self {
            config,
            log: db.open_tree("mail-replica-log-v1")?,
            seen: db.open_tree("mail-replica-seen-v1")?,
            tombstones: db.open_tree("mail-replica-tombstones-v1")?,
            receipts: db.open_tree("mail-replica-receipts-v1")?,
            latest: db.open_tree("mail-replica-latest-v1")?,
            cursors: db.open_tree("mail-replica-cursors-v1")?,
            db: db.clone(),
            tx,
        })
    }
    fn signed(&self, op: u8, body: &[u8]) -> Vec<u8> {
        let key = SigningKey::from_bytes(&self.config.key);
        let mut frame = vec![2, op];
        frame.extend_from_slice(key.verifying_key().as_bytes());
        frame.extend_from_slice(body);
        let sig = signature(&key, &frame);
        frame.extend_from_slice(&sig);
        frame
    }
    fn verify<'a>(&self, frame: &'a [u8], source: SocketAddr) -> Result<([u8; 32], &'a [u8])> {
        ensure!(
            frame.len() >= 98 && frame.len() <= 8800,
            "replica frame budget"
        );
        let public: [u8; 32] = frame[2..34].try_into()?;
        ensure!(
            (self.config.peers.contains_key(&public)
                || public
                    == SigningKey::from_bytes(&self.config.key)
                        .verifying_key()
                        .to_bytes())
                && self.config.peers.values().any(|addr| *addr == source),
            "replica not authorized at this endpoint"
        );
        let end = frame.len() - 64;
        let mut body = DOMAIN.to_vec();
        body.extend_from_slice(&frame[..end]);
        VerifyingKey::from_bytes(&public)?
            .verify_strict(&body, &Signature::from_bytes(frame[end..].try_into()?))?;
        Ok((public, &frame[34..end]))
    }
    fn remember(&self, frame: &[u8]) -> Result<[u8; 32]> {
        let hash = *blake3::hash(frame).as_bytes();
        if !self.seen.contains_key(hash)? {
            ensure!(
                self.log.len() < MAX_LOG,
                "replication history quota; operator checkpoint/epoch migration required"
            );
            let seq = self
                .db
                .generate_id()?
                .checked_add(1)
                .ok_or_else(|| anyhow::anyhow!("sequence exhausted"))?;
            self.log.insert(seq.to_be_bytes(), frame)?;
            self.seen.insert(hash, &seq.to_be_bytes())?;
        };
        Ok(hash)
    }
    /// Journal BEFORE modifying the mailbox. Recovery reapplies this durable intent.
    pub fn journal(&self, key: &[u8], value: Option<&[u8]>, expires: u64) -> Result<[u8; 32]> {
        ensure!(
            key.len() == 64 && value.map_or(true, |v| v.len() <= 8192),
            "replica mutation budget"
        );
        ensure!(
            !self.tombstones.contains_key(key)? || value.is_none(),
            "deleted identity cannot be redeposited"
        );
        let mut body = key.to_vec();
        body.push(u8::from(value.is_none()));
        body.extend_from_slice(&expires.to_be_bytes());
        body.extend_from_slice(value.unwrap_or(&[]));
        let frame = self.signed(REPLICA_PUT, &body);
        let hash = self.remember(&frame)?;
        if value.is_none() {
            self.tombstones.insert(key, &[])?;
        }
        self.latest.insert(key, &hash)?;
        self.db.flush()?;
        self.broadcast(&frame);
        Ok(hash)
    }
    fn broadcast(&self, frame: &[u8]) {
        let hash = blake3::hash(frame);
        for (peer, addr) in &self.config.peers {
            let mut receipt = hash.as_bytes().to_vec();
            receipt.extend_from_slice(peer);
            if self.receipts.contains_key(receipt).unwrap_or(false) {
                continue;
            }
            let _ = self.tx.try_send((*addr, frame.to_vec()));
        }
    }
    pub fn deleted(&self, key: &[u8]) -> Result<bool> {
        Ok(self.tombstones.contains_key(key)?)
    }
    pub fn status(&self, key: &[u8]) -> Result<(usize, usize)> {
        let hash = self
            .latest
            .get(key)?
            .ok_or_else(|| anyhow::anyhow!("no replicated record"))?;
        let mut copies = 1;
        for peer in self.config.peers.keys() {
            let mut id = hash.to_vec();
            id.extend_from_slice(peer);
            if self.receipts.contains_key(id)? {
                copies += 1;
            }
        }
        Ok((copies, self.config.copies))
    }
    fn apply(&self, frame: &[u8], messages: &sled::Tree, now: u64) -> Result<()> {
        ensure!(frame.len() >= 171, "mutation length");
        let end = frame.len() - 64;
        let body = &frame[34..end];
        ensure!(body.len() >= 73 && body[64] <= 1, "mutation body");
        let key = &body[..64];
        let tombstone = body[64] == 1;
        if !tombstone {
            ensure!(
                key[32..] == *blake3::hash(&body[73..]).as_bytes(),
                "ciphertext identity mismatch"
            );
        }
        let expires = u64::from_be_bytes(body[65..73].try_into()?);
        ensure!(body.len() <= 73 + 8192, "ciphertext budget");
        if tombstone {
            ensure!(body.len() == 73, "tombstone body");
            self.tombstones.insert(key, &[])?;
            messages.remove(key)?;
        } else if expires > now && !self.tombstones.contains_key(key)? {
            ensure!(
                body.len() > 73 && expires <= now.saturating_add(86400 + 30),
                "expiry or payload"
            );
            if !messages.contains_key(key)? {
                ensure!(
                    messages.len() < 4096 && messages.scan_prefix(&key[..32]).count() < 64,
                    "replica storage quota"
                );
            }
            let mut value = expires.saturating_sub(86400).to_be_bytes().to_vec();
            value.extend_from_slice(&body[73..]);
            messages.insert(key, value)?;
        }
        if tombstone || !self.tombstones.contains_key(key)? {
            let hash = *blake3::hash(frame).as_bytes();
            self.latest.insert(key, &hash)?;
        }
        Ok(())
    }
    pub fn recover(&self, messages: &sled::Tree, now: u64) -> Result<()> {
        for item in self.log.iter() {
            let (_, frame) = item?;
            self.apply(&frame, messages, now)?;
        }
        for item in self.tombstones.iter() {
            let (key, _) = item?;
            messages.remove(key)?;
        }
        self.db.flush()?;
        Ok(())
    }
    /// Retry durable log records and request bounded anti-entropy batches.
    pub fn reconcile(&self) -> Result<()> {
        for item in self.log.iter().rev().take(32) {
            let (_, frame) = item?;
            self.broadcast(&frame);
        }
        for (peer, addr) in &self.config.peers {
            let cursor = self
                .cursors
                .get(peer)?
                .map(|v| u64::from_be_bytes(v.as_ref().try_into().unwrap_or([0; 8])))
                .unwrap_or(0);
            let request = self.signed(REPLICA_SYNC, &cursor.to_be_bytes());
            let _ = self.tx.try_send((*addr, request));
        }
        Ok(())
    }
    pub fn receive(
        &self,
        frame: &[u8],
        source: SocketAddr,
        messages: &sled::Tree,
        now: u64,
    ) -> Result<()> {
        let (public, body) = self.verify(frame, source)?;
        match frame[1] {
            REPLICA_PUT => {
                let hash = *blake3::hash(frame).as_bytes();
                if !self.seen.contains_key(hash)? {
                    self.apply(frame, messages, now)?;
                    self.remember(frame)?;
                    self.db.flush()?;
                }
                let ack = self.signed(REPLICA_ACK, &hash);
                let _ = self.tx.try_send((source, ack));
            }
            REPLICA_ACK => {
                ensure!(
                    body.len() == 32 && self.seen.contains_key(body)?,
                    "ack not bound to journaled mutation"
                );
                let mut key = body.to_vec();
                key.extend_from_slice(&public);
                if !self.receipts.contains_key(&key)? {
                    self.receipts.insert(key, &now.to_be_bytes())?;
                    self.db.flush()?;
                }
            }
            REPLICA_SYNC => {
                ensure!(body.len() == 8, "sync cursor");
                let cursor = u64::from_be_bytes(body.try_into()?);
                for item in self.log.range(cursor.saturating_add(1).to_be_bytes()..) {
                    let (seq, stored) = item?;
                    {
                        let mut page = seq.to_vec();
                        page.extend_from_slice(&stored);
                        let _ = self.tx.try_send((source, self.signed(REPLICA_PAGE, &page)));
                        break;
                    }
                }
            }
            REPLICA_PAGE => {
                ensure!(
                    body.len() > 10 && body[8] == 2 && body[9] == REPLICA_PUT,
                    "sync page requires one mutation"
                );
                let sequence = u64::from_be_bytes(body[..8].try_into()?);
                self.receive(&body[8..], source, messages, now)?;
                let old = self
                    .cursors
                    .get(public)?
                    .map(|v| u64::from_be_bytes(v.as_ref().try_into().unwrap_or([0; 8])))
                    .unwrap_or(0);
                if sequence > old {
                    self.cursors.insert(public, &sequence.to_be_bytes())?;
                    self.db.flush()?;
                }
            }
            _ => anyhow::bail!("unknown replication operation"),
        };
        Ok(())
    }
}
