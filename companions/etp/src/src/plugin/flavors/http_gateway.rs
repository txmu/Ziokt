//! Bounded loopback read-only HTTP access to verified TNS and local shared objects.
use super::{fileshare::FileShareFlavor, tns::TnsFlavor};
use crate::plugin::{CapabilityProvider, Flavor, FlavorContext};
use anyhow::Result;
use log::{error, info};
use std::{net::SocketAddr, sync::Arc, time::Duration};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    sync::{watch, OwnedSemaphorePermit, Semaphore},
    time::timeout,
};

const HEADER_LIMIT: usize = 8192;
const CONNECTION_LIMIT: usize = 8;
const HEADER_TIMEOUT: Duration = Duration::from_secs(2);
const REQUEST_TIMEOUT: Duration = Duration::from_secs(30);

pub struct HttpGatewayFlavor {
    address: SocketAddr,
    shutdown: watch::Sender<bool>,
}

impl HttpGatewayFlavor {
    /// Legacy asynchronous constructor. Use bind() to receive real startup errors.
    #[deprecated(note = "use HttpGatewayFlavor::bind(...).await to verify listener startup")]
    pub fn new(port: u16, tns: Arc<TnsFlavor>, fs: Arc<FileShareFlavor>) -> Arc<Self> {
        let address = SocketAddr::from(([127, 0, 0, 1], port));
        let (shutdown, receiver) = watch::channel(false);
        tokio::spawn(async move {
            if std::env::var("ZIOKT_AIRGAP")
                .is_ok_and(|v| matches!(v.to_ascii_lowercase().as_str(), "1" | "true" | "yes"))
            {
                error!("AIRGAP_DENIED: ETP HTTP gateway disabled");
                return;
            }
            match TcpListener::bind(address).await {
                Ok(listener) => Self::serve(listener, tns, fs, receiver).await,
                Err(error) => error!("HTTP Gateway bind failed: {}", error),
            }
        });
        Arc::new(Self { address, shutdown })
    }

    pub async fn bind(
        port: u16,
        tns: Arc<TnsFlavor>,
        fs: Arc<FileShareFlavor>,
    ) -> Result<Arc<Self>> {
        anyhow::ensure!(
            !std::env::var("ZIOKT_AIRGAP")
                .is_ok_and(|v| matches!(v.to_ascii_lowercase().as_str(), "1" | "true" | "yes")),
            "AIRGAP_DENIED: ETP HTTP gateway disabled"
        );
        let listener = TcpListener::bind(SocketAddr::from(([127, 0, 0, 1], port))).await?;
        let address = listener.local_addr()?;
        let (shutdown, receiver) = watch::channel(false);
        tokio::spawn(Self::serve(listener, tns, fs, receiver));
        Ok(Arc::new(Self { address, shutdown }))
    }

    pub fn local_addr(&self) -> SocketAddr {
        self.address
    }

    async fn serve(
        listener: TcpListener,
        tns: Arc<TnsFlavor>,
        fs: Arc<FileShareFlavor>,
        mut shutdown: watch::Receiver<bool>,
    ) {
        let address = match listener.local_addr() {
            Ok(address) => address,
            Err(_) => return,
        };
        info!("HTTP Gateway listening on http://{}", address);
        let slots = Arc::new(Semaphore::new(CONNECTION_LIMIT));
        loop {
            let accepted = tokio::select! {
                _ = shutdown.changed() => break,
                accepted = listener.accept() => accepted,
            };
            let (socket, peer) = match accepted {
                Ok(value) => value,
                Err(_) => break,
            };
            if !peer.ip().is_loopback() {
                continue;
            }
            let permit = match slots.clone().try_acquire_owned() {
                Ok(permit) => permit,
                Err(_) => continue,
            };
            let tns = tns.clone();
            let fs = fs.clone();
            let permit = Arc::new(permit);
            tokio::spawn(async move {
                let _permit = permit.clone();
                let _ = timeout(
                    REQUEST_TIMEOUT,
                    Self::handle(socket, address, tns, fs, permit),
                )
                .await;
            });
        }
    }

