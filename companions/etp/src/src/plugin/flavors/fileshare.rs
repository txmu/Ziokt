//! Content addressed, bounded file exchange. Peer filenames are display metadata only.
use crate::plugin::{CapabilityProvider, Flavor, FlavorContext};
use anyhow::{ensure, Result};
use bincode::Options;
use parking_lot::{Mutex, RwLock};
use serde::{Deserialize, Serialize};
use std::{
    collections::{HashMap, HashSet},
    fs::{self, File, OpenOptions},
    io::{Read, Seek, SeekFrom, Write},
    net::SocketAddr,
    path::{Path, PathBuf},
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::sync::mpsc;
const VERSION: u8 = 1;
const CHUNK_SIZE: usize = 16 * 1024;
const MAX_CHUNKS: usize = 1024;
const MAX_TASKS: usize = 16;
const MAX_WIRE: usize = 40000;
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileManifest {
    pub file_name: String,
    pub file_size: u64,
    pub mime_type: String,
    pub chunk_count: u32,
    pub root_hash: [u8; 32],
    pub chunk_hashes: Vec<[u8; 32]>,
}
impl FileManifest {
    fn validate(&self) -> bool {
        let count = self.file_size.div_ceil(CHUNK_SIZE as u64);
        self.file_size > 0
            && count <= MAX_CHUNKS as u64
            && self.chunk_count as u64 == count
            && self.chunk_hashes.len() == count as usize
            && self.file_name.len() <= 255
            && self.mime_type.len() <= 128
            && root(&self.chunk_hashes) == self.root_hash
    }
    pub fn verify_chunk(&self, index: u32, data: &[u8]) -> bool {
        if index >= self.chunk_count || self.chunk_hashes.len() != self.chunk_count as usize {
            return false;
        }
        let size = if index + 1 == self.chunk_count {
            (self.file_size - index as u64 * CHUNK_SIZE as u64) as usize
        } else {
            CHUNK_SIZE
        };
        data.len() == size && blake3::hash(data).as_bytes() == &self.chunk_hashes[index as usize]
    }
}
fn root(hashes: &[[u8; 32]]) -> [u8; 32] {
    let mut hash = blake3::Hasher::new();
    for chunk in hashes {
        hash.update(chunk);
    }
    *hash.finalize().as_bytes()
}
fn private_new(path: &Path) -> Result<File> {
    let mut options = OpenOptions::new();
    options.create_new(true).read(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    Ok(options.open(path)?)
}
fn regular_read(path: &Path) -> Result<File> {
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK);
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        // Open the reparse point itself; the regular-file check below rejects it.
        options.custom_flags(0x00200000); // FILE_FLAG_OPEN_REPARSE_POINT
    }
    let file = options.open(path)?;
    ensure!(file.metadata()?.is_file(), "regular file required");
    Ok(file)
}
struct DownloadTask {
    manifest: FileManifest,
    received: HashSet<u32>,
    peer: SocketAddr,
    file: File,
    path: PathBuf,
    next: u32,
    started: Instant,
}
impl Drop for DownloadTask {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.path);
    }
}
pub struct FileShareFlavor {
    storage_dir: PathBuf,
    shared_files: RwLock<HashMap<[u8; 32], FileManifest>>,
    active_downloads: Mutex<HashMap<[u8; 32], DownloadTask>>,
    pending: Mutex<HashMap<[u8; 32], (SocketAddr, Instant)>>,
    network_tx: mpsc::Sender<(SocketAddr, Vec<u8>)>,
}
impl FileShareFlavor {
    pub fn new(
        storage: &str,
        network_tx: mpsc::Sender<(SocketAddr, Vec<u8>)>,
    ) -> Result<Arc<Self>> {
        fs::create_dir_all(storage)?;
        ensure!(
            fs::symlink_metadata(storage)?.is_dir(),
            "real storage directory required"
        );
        Ok(Arc::new(Self {
            storage_dir: Path::new(storage).canonicalize()?,
            shared_files: RwLock::new(HashMap::new()),
            active_downloads: Mutex::new(HashMap::new()),
            pending: Mutex::new(HashMap::new()),
            network_tx,
        }))
    }
    pub fn share_file(&self, path: &Path) -> Result<[u8; 32]> {
        ensure!(
            self.shared_files.read().len() < MAX_CHUNKS,
            "shared file budget"
        );
        let mut source = regular_read(path)?;
        let size = source.metadata()?.len();
        ensure!(
            (1..=(MAX_CHUNKS * CHUNK_SIZE) as u64).contains(&size),
            "file size budget"
        );
        // Snapshot the same handle we hash, never reopen the source for copying.
        let mut bytes = Vec::new();
        source.take(size + 1).read_to_end(&mut bytes)?;
        ensure!(bytes.len() as u64 == size, "source changed");
        let hashes: Vec<_> = bytes
            .chunks(CHUNK_SIZE)
            .map(|c| *blake3::hash(c).as_bytes())
            .collect();
        let hash = root(&hashes);
        let manifest = FileManifest {
            file_name: path
                .file_name()
                .ok_or_else(|| anyhow::anyhow!("file name required"))?
                .to_string_lossy()
                .chars()
                .take(255)
                .collect(),
            file_size: size,
            mime_type: "application/octet-stream".into(),
            chunk_count: hashes.len() as u32,
            root_hash: hash,
            chunk_hashes: hashes,
        };
        let dest = self.storage_dir.join(hex::encode(hash));
        match private_new(&dest) {
            Ok(mut file) => {
                file.write_all(&bytes)?;
                file.sync_all()?;
            }
            Err(error) if dest.exists() => {
                let mut existing = Vec::new();
                regular_read(&dest)?
                    .take(size + 1)
                    .read_to_end(&mut existing)?;
                ensure!(existing == bytes, "stored content mismatch: {error}");
            }
            Err(error) => return Err(error),
        }
        self.shared_files.write().insert(hash, manifest);
        Ok(hash)
    }
    /// Snapshot only an explicitly shared/completed local object, validating every
    /// chunk before any caller can expose its bytes. Hashes are not filesystem paths.
    pub fn read_shared(&self, hash: [u8; 32]) -> Result<Vec<u8>> {
        let manifest = self
            .shared_files
            .read()
            .get(&hash)
            .cloned()
            .ok_or_else(|| anyhow::anyhow!("local object not shared"))?;
        ensure!(
            manifest.validate() && manifest.root_hash == hash,
            "invalid local manifest"
        );
        let file = regular_read(&self.storage_dir.join(hex::encode(hash)))?;
        ensure!(
            file.metadata()?.len() == manifest.file_size,
            "stored content size changed"
        );
        let mut bytes = Vec::new();
        file.take(manifest.file_size + 1).read_to_end(&mut bytes)?;
        ensure!(
            bytes.len() as u64 == manifest.file_size,
            "stored content changed"
        );
        ensure!(
            bytes
                .chunks(CHUNK_SIZE)
                .enumerate()
                .all(|(i, data)| manifest.verify_chunk(i as u32, data)),
            "stored content digest mismatch"
        );
        Ok(bytes)
    }

