//! Bounded opaque mailbox. Version 2 binds proofs to operation, nonce and body.
use crate::plugin::{CapabilityProvider, Flavor, FlavorContext};
use anyhow::{anyhow, ensure, Result};
use ed25519_dalek::{Signature, VerifyingKey};
use parking_lot::Mutex;
use std::{
    net::SocketAddr,
    sync::Arc,
    time::{SystemTime, UNIX_EPOCH},
};
use tokio::sync::mpsc;
const VERSION: u8 = 2;
const DEPOSIT: u8 = 1;
const FETCH: u8 = 2;
const FETCH_RESP: u8 = 3;
const DELETE: u8 = 4;
const ACK: u8 = 5;
const REPLICATION_STATUS: u8 = 6;
use super::mailbox_replication::{
    ReplicaConfig, Replicas, REPLICA_ACK, REPLICA_PAGE, REPLICA_PUT, REPLICA_SYNC,
};
const MAX_MESSAGE: usize = 8192;
const MAX_RECORDS: usize = 4096;
const TTL: u64 = 86400;
const AUTH_LEN: usize = 32 + 8 + 16 + 64;

pub struct MailboxFlavor {
    db: sled::Db,
    replicas: Option<Replicas>,
    messages: sled::Tree,
    proofs: sled::Tree,
    mutation: Mutex<()>,
    network_tx: mpsc::Sender<(SocketAddr, Vec<u8>)>,
}
fn now() -> Result<u64> {
    Ok(SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs())
}
impl MailboxFlavor {
    pub fn new(path: &str, network_tx: mpsc::Sender<(SocketAddr, Vec<u8>)>) -> Result<Arc<Self>> {
        Self::new_with_replication(path, network_tx, None)
    }
    /// Existing constructor stays single-node. Replication is an explicit opt-in.
    pub fn new_with_replication(
        path: &str,
        network_tx: mpsc::Sender<(SocketAddr, Vec<u8>)>,
        config: Option<ReplicaConfig>,
    ) -> Result<Arc<Self>> {
        let db = sled::open(path)?;
        let messages = db.open_tree("mail-v2")?;
        let replicas = config
            .map(|config| Replicas::new(&db, config, network_tx.clone()))
            .transpose()?;
        if let Some(replica) = &replicas {
            let time = now()?;
            replica.recover(&messages, time)?;
            for item in messages.iter() {
                let (key, value) = item?;
                if value.len() >= 9 && replica.status(&key).is_err() {
                    let expires = u64::from_be_bytes(value[..8].try_into()?).saturating_add(TTL);
                    if expires > time {
                        replica.journal(&key, Some(&value[8..]), expires)?;
                    }
                }
            }
        }

        Ok(Arc::new(Self {
            messages,
            replicas,
            proofs: db.open_tree("proof-v2")?,
            db,
            mutation: Mutex::new(()),
            network_tx,
        }))
    }
    /// Called by the host's bounded scheduler; no detached unbounded workers.
    pub fn reconcile(&self) -> Result<()> {
        let _guard = self.mutation.lock();
        if let Some(replica) = &self.replicas {
            replica.reconcile()?;
        }
        Ok(())
    }
    fn proof_message(op: u8, header: &[u8], body: &[u8]) -> Vec<u8> {
        let mut message = b"ETP_MAILBOX_V2\0".to_vec();
        message.push(op);
        message.extend_from_slice(header);
        message.extend_from_slice(body);
        message
    }
    /// Typed packet entry for native hosts and real-network CI runners.
    pub fn process_packet(&self, source: SocketAddr, data: &[u8]) -> Result<Vec<u8>> {
        ensure!(data.len() >= 2 && data[0] == VERSION, "mailbox version");
        if matches!(
            data[1],
            REPLICA_PUT | REPLICA_ACK | REPLICA_SYNC | REPLICA_PAGE
        ) {
            let _guard = self.mutation.lock();
            let time = now()?;
            self.cleanup(time)?;
            self.replicas
                .as_ref()
                .ok_or_else(|| anyhow!("replication disabled"))?
                .receive(data, source, &self.messages, time)?;
            Ok(Vec::new())
        } else {
            self.handle(data[1], &data[2..])
        }
    }
    // Must be called with mutation held, so proof consumption and mutation serialize.
    fn verify_auth(&self, op: u8, data: &[u8]) -> Result<[u8; 32]> {
        ensure!(
            data.len() >= AUTH_LEN && data.len() <= 4096,
            "invalid proof size"
        );
        let key: [u8; 32] = data[..32].try_into()?;
        let timestamp = u64::from_be_bytes(data[32..40].try_into()?);
        let time = now()?;
        ensure!(
            timestamp <= time.saturating_add(30) && time <= timestamp.saturating_add(300),
            "expired proof"
        );
        let signature = Signature::from_bytes(data[56..120].try_into()?);
        VerifyingKey::from_bytes(&key)?.verify_strict(
            &Self::proof_message(op, &data[..56], &data[AUTH_LEN..]),
            &signature,
        )?;
        let token = blake3::hash(&data[..56]);
        ensure!(
            !self.proofs.contains_key(token.as_bytes())?,
            "replayed proof"
        );
        ensure!(self.proofs.len() < MAX_RECORDS, "proof budget exhausted");
        self.proofs.insert(
            token.as_bytes(),
            &timestamp.saturating_add(301).to_be_bytes(),
        )?;
        Ok(*blake3::hash(&key).as_bytes())
    }
    fn cleanup(&self, time: u64) -> Result<()> {
        for entry in self.messages.iter() {
            let (key, value) = entry?;
            if value.len() < 8
                || u64::from_be_bytes(value[..8].try_into()?).saturating_add(TTL) < time
            {
                self.messages.remove(key)?;
            }
        }
        for entry in self.proofs.iter() {
            let (key, value) = entry?;
            if value.len() != 8 || u64::from_be_bytes(value[..8].try_into()?) < time {
                self.proofs.remove(key)?;
            }
        }
        Ok(())
    }
    fn handle(&self, op: u8, data: &[u8]) -> Result<Vec<u8>> {
        let _guard = self.mutation.lock();
        let time = now()?;
        self.cleanup(time)?;
        match op {
            DEPOSIT => {
                ensure!(
                    (33..=32 + MAX_MESSAGE).contains(&data.len()),
                    "message budget"
                );
                let owner = &data[..32];
                let mut key = owner.to_vec();
                key.extend_from_slice(blake3::hash(&data[32..]).as_bytes());
                ensure!(
                    !self
                        .db
                        .open_tree("mail-replica-tombstones-v1")?
                        .contains_key(&key)?,
                    "retained deletion marker"
                );
                if let Some(replica) = &self.replicas {
                    ensure!(
                        !replica.deleted(&key)?,
                        "message has a durable deletion marker"
                    );
                }
                if !self.messages.contains_key(&key)? {
                    ensure!(
                        self.messages.len() < MAX_RECORDS
                            && self.messages.scan_prefix(owner).count() < 64,
                        "mailbox quota"
                    );
                    let mut value = time.to_be_bytes().to_vec();
                    value.extend_from_slice(&data[32..]);
                    if let Some(replica) = &self.replicas {
                        replica.journal(&key, Some(&data[32..]), time.saturating_add(TTL))?;
                    }
                    self.messages.insert(&key, value)?;
                }
                self.db.flush()?;
                if let Some(replica) = &self.replicas {
                    replica.reconcile()?;
                    let (copies, required) = replica.status(&key)?;
                    return Ok(vec![
                        VERSION,
                        ACK,
                        u8::from(copies < required),
                        copies as u8,
                        required as u8,
                    ]);
                }
                Ok(vec![VERSION, ACK, 0])
            }
            FETCH => {
                ensure!(data.len() == AUTH_LEN, "unexpected fetch body");
                let owner = self.verify_auth(op, data)?;
                let mut response = vec![VERSION, FETCH_RESP, 0];
                for entry in self.messages.scan_prefix(owner).take(4) {
                    let (key, value) = entry?;
                    if let Some(replica) = &self.replicas {
                        if replica.deleted(&key)? {
                            continue;
                        }
                    }

                    response.push(key.len() as u8);
                    response.extend_from_slice(&key);
                    response.extend_from_slice(&((value.len() - 8) as u32).to_be_bytes());
                    response.extend_from_slice(&value[8..]);
                    response[2] += 1;
                }
                self.db.flush()?;
                Ok(response)
            }
            DELETE => {
                ensure!(
                    data.len() >= AUTH_LEN && (data.len() - AUTH_LEN) % 64 == 0,
                    "invalid deletion body"
                );
                // Validate all ownership before consuming the proof or deleting anything.
                let owner = *blake3::hash(&data[..32]).as_bytes();
                ensure!(
                    data[AUTH_LEN..]
                        .chunks_exact(64)
                        .all(|key| key[..32] == owner),
                    "foreign message key"
                );
                self.verify_auth(op, data)?;
                let mut batch = sled::Batch::default();
                for key in data[AUTH_LEN..].chunks_exact(64) {
                    if let Some(replica) = &self.replicas {
                        replica.journal(key, None, time.saturating_add(TTL))?;
                    }
                    batch.remove(key);
                }
                self.messages.apply_batch(batch)?;
                self.db.flush()?;
                if let Some(replica) = &self.replicas {
                    replica.reconcile()?;
                    let mut counts = (1usize, 1usize);
                    for key in data[AUTH_LEN..].chunks_exact(64) {
                        let current = replica.status(key)?;
                        if counts.1 == 1 || current.0 < counts.0 {
                            counts = current;
                        }
                    }
                    return Ok(vec![
                        VERSION,
                        ACK,
                        u8::from(counts.0 < counts.1),
                        counts.0 as u8,
                        counts.1 as u8,
                    ]);
                }
                Ok(vec![VERSION, ACK, 0])
            }
            REPLICATION_STATUS => {
                ensure!(
                    data.len() == AUTH_LEN + 64,
                    "status requires exact message key"
                );
                let owner = self.verify_auth(op, data)?;
                let key = &data[AUTH_LEN..];
                ensure!(key[..32] == owner, "foreign status key");
                self.db.flush()?;
                if let Some(replica) = &self.replicas {
                    let (copies, required) = replica.status(key)?;
                    Ok(vec![
                        VERSION,
                        ACK,
                        u8::from(copies < required),
                        copies as u8,
                        required as u8,
                    ])
                } else {
                    ensure!(self.messages.contains_key(key)?, "message unavailable");
                    Ok(vec![VERSION, ACK, 0, 1, 1])
                }
            }
            _ => Err(anyhow!("unknown mailbox operation")),
        }
    }
}
impl CapabilityProvider for MailboxFlavor {
    fn capability_id(&self) -> String {
        "etp.flavor.mailbox.v2".into()
    }
}
impl Flavor for MailboxFlavor {
    fn on_stream_data(&self, ctx: FlavorContext, data: &[u8]) -> bool {
        if data.len() >= 2
            && data[0] == VERSION
            && matches!(
                data[1],
                REPLICA_PUT | REPLICA_ACK | REPLICA_SYNC | REPLICA_PAGE
            )
        {
            if let Some(replica) = &self.replicas {
                let _guard = self.mutation.lock();
                if let Ok(time) = now() {
                    let _ = replica.receive(data, ctx.src_addr, &self.messages, time);
                }
            }
            return true;
        }
        if data.len() < 2
            || data[0] != VERSION
            || !matches!(data[1], DEPOSIT | FETCH | DELETE | REPLICATION_STATUS)
        {
            return false;
        }
        // No unbounded task spawning when a consumer stops reading.
        if let Ok(response) = self.handle(data[1], &data[2..]) {
            let _ = self.network_tx.try_send((ctx.src_addr, response));
        }
        true
    }
    fn on_connection_open(&self, _: SocketAddr) {
        let _ = self.reconcile();
    }
    fn on_connection_close(&self, _: SocketAddr) {}
}
impl std::fmt::Debug for MailboxFlavor {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("MailboxFlavor").finish_non_exhaustive()
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use ed25519_dalek::{Signer, SigningKey};
    fn proof(key: &SigningKey, op: u8, body: &[u8]) -> Vec<u8> {
        let mut header = key.verifying_key().as_bytes().to_vec();
        header.extend_from_slice(&now().unwrap().to_be_bytes());
        header.extend_from_slice(&rand::random::<[u8; 16]>());
        let signature = key.sign(&MailboxFlavor::proof_message(op, &header, body));
        header.extend_from_slice(&signature.to_bytes());
        header.extend_from_slice(body);
        header
    }
    #[test]
    fn signed_operations_are_bound_replay_safe_and_deposits_idempotent() {
        let path = std::env::temp_dir().join(format!("etp-mail-{}", rand::random::<u64>()));
        let (tx, _) = mpsc::channel(4);
        let mailbox = MailboxFlavor::new(path.to_str().unwrap(), tx).unwrap();
        let key = SigningKey::from_bytes(&[42; 32]);
        let mut deposit = blake3::hash(key.verifying_key().as_bytes())
            .as_bytes()
            .to_vec();
        deposit.extend_from_slice(b"opaque cipher");
        mailbox.handle(DEPOSIT, &deposit).unwrap();
        mailbox.handle(DEPOSIT, &deposit).unwrap();
        assert_eq!(mailbox.messages.len(), 1);
        let request = proof(&key, FETCH, &[]);
        assert!(mailbox.handle(DELETE, &request).is_err());
        assert_eq!(mailbox.handle(FETCH, &request).unwrap()[2], 1);
        assert!(mailbox.handle(FETCH, &request).is_err());
        let stored_key = mailbox.messages.iter().next().unwrap().unwrap().0;
        let mut delete = proof(&key, DELETE, &stored_key);
        delete[AUTH_LEN + 40] ^= 1;
        assert!(mailbox.handle(DELETE, &delete).is_err());
        mailbox
            .handle(DELETE, &proof(&key, DELETE, &stored_key))
            .unwrap();
        assert!(mailbox.messages.is_empty());
        assert!(mailbox.handle(DEPOSIT, &vec![0; MAX_MESSAGE + 33]).is_err());
        drop(mailbox);
        std::fs::remove_dir_all(path).unwrap();
    }
}