    async fn respond(
        socket: &mut TcpStream,
        status: &str,
        mime: &str,
        body: &[u8],
        attachment: bool,
    ) -> std::io::Result<()> {
        let disposition = if attachment {
            "Content-Disposition: attachment; filename=shared-object.bin\r\n"
        } else {
            ""
        };
        let header = format!("HTTP/1.1 {}\r\nContent-Type: {}\r\nContent-Length: {}\r\nConnection: close\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\nContent-Security-Policy: default-src 'none'; sandbox\r\n{}\r\n", status, mime, body.len(), disposition);
        socket.write_all(header.as_bytes()).await?;
        for chunk in body.chunks(16 * 1024) {
            socket.write_all(chunk).await?;
        }
        socket.shutdown().await
    }

    async fn handle(
        mut socket: TcpStream,
        address: SocketAddr,
        tns: Arc<TnsFlavor>,
        fs: Arc<FileShareFlavor>,
        slot: Arc<OwnedSemaphorePermit>,
    ) -> std::io::Result<()> {
        let read = timeout(HEADER_TIMEOUT, async {
            let mut bytes = Vec::new();
            loop {
                let mut chunk = [0; 1024];
                let n = socket.read(&mut chunk).await?;
                if n == 0 {
                    return Err(std::io::Error::from(std::io::ErrorKind::UnexpectedEof));
                }
                bytes.extend_from_slice(&chunk[..n]);
                if bytes.len() > HEADER_LIMIT {
                    return Err(std::io::Error::from(std::io::ErrorKind::InvalidData));
                }
                if bytes.windows(4).any(|part| part == b"\r\n\r\n") {
                    return Ok(bytes);
                }
            }
        })
        .await;
        let bytes = match read {
            Ok(Ok(bytes)) => bytes,
            _ => {
                return Self::respond(
                    &mut socket,
                    "400 Bad Request",
                    "text/plain",
                    b"invalid request",
                    false,
                )
                .await
            }
        };
        let request = match std::str::from_utf8(&bytes) {
            Ok(value) => value,
            Err(_) => {
                return Self::respond(
                    &mut socket,
                    "400 Bad Request",
                    "text/plain",
                    b"invalid request",
                    false,
                )
                .await
            }
        };
        let (headers, extra) = match request.split_once("\r\n\r\n") {
            Some(value) => value,
            None => return Ok(()),
        };
        let mut lines = headers.split("\r\n");
        let first: Vec<_> = lines.next().unwrap_or_default().split(' ').collect();
        let allowed_hosts = [address.to_string(), format!("localhost:{}", address.port())];
        let mut host = None;
        let mut valid = extra.is_empty();
        let mut seen = std::collections::HashSet::new();
        for line in lines {
            let (name, value) = match line.split_once(':') {
                Some(pair) => pair,
                None => {
                    valid = false;
                    break;
                }
            };
            let name = name.to_ascii_lowercase();
            let value = value.trim();
            if name.is_empty()
                || !name.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'-')
                || !seen.insert(name.clone())
                || value.bytes().any(|c| c < 32 || c == 127)
            {
                valid = false;
                break;
            }
            match name.as_str() {
                "host" => host = Some(value),
                "origin" => {
                    valid &= allowed_hosts
                        .iter()
                        .any(|host| value == format!("http://{}", host))
                }
                "sec-fetch-site" => valid &= matches!(value, "same-origin" | "none"),
                "content-length" => valid &= value == "0",
                "transfer-encoding" => valid = false,
                _ => {}
            }
        }
        valid &= host.is_some_and(|host| allowed_hosts.iter().any(|allowed| host == allowed));
        if !valid {
            return Self::respond(
                &mut socket,
                "403 Forbidden",
                "text/plain",
                b"request rejected",
                false,
            )
            .await;
        }
        if first.len() != 3 || first[2] != "HTTP/1.1" || first[0] != "GET" {
            return Self::respond(
                &mut socket,
                "405 Method Not Allowed",
                "text/plain",
                b"GET required",
                false,
            )
            .await;
        }
        let path = first[1];
        if let Some(hash) = path.strip_prefix("/fs/") {
            if hash.len() == 64
                && hash
                    .bytes()
                    .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
            {
                let hash: [u8; 32] = match hex::decode(hash)
                    .ok()
                    .and_then(|bytes| bytes.try_into().ok())
                {
                    Some(hash) => hash,
                    None => return Ok(()),
                };
                // The bytes are verified before HTTP headers, and streamed from that immutable snapshot.
                if let Ok(Ok(data)) = tokio::task::spawn_blocking(move || {
                    let _permit = slot;
                    fs.read_shared(hash)
                })
                .await
                {
                    return Self::respond(
                        &mut socket,
                        "200 OK",
                        "application/octet-stream",
                        &data,
                        true,
                    )
                    .await;
                }
            }
        } else if let Some(name) = path.strip_prefix("/tns/") {
            if !name.is_empty()
                && name.len() <= 253
                && name
                    .bytes()
                    .all(|c| c.is_ascii_alphanumeric() || matches!(c, b'.' | b'-' | b'_'))
            {
                if let Ok(record) = tns.resolve(name).await {
                    let data = serde_json::to_vec(&serde_json::json!({"name":record.name,"target":hex::encode(record.target_id)})).map_err(std::io::Error::other)?;
                    return Self::respond(&mut socket, "200 OK", "application/json", &data, false)
                        .await;
                }
            }
        }
        Self::respond(
            &mut socket,
            "404 Not Found",
            "text/plain",
            b"local object unavailable",
            false,
        )
        .await
    }
}
impl Drop for HttpGatewayFlavor {
    fn drop(&mut self) {
        let _ = self.shutdown.send(true);
    }
}
impl CapabilityProvider for HttpGatewayFlavor {
    fn capability_id(&self) -> String {
        "etp.flavor.gateway.v1".into()
    }
}
impl Flavor for HttpGatewayFlavor {
    fn on_stream_data(&self, _ctx: FlavorContext, _data: &[u8]) -> bool {
        false
    }
    fn on_connection_open(&self, _peer: SocketAddr) {}
    fn on_connection_close(&self, _peer: SocketAddr) {}
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;
    use tokio::sync::mpsc;