    pub async fn start_download(&self, hash: [u8; 32], peer: SocketAddr) -> Result<()> {
        {
            let mut pending = self.pending.lock();
            pending.retain(|_, (_, t)| t.elapsed() < Duration::from_secs(60));
            ensure!(
                pending.len() < MAX_TASKS
                    && !pending.contains_key(&hash)
                    && !self.active_downloads.lock().contains_key(&hash),
                "download budget or duplicate"
            );
            pending.insert(hash, (peer, Instant::now()));
        }
        let mut packet = vec![VERSION, 1];
        packet.extend_from_slice(&hash);
        if let Err(error) = self.network_tx.send((peer, packet)).await {
            self.pending.lock().remove(&hash);
            return Err(error.into());
        }
        Ok(())
    }
    fn send(&self, peer: SocketAddr, packet: Vec<u8>) -> Result<()> {
        self.network_tx.try_send((peer, packet))?;
        Ok(())
    }
    fn request_chunk(&self, peer: SocketAddr, hash: &[u8; 32], index: u32) -> Result<()> {
        let mut packet = vec![VERSION, 3];
        packet.extend_from_slice(hash);
        packet.extend_from_slice(&index.to_be_bytes());
        self.send(peer, packet)
    }
    fn handle(&self, peer: SocketAddr, data: &[u8]) -> Result<()> {
        ensure!(
            data.len() >= 2 && data.len() <= MAX_WIRE,
            "wire size budget"
        );
        match data[1] {
            1 => {
                ensure!(data.len() == 34, "manifest request size");
                let hash: [u8; 32] = data[2..].try_into()?;
                if let Some(manifest) = self.shared_files.read().get(&hash) {
                    let mut packet = vec![VERSION, 2];
                    packet.extend(bincode::serialize(manifest)?);
                    self.send(peer, packet)?;
                }
            }
            2 => {
                let manifest: FileManifest = bincode::DefaultOptions::new()
                    .with_fixint_encoding()
                    .with_limit(MAX_WIRE as u64)
                    .reject_trailing_bytes()
                    .deserialize(&data[2..])?;
                ensure!(manifest.validate(), "invalid manifest");
                let mut pending = self.pending.lock();
                let hash = manifest.root_hash;
                ensure!(
                    pending
                        .get(&hash)
                        .map(|(p, t)| *p == peer && t.elapsed() < Duration::from_secs(60))
                        .unwrap_or(false),
                    "unsolicited manifest"
                );
                let mut tasks = self.active_downloads.lock();
                ensure!(
                    tasks.len() < MAX_TASKS && !tasks.contains_key(&hash),
                    "active download budget"
                );
                let path = self.storage_dir.join(format!(
                    "{}.{}.part",
                    hex::encode(hash),
                    rand::random::<u64>()
                ));
                let file = private_new(&path)?;
                file.set_len(manifest.file_size)?;
                tasks.insert(
                    hash,
                    DownloadTask {
                        manifest,
                        received: HashSet::new(),
                        peer,
                        file,
                        path,
                        next: 0,
                        started: Instant::now(),
                    },
                );
                pending.remove(&hash);
            }
            3 => {
                ensure!(data.len() == 38, "chunk request size");
                let hash: [u8; 32] = data[2..34].try_into()?;
                let index = u32::from_be_bytes(data[34..38].try_into()?);
                let shared = self.shared_files.read();
                let manifest = shared
                    .get(&hash)
                    .ok_or_else(|| anyhow::anyhow!("unshared file"))?;
                ensure!(index < manifest.chunk_count, "chunk index");
                let mut file = regular_read(&self.storage_dir.join(hex::encode(hash)))?;
                file.seek(SeekFrom::Start(index as u64 * CHUNK_SIZE as u64))?;
                let mut bytes = vec![0; CHUNK_SIZE];
                let len = file.read(&mut bytes)?;
                bytes.truncate(len);
                ensure!(manifest.verify_chunk(index, &bytes), "stored chunk changed");
                let mut packet = vec![VERSION, 4];
                packet.extend_from_slice(&hash);
                packet.extend_from_slice(&index.to_be_bytes());
                packet.extend(bytes);
                self.send(peer, packet)?;
            }
            4 => {
                ensure!(data.len() >= 38, "chunk response size");
                let hash: [u8; 32] = data[2..34].try_into()?;
                let index = u32::from_be_bytes(data[34..38].try_into()?);
                let mut tasks = self.active_downloads.lock();
                let task = tasks
                    .get_mut(&hash)
                    .ok_or_else(|| anyhow::anyhow!("unsolicited chunk"))?;
                ensure!(
                    task.peer == peer && task.manifest.verify_chunk(index, &data[38..]),
                    "invalid chunk or sender"
                );
                if task.received.insert(index) {
                    task.file
                        .seek(SeekFrom::Start(index as u64 * CHUNK_SIZE as u64))?;
                    task.file.write_all(&data[38..])?;
                }
                if task.received.len() == task.manifest.chunk_count as usize {
                    task.file.sync_all()?;
                    // Link is atomic and refuses overwrite. A peer filename is never a path.
                    fs::hard_link(&task.path, self.storage_dir.join(hex::encode(hash)))?;
                    self.shared_files
                        .write()
                        .insert(hash, task.manifest.clone());
                    tasks.remove(&hash);
                }
            }
            _ => anyhow::bail!("unknown file operation"),
        }
        Ok(())
    }
}
impl CapabilityProvider for FileShareFlavor {
    fn capability_id(&self) -> String {
        "etp.flavor.fs.v1".into()
    }
}
impl Flavor for FileShareFlavor {
    fn priority(&self) -> u8 {
        80
    }
    fn on_stream_data(&self, ctx: FlavorContext, data: &[u8]) -> bool {
        if data.len() < 2 || data[0] != VERSION || !(1..=4).contains(&data[1]) {
            return false;
        }
        let _ = self.handle(ctx.src_addr, data);
        true
    }
    fn on_connection_open(&self, _: SocketAddr) {}
    fn on_connection_close(&self, _: SocketAddr) {}
    fn poll(&self) {
        let mut tasks = self.active_downloads.lock();
        tasks.retain(|_, t| t.started.elapsed() < Duration::from_secs(300));
        for (hash, task) in tasks.iter_mut() {
            // Reissue at most one missing chunk per tick; bounded queue applies backpressure.
            let count = task.manifest.chunk_count;
            for _ in 0..count {
                let index = task.next % count;
                task.next = (index + 1) % count;
                if !task.received.contains(&index) {
                    let _ = self.request_chunk(task.peer, hash, index);
                    break;
                }
            }
        }
    }
}
impl std::fmt::Debug for FileShareFlavor {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("FileShareFlavor").finish_non_exhaustive()
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    async fn content_addressed_download_rejects_unsolicited_data_and_completes_after_five_chunks() {
        let dir = std::env::temp_dir().join(format!("etp-fs-{}", rand::random::<u64>()));
        fs::create_dir_all(&dir).unwrap();
        let (tx, mut rx) = mpsc::channel(16);
        let store = FileShareFlavor::new(dir.to_str().unwrap(), tx).unwrap();
        let peer = "127.0.0.1:12345".parse().unwrap();
        let bytes = vec![42; CHUNK_SIZE * 6 + 7];
        let hashes = bytes
            .chunks(CHUNK_SIZE)
            .map(|c| *blake3::hash(c).as_bytes())
            .collect::<Vec<_>>();
        let hash = root(&hashes);
        let manifest = FileManifest {
            file_name: "../../escape".into(),
            file_size: bytes.len() as u64,
            mime_type: "application/octet-stream".into(),
            chunk_count: hashes.len() as u32,
            root_hash: hash,
            chunk_hashes: hashes,
        };
        let mut packet = vec![VERSION, 2];
        packet.extend(bincode::serialize(&manifest).unwrap());
        assert!(store.handle(peer, &packet).is_err());
        store.start_download(hash, peer).await.unwrap();
        rx.recv().await.unwrap();
        store.handle(peer, &packet).unwrap();
        for (index, chunk) in bytes.chunks(CHUNK_SIZE).enumerate() {
            store.poll();
            let (_, request) = rx.recv().await.unwrap();
            assert_eq!(
                u32::from_be_bytes(request[34..38].try_into().unwrap()),
                index as u32
            );
            let mut response = vec![VERSION, 4];
            response.extend_from_slice(&hash);
            response.extend_from_slice(&(index as u32).to_be_bytes());
            response.extend_from_slice(chunk);
            assert!(store
                .handle("127.0.0.1:12346".parse().unwrap(), &response)
                .is_err());
            store.handle(peer, &response).unwrap();
        }
        assert!(store.active_downloads.lock().is_empty());
        assert_eq!(fs::read(dir.join(hex::encode(hash))).unwrap(), bytes);
        assert_eq!(fs::read_dir(&dir).unwrap().count(), 1);
        drop(store);
        fs::remove_dir_all(dir).unwrap();
    }
}
