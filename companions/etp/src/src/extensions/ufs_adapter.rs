//! Capability-rooted UFS operations with bounded requests, workers and replies.
#![cfg(feature = "ultrafileserver")]
use crate::plugin::{CapabilityProvider, Flavor, FlavorContext};
use anyhow::{ensure, Result};
use cap_std::fs::{Dir, OpenOptions};
use serde::{Deserialize, Serialize};
use std::{
    io::{Read, Seek, SeekFrom, Write},
    net::SocketAddr,
    path::{Component, Path},
    sync::Arc,
};
use tokio::sync::{mpsc, Semaphore};
const VERSION: u8 = 1;
const CHUNK: usize = 16384;
const MAX_FILE: u64 = 16 * 1024 * 1024;
#[derive(Serialize, Deserialize, Debug)]
pub struct FileMetadata {
    pub name: String,
    pub is_dir: bool,
    pub size: u64,
    pub modified: u64,
    pub mime_type: String,
}
#[derive(Serialize, Deserialize, Debug)]
pub struct DirectoryListing {
    pub path: String,
    pub files: Vec<FileMetadata>,
}
#[derive(Clone)]
pub struct UltraFileServerFlavor {
    root: Arc<Dir>,
    network_tx: mpsc::Sender<(SocketAddr, Vec<u8>)>,
    read_only: bool,
    workers: Arc<Semaphore>,
}
impl UltraFileServerFlavor {
    pub fn new(
        path: &str,
        network_tx: mpsc::Sender<(SocketAddr, Vec<u8>)>,
        read_only: bool,
    ) -> Result<Arc<Self>> {
        Ok(Arc::new(Self {
            root: Arc::new(Dir::open_ambient_dir(path, cap_std::ambient_authority())?),
            network_tx,
            read_only,
            workers: Arc::new(Semaphore::new(16)),
        }))
    }
    fn path(value: &str) -> Result<&Path> {
        ensure!(
            value.len() <= 1024 && !value.contains(['\\', '\0']) && !value.contains(':'),
            "bounded relative path required"
        );
        let path = Path::new(value);
        ensure!(
            path.components()
                .all(|c| matches!(c, Component::Normal(_) | Component::CurDir)),
            "relative non-traversing path required"
        );
        Ok(if value.is_empty() {
            Path::new(".")
        } else {
            path
        })
    }
    fn metadata(name: String, meta: cap_std::fs::Metadata) -> FileMetadata {
        FileMetadata {
            name,
            is_dir: meta.is_dir(),
            size: meta.len(),
            modified: meta
                .modified()
                .ok()
                .and_then(|t| t.into_std().duration_since(std::time::UNIX_EPOCH).ok())
                .map(|d| d.as_secs())
                .unwrap_or(0),
            mime_type: if meta.is_dir() {
                "inode/directory"
            } else {
                "application/octet-stream"
            }
            .into(),
        }
    }
    fn request(&self, op: u8, data: &[u8]) -> Result<Vec<u8>> {
        ensure!(data.len() <= CHUNK + 1034, "UFS request budget");
        match op {
            1 => {
                let name = std::str::from_utf8(data)?;
                let dir = self.root.open_dir(Self::path(name)?)?;
                let mut files = Vec::new();
                for entry in dir.entries()? {
                    let entry = entry?;
                    ensure!(files.len() < 128, "directory entry budget");
                    files.push(Self::metadata(
                        entry.file_name().to_string_lossy().into_owned(),
                        entry.metadata()?,
                    ));
                }
                let mut packet = vec![VERSION, 2];
                packet.extend(serde_json::to_vec(&DirectoryListing {
                    path: name.into(),
                    files,
                })?);
                ensure!(packet.len() <= CHUNK * 2, "directory reply budget");
                Ok(packet)
            }
            3 => {
                ensure!(data.len() >= 8, "file offset required");
                let offset = u64::from_be_bytes(data[..8].try_into()?);
                ensure!(offset <= MAX_FILE, "file offset budget");
                let name = std::str::from_utf8(&data[8..])?;
                let mut file = self.root.open(Self::path(name)?)?;
                ensure!(
                    file.metadata()?.is_file() && file.metadata()?.len() <= MAX_FILE,
                    "regular bounded file required"
                );
                file.seek(SeekFrom::Start(offset))?;
                let mut bytes = vec![0; CHUNK];
                let size = file.read(&mut bytes)?;
                bytes.truncate(size);
                let mut packet = vec![VERSION, 4];
                packet.extend_from_slice(&offset.to_be_bytes());
                packet.extend(bytes);
                Ok(packet)
            }
            5 => {
                ensure!(
                    !self.read_only && data.len() >= 10,
                    "write denied or malformed"
                );
                let offset = u64::from_be_bytes(data[..8].try_into()?);
                let length = u16::from_be_bytes(data[8..10].try_into()?) as usize;
                ensure!(
                    length <= 1024 && data.len() >= 10 + length,
                    "file path budget"
                );
                let bytes = &data[10 + length..];
                ensure!(
                    bytes.len() <= CHUNK
                        && offset
                            .checked_add(bytes.len() as u64)
                            .map(|v| v <= MAX_FILE)
                            .unwrap_or(false),
                    "file write budget"
                );
                let name = std::str::from_utf8(&data[10..10 + length])?;
                let path = Self::path(name)?;
                let mut options = OpenOptions::new();
                options.write(true).create(true);
                let mut file = self.root.open_with(path, &options)?;
                ensure!(file.metadata()?.is_file(), "regular destination required");
                file.seek(SeekFrom::Start(offset))?;
                file.write_all(bytes)?;
                file.sync_all()?;
                Ok(vec![VERSION, 8])
            }
            6 => {
                ensure!(!self.read_only, "delete denied");
                let name = std::str::from_utf8(data)?;
                let path = Self::path(name)?;
                // Deliberately bounded: directories must be empty before removing them.
                if self.root.symlink_metadata(path)?.is_dir() {
                    self.root.remove_dir(path)?;
                } else {
                    self.root.remove_file(path)?;
                }
                Ok(vec![VERSION, 8])
            }
            7 => {
                let name = std::str::from_utf8(data)?;
                let meta = self.root.metadata(Self::path(name)?)?;
                let mut packet = vec![VERSION, 8];
                packet.extend(serde_json::to_vec(&Self::metadata(name.into(), meta))?);
                Ok(packet)
            }
            _ => anyhow::bail!("unsupported UFS operation"),
        }
    }
}
impl CapabilityProvider for UltraFileServerFlavor {
    fn capability_id(&self) -> String {
        "etp.flavor.ufs.v1".into()
    }
}
impl Flavor for UltraFileServerFlavor {
    fn on_stream_data(&self, ctx: FlavorContext, data: &[u8]) -> bool {
        if data.len() < 2 || data[0] != VERSION || !matches!(data[1], 1 | 3 | 5 | 6 | 7) {
            return false;
        }
        if data.len() > CHUNK + 1036 {
            return true;
        }
        let Ok(permit) = self.workers.clone().try_acquire_owned() else {
            return true;
        };
        let worker = self.clone();
        let op = data[1];
        let bytes = data[2..].to_vec();
        let peer = ctx.src_addr;
        tokio::task::spawn_blocking(move || {
            let _permit = permit;
            let packet = worker
                .request(op, &bytes)
                .unwrap_or_else(|_| vec![VERSION, 255]);
            let _ = worker.network_tx.try_send((peer, packet));
        });
        true
    }
    fn on_connection_open(&self, _: SocketAddr) {}
    fn on_connection_close(&self, _: SocketAddr) {}
}
impl std::fmt::Debug for UltraFileServerFlavor {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("UltraFileServerFlavor")
            .finish_non_exhaustive()
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn capability_root_rejects_parent_and_symlink_escape_and_bounds_writes() {
        let base = std::env::temp_dir().join(format!("etp-ufs-{}", rand::random::<u64>()));
        std::fs::create_dir_all(base.join("root")).unwrap();
        std::fs::write(base.join("outside"), b"private").unwrap();
        let (tx, _) = mpsc::channel(8);
        let ufs =
            UltraFileServerFlavor::new(base.join("root").to_str().unwrap(), tx, false).unwrap();
        for path in ["../outside", "/etc/passwd", "..\\outside", "C:outside"] {
            assert!(ufs.request(7, path.as_bytes()).is_err());
        }
        #[cfg(unix)]
        {
            std::os::unix::fs::symlink(base.join("outside"), base.join("root/escape")).unwrap();
            let mut req = 0u64.to_be_bytes().to_vec();
            req.extend_from_slice(b"escape");
            assert!(ufs.request(3, &req).is_err());
        }
        let mut put = 0u64.to_be_bytes().to_vec();
        put.extend_from_slice(&4u16.to_be_bytes());
        put.extend_from_slice(b"safe");
        put.extend_from_slice(b"sealed");
        ufs.request(5, &put).unwrap();
        let mut get = 0u64.to_be_bytes().to_vec();
        get.extend_from_slice(b"safe");
        assert_eq!(&ufs.request(3, &get).unwrap()[10..], b"sealed");
        let readonly = UltraFileServerFlavor::new(
            base.join("root").to_str().unwrap(),
            ufs.network_tx.clone(),
            true,
        )
        .unwrap();
        assert!(readonly.request(5, &put).is_err());
        assert!(ufs.request(5, &vec![0; CHUNK + 1035]).is_err());
        drop(ufs);
        drop(readonly);
        std::fs::remove_dir_all(base).unwrap();
    }
}