    async fn fixture() -> (
        PathBuf,
        Arc<HttpGatewayFlavor>,
        Arc<FileShareFlavor>,
        [u8; 32],
        Vec<u8>,
    ) {
        let root = std::env::temp_dir().join(format!("etp-http-{}", rand::random::<u64>()));
        std::fs::create_dir_all(&root).unwrap();
        let (net_tx, _net_rx) = mpsc::channel(16);
        let (dht_tx, _dht_rx) = mpsc::channel(16);
        let tns = TnsFlavor::new(
            root.join("tns").to_str().unwrap(),
            &[7; 32],
            dht_tx,
            net_tx.clone(),
        )
        .unwrap();
        let fs = FileShareFlavor::new(root.join("shared").to_str().unwrap(), net_tx).unwrap();
        let data = vec![42; 100_000];
        let source = root.join("source");
        std::fs::write(&source, &data).unwrap();
        let hash = fs.share_file(&source).unwrap();
        let gateway = HttpGatewayFlavor::bind(0, tns, fs.clone()).await.unwrap();
        (root, gateway, fs, hash, data)
    }
    async fn request(address: SocketAddr, path: &str, headers: &str) -> Vec<u8> {
        let mut socket = TcpStream::connect(address).await.unwrap();
        socket
            .write_all(format!("GET {} HTTP/1.1\r\n{}\r\n", path, headers).as_bytes())
            .await
            .unwrap();
        let mut result = Vec::new();
        timeout(Duration::from_secs(4), socket.read_to_end(&mut result))
            .await
            .unwrap()
            .unwrap();
        result
    }
    async fn cleanup(root: PathBuf, gateway: Arc<HttpGatewayFlavor>, fs: Arc<FileShareFlavor>) {
        drop(gateway);
        drop(fs);
        tokio::time::sleep(Duration::from_millis(30)).await;
        std::fs::remove_dir_all(root).unwrap();
    }

    #[tokio::test]
    async fn real_http_streams_only_verified_local_shared_bytes() {
        let (root, gateway, fs, hash, data) = fixture().await;
        let address = gateway.local_addr();
        let path = format!("/fs/{}", hex::encode(hash));
        let reply = request(address, &path, &format!("Host: {}\r\n", address)).await;
        let end = reply
            .windows(4)
            .position(|part| part == b"\r\n\r\n")
            .unwrap()
            + 4;
        assert!(reply.starts_with(b"HTTP/1.1 200 OK\r\n"));
        assert_eq!(&reply[end..], data.as_slice());
        assert!(String::from_utf8_lossy(&reply[..end]).contains("Content-Length: 100000\r\n"));
        assert!(String::from_utf8_lossy(&reply[..end]).contains("Content-Disposition: attachment"));
        std::fs::write(
            root.join("shared").join(hex::encode(hash)),
            vec![99; data.len()],
        )
        .unwrap();
        let reply = request(address, &path, &format!("Host: {}\r\n", address)).await;
        assert!(reply.starts_with(b"HTTP/1.1 404"));
        assert!(fs.read_shared(hash).is_err());
        cleanup(root, gateway, fs).await;
    }

