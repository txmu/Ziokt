//! CI/native opt-in mailbox host with real bounded UDP exchange and JSONL control.
//! Ciphertext must already be encrypted by the caller. Bind is loopback only.
use anyhow::{ensure, Result};
use base64::{engine::general_purpose::STANDARD, Engine};
use ed25519_dalek::{Signer, SigningKey};
use etp_core::plugin::flavors::{mailbox::MailboxFlavor, mailbox_replication::ReplicaConfig};
use serde::Deserialize;
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    io::{self, BufRead, Read, Write},
    net::SocketAddr,
    sync::Arc,
    time::{SystemTime, UNIX_EPOCH},
};
use tokio::sync::mpsc;
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    database: String,
    bind: SocketAddr,
    copies: usize,
    key: String,
    peers: BTreeMap<String, SocketAddr>,
}
fn key(value: &str) -> Result<[u8; 32]> {
    Ok(hex::decode(value)?
        .try_into()
        .map_err(|_| anyhow::anyhow!("key length"))?)
}
fn proof(op: u8, body: &[u8]) -> Vec<u8> {
    let key = SigningKey::from_bytes(&[77; 32]);
    let mut header = key.verifying_key().to_bytes().to_vec();
    header.extend_from_slice(
        &SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_secs()
            .to_be_bytes(),
    );
    header.extend_from_slice(&rand::random::<[u8; 16]>());
    let mut message = b"ETP_MAILBOX_V2\0".to_vec();
    message.push(op);
    message.extend_from_slice(&header);
    message.extend_from_slice(body);
    header.extend_from_slice(&key.sign(&message).to_bytes());
    header.extend_from_slice(body);
    header
}
#[tokio::main(worker_threads = 2)]
async fn main() -> Result<()> {
    let path = std::env::args()
        .nth(1)
        .ok_or_else(|| anyhow::anyhow!("config required"))?;
    let mut raw = Vec::new();
    std::fs::File::open(path)?
        .take(65537)
        .read_to_end(&mut raw)?;
    ensure!(raw.len() <= 65536, "config budget");
    let config: Config = serde_json::from_slice(&raw)?;
    ensure!(config.bind.ip().is_loopback(), "runner binds loopback only");
    let mut peers = BTreeMap::new();
    for (public, address) in config.peers {
        peers.insert(key(&public)?, address);
    }
    let socket = Arc::new(tokio::net::UdpSocket::bind(config.bind).await?);
    let address = socket.local_addr()?;
    let (tx, mut rx) = mpsc::channel(256);
    let mailbox = MailboxFlavor::new_with_replication(
        &config.database,
        tx,
        Some(ReplicaConfig {
            copies: config.copies,
            key: key(&config.key)?,
            peers,
        }),
    )?;
    let sender = socket.clone();
    tokio::spawn(async move {
        while let Some((peer, packet)) = rx.recv().await {
            let _ = sender.send_to(&packet, peer).await;
        }
    });
    let receiver = socket.clone();
    let incoming = mailbox.clone();
    tokio::spawn(async move {
        let mut buffer = vec![0; 9000];
        let mut rejected = 0;
        loop {
            match receiver.recv_from(&mut buffer).await {
                Ok((size, source)) => {
                    if let Err(error) = incoming.process_packet(source, &buffer[..size]) {
                        if rejected < 16 {
                            eprintln!("replica packet rejected: {}", error);
                            rejected += 1;
                        }
                    }
                }
                Err(error) => {
                    // An offline UDP peer may produce asynchronous ICMP errors.
                    // Keep the receiver alive so rejoined peers can reconcile.
                    if rejected < 16 {
                        eprintln!("replica socket transient: {:?}", error.kind());
                        rejected += 1;
                    }
                    tokio::time::sleep(std::time::Duration::from_millis(100)).await;
                }
            }
        }
    });
    let reconcile = mailbox.clone();
    tokio::spawn(async move {
        let mut ticks = tokio::time::interval(std::time::Duration::from_secs(1));
        loop {
            ticks.tick().await;
            let _ = reconcile.reconcile();
        }
    });
    println!("{}", json!({"ready":true,"bind":address.to_string()}));
    io::stdout().flush()?;
    let (control_tx, mut control_rx) = mpsc::channel::<String>(16);
    std::thread::spawn(move || {
        let stdin = io::stdin();
        let mut input = stdin.lock();
        loop {
            let mut line = String::new();
            match input.by_ref().take(32769).read_line(&mut line) {
                Ok(0) | Err(_) => break,
                _ => {
                    if line.len() > 32768 || !line.ends_with('\n') {
                        break;
                    };
                    if control_tx.blocking_send(line).is_err() {
                        break;
                    }
                }
            }
        }
    });
    let owner =
        *blake3::hash(SigningKey::from_bytes(&[77; 32]).verifying_key().as_bytes()).as_bytes();
    while let Some(line) = control_rx.recv().await {
        let outcome = (|| -> Result<Value> {
            let request: Value = serde_json::from_str(&line)?;
            let op = request["operation"].as_str().unwrap_or("");
            let mut packet = vec![2];
            match op {
                "deposit" => {
                    packet.push(1);
                    packet.extend_from_slice(&owner);
                    packet.extend_from_slice(
                        &STANDARD.decode(request["ciphertext"].as_str().unwrap_or(""))?,
                    );
                }
                "fetch" => {
                    packet.push(2);
                    packet.extend_from_slice(&proof(2, &[]));
                }
                "status" | "delete" => {
                    let mut id = owner.to_vec();
                    id.extend_from_slice(
                        blake3::hash(
                            &STANDARD.decode(request["ciphertext"].as_str().unwrap_or(""))?,
                        )
                        .as_bytes(),
                    );
                    let code = if op == "status" { 6 } else { 4 };
                    packet.push(code);
                    packet.extend_from_slice(&proof(code, &id));
                }
                _ => anyhow::bail!("operation"),
            };
            let response = mailbox.process_packet(address, &packet)?;
            Ok(json!({"response":STANDARD.encode(response)}))
        })();
        println!(
            "{}",
            outcome.unwrap_or_else(|_| json!({"error":"rejected"}))
        );
        io::stdout().flush()?;
    }
    Ok(())
}