    #[tokio::test]
    async fn real_http_rejects_rebinding_csrf_paths_and_oversized_headers() {
        let (root, gateway, fs, hash, _) = fixture().await;
        let address = gateway.local_addr();
        let path = format!("/fs/{}", hex::encode(hash));
        for headers in [
            "Host: attacker.invalid\r\n".to_string(),
            format!("Host: {}\r\nOrigin: https://attacker.invalid\r\n", address),
            format!("Host: {}\r\nSec-Fetch-Site: cross-site\r\n", address),
            format!("Host: {}\r\nSec-Fetch-Site: same-site\r\n", address),
            format!("Host: {}\r\nHost: {}\r\n", address, address),
            format!("Host: {}\r\nContent-Length: 1\r\n", address),
            format!("Host: {}\r\nTransfer-Encoding: chunked\r\n", address),
        ] {
            assert!(request(address, &path, &headers)
                .await
                .starts_with(b"HTTP/1.1 403"));
        }
        for path in [
            "/fs/../../source",
            "/fs/%2e%2e/source",
            "/fs/",
            "/fs/0000000000000000000000000000000000000000000000000000000000000000",
            "/fs/source?x=1",
        ] {
            assert!(request(address, path, &format!("Host: {}\r\n", address))
                .await
                .starts_with(b"HTTP/1.1 404"));
        }
        let oversized = format!(
            "Host: {}\r\nX-Large: {}\r\n",
            address,
            "a".repeat(HEADER_LIMIT)
        );
        assert!(request(address, &path, &oversized)
            .await
            .starts_with(b"HTTP/1.1 400"));
        cleanup(root, gateway, fs).await;
    }

    #[tokio::test]
    async fn real_http_handles_fragmented_headers_budgets_and_listener_shutdown() {
        let (root, gateway, fs, hash, data) = fixture().await;
        let address = gateway.local_addr();
        let mut socket = TcpStream::connect(address).await.unwrap();
        socket
            .write_all(format!("GET /fs/{} HTTP/1.1\r\nHo", hex::encode(hash)).as_bytes())
            .await
            .unwrap();
        tokio::time::sleep(Duration::from_millis(10)).await;
        socket
            .write_all(format!("st: {}\r\n\r\n", address).as_bytes())
            .await
            .unwrap();
        let mut response = Vec::new();
        timeout(Duration::from_secs(4), socket.read_to_end(&mut response))
            .await
            .unwrap()
            .unwrap();
        assert!(response.ends_with(&data));
        let mut held = Vec::new();
        for _ in 0..CONNECTION_LIMIT {
            let mut socket = TcpStream::connect(address).await.unwrap();
            socket.write_all(b"GET / HTTP/1.1\r\n").await.unwrap();
            held.push(socket);
        }
        tokio::time::sleep(Duration::from_millis(30)).await;
        let mut excess = TcpStream::connect(address).await.unwrap();
        let mut byte = [0; 1];
        assert_eq!(
            timeout(Duration::from_secs(1), excess.read(&mut byte))
                .await
                .unwrap()
                .unwrap(),
            0
        );
        drop(held);
        tokio::time::sleep(Duration::from_millis(30)).await;
        let mut slow = TcpStream::connect(address).await.unwrap();
        slow.write_all(b"GET /").await.unwrap();
        let mut response = Vec::new();
        timeout(Duration::from_secs(4), slow.read_to_end(&mut response))
            .await
            .unwrap()
            .unwrap();
        assert!(response.starts_with(b"HTTP/1.1 400"));
        drop(gateway);
        tokio::time::sleep(Duration::from_millis(30)).await;
        assert!(TcpStream::connect(address).await.is_err());
        drop(fs);
        std::fs::remove_dir_all(root).unwrap();
    }
}
