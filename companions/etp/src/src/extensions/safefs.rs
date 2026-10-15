//! SafeFS v3: bounded password-encrypted files, authenticated headers and private outputs.
//! Guards self-test this process's crypto; they do not inspect, terminate or modify other processes.
#![cfg(feature = "safefs")]
use crate::error::EtpError;
use anyhow::{ensure, Result};
use argon2::{Algorithm, Argon2, Params, Version};
use chacha20poly1305::{
    aead::{Aead, Payload},
    ChaCha20Poly1305, KeyInit,
};
use rand::RngCore;
use std::{
    fs::{File, OpenOptions},
    io::{Read, Seek, SeekFrom, Write},
    path::Path,
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc, Arc,
    },
    thread::{self, JoinHandle},
    time::Duration,
};
use zeroize::{Zeroize, Zeroizing};
pub const KDF_SALT_LEN: usize = 16;
const MAGIC: &[u8; 8] = b"ETP-SFS3";
const MAX_FILE: usize = 8 * 1024 * 1024;
const MAX_SEALED: usize = 16 * 1024 * 1024;
const HEADER: usize = 52;
pub struct SecureKey {
    key: [u8; 32],
}
impl SecureKey {
    pub fn new(key: [u8; 32]) -> Self {
        Self { key }
    }
    pub fn as_bytes(&self) -> &[u8] {
        &self.key
    }
}
impl Drop for SecureKey {
    fn drop(&mut self) {
        self.key.zeroize();
    }
}
pub struct CryptoEngine;
impl CryptoEngine {
    pub fn derive_key(password: &str) -> Result<(SecureKey, [u8; 16], [u8; 16]), EtpError> {
        let mut context = [0; 16];
        let mut salt = [0; 16];
        rand::rngs::OsRng.fill_bytes(&mut context);
        rand::rngs::OsRng.fill_bytes(&mut salt);
        Ok((Self::restore_key(password, &context, &salt)?, context, salt))
    }
    pub fn restore_key(password: &str, context: &[u8], salt: &[u8]) -> Result<SecureKey, EtpError> {
        fn derive(password: &str, context: &[u8], salt: &[u8]) -> Result<SecureKey> {
            ensure!(
                !password.is_empty()
                    && password.len() <= 4096
                    && context.len() == 16
                    && salt.len() == 16,
                "bounded password and v3 salts required"
            );
            let parameters = Params::new(65536, 3, 1, Some(32))
                .map_err(|_| anyhow::anyhow!("KDF parameters"))?;
            let mut intermediate = Zeroizing::new([0u8; 32]);
            Argon2::new(Algorithm::Argon2id, Version::V0x13, parameters)
                .hash_password_into(password.as_bytes(), salt, intermediate.as_mut())
                .map_err(|_| anyhow::anyhow!("KDF rejected"))?;
            let mut input = Zeroizing::new(Vec::from(intermediate.as_slice()));
            input.extend_from_slice(context);
            Ok(SecureKey::new(blake3::derive_key(
                "ETP SafeFS password file v3",
                &input,
            )))
        }
        derive(password, context, salt).map_err(Into::into)
    }
    pub fn constant_time_eq(a: &[u8], b: &[u8]) -> bool {
        constant_time_eq::constant_time_eq(a, b)
    }
}
fn open_regular(path: &Path) -> Result<File> {
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK);
    }
    let file = options.open(path)?;
    ensure!(file.metadata()?.is_file(), "regular input required");
    Ok(file)
}
fn read_bounded(path: &Path, maximum: usize) -> Result<Zeroizing<Vec<u8>>> {
    let file = open_regular(path)?;
    let before = file.metadata()?;
    ensure!(before.len() <= maximum as u64, "file budget");
    let mut bytes = Zeroizing::new(Vec::new());
    file.take(maximum as u64 + 1).read_to_end(&mut bytes)?;
    ensure!(bytes.len() <= maximum, "file budget");
    Ok(bytes)
}
fn private_output(path: &Path, bytes: &[u8]) -> Result<()> {
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600).custom_flags(libc::O_NOFOLLOW);
    }
    let mut file = options.open(path)?;
    let result = (|| -> Result<()> {
        file.write_all(bytes)?;
        file.sync_all()?;
        Ok(())
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(path);
    }
    result
}
pub struct SafeFileSystem;
impl SafeFileSystem {
    pub fn encrypt_file(input: &Path, output: &Path, password: &str) -> Result<(), EtpError> {
        fn encrypt(input: &Path, output: &Path, password: &str) -> Result<()> {
            let bytes = read_bounded(input, MAX_FILE)?;
            let (key, context, salt) = CryptoEngine::derive_key(password)?;
            let mut nonce = [0; 12];
            rand::rngs::OsRng.fill_bytes(&mut nonce);
            let mut header = MAGIC.to_vec();
            header.extend_from_slice(&context);
            header.extend_from_slice(&salt);
            header.extend_from_slice(&nonce);
            let total = (bytes.len() + 8 + HEADER + 16)
                .next_power_of_two()
                .max(16384);
            ensure!(total <= MAX_SEALED, "sealed file budget");
            let mut plain = Zeroizing::new(vec![0; total - HEADER - 16]);
            rand::rngs::OsRng.fill_bytes(&mut plain);
            plain[..8].copy_from_slice(&(bytes.len() as u64).to_be_bytes());
            plain[8..8 + bytes.len()].copy_from_slice(&bytes);
            let cipher = ChaCha20Poly1305::new_from_slice(key.as_bytes())
                .map_err(|_| anyhow::anyhow!("key size"))?;
            let sealed = cipher
                .encrypt(
                    (&nonce).into(),
                    Payload {
                        msg: &plain,
                        aad: &header,
                    },
                )
                .map_err(|_| anyhow::anyhow!("file encryption rejected"))?;
            header.extend(sealed);
            private_output(output, &header)
        }
        encrypt(input, output, password).map_err(Into::into)
    }
    pub fn decrypt_file(input: &Path, output: &Path, password: &str) -> Result<(), EtpError> {
        fn decrypt(input: &Path, output: &Path, password: &str) -> Result<()> {
            let bytes = read_bounded(input, MAX_SEALED)?;
            ensure!(
                bytes.len() >= 16384 && bytes.len().is_power_of_two() && &bytes[..8] == MAGIC,
                "version 3 padded SafeFS file required"
            );
            let key = CryptoEngine::restore_key(password, &bytes[8..24], &bytes[24..40])?;
            let cipher = ChaCha20Poly1305::new_from_slice(key.as_bytes())
                .map_err(|_| anyhow::anyhow!("key size"))?;
            let plain = Zeroizing::new(
                cipher
                    .decrypt(
                        chacha20poly1305::Nonce::from_slice(&bytes[40..52]),
                        Payload {
                            msg: &bytes[HEADER..],
                            aad: &bytes[..HEADER],
                        },
                    )
                    .map_err(|_| anyhow::anyhow!("file authentication rejected"))?,
            );
            ensure!(plain.len() >= 8, "file framing");
            let size = u64::from_be_bytes(plain[..8].try_into()?) as usize;
            ensure!(
                size <= MAX_FILE && size <= plain.len() - 8,
                "plaintext budget"
            );
            private_output(output, &plain[8..8 + size])
        }
        decrypt(input, output, password).map_err(Into::into)
    }
    /// Best-effort overwrite and unlink. Filesystem snapshots/SSDs may retain old copies.
    pub fn secure_wipe(path: &Path) -> Result<(), EtpError> {
        fn wipe(path: &Path) -> Result<()> {
            let mut options = OpenOptions::new();
            options.read(true).write(true);
            #[cfg(unix)]
            {
                use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
                options.custom_flags(libc::O_NOFOLLOW);
                let metadata = std::fs::symlink_metadata(path)?;
                ensure!(
                    metadata.uid() == unsafe { libc::geteuid() } && metadata.nlink() == 1,
                    "owned single-link file required"
                );
            }
            let mut file = options.open(path)?;
            let metadata = file.metadata()?;
            ensure!(
                metadata.is_file() && metadata.len() <= MAX_SEALED as u64,
                "bounded regular file required"
            );
            file.seek(SeekFrom::Start(0))?;
            let zero = [0u8; 8192];
            let mut remaining = metadata.len();
            while remaining > 0 {
                let size = remaining.min(zero.len() as u64) as usize;
                file.write_all(&zero[..size])?;
                remaining -= size as u64;
            }
            file.sync_all()?;
            drop(file);
            std::fs::remove_file(path)?;
            Ok(())
        }
        wipe(path).map_err(Into::into)
    }
}
pub struct SystemGuard;
impl SystemGuard {
    /// Checks only local entropy and authenticated-encryption primitives.
    pub fn enforce_security_perimeter() -> Result<(), EtpError> {
        fn check() -> Result<()> {
            let mut key = Zeroizing::new([0u8; 32]);
            rand::rngs::OsRng
                .try_fill_bytes(key.as_mut())
                .map_err(|_| anyhow::anyhow!("OS entropy unavailable"))?;
            let cipher = ChaCha20Poly1305::new_from_slice(key.as_slice())
                .map_err(|_| anyhow::anyhow!("key size"))?;
            let nonce = [0u8; 12];
            let encrypted = cipher
                .encrypt((&nonce).into(), b"self test".as_slice())
                .map_err(|_| anyhow::anyhow!("self test"))?;
            ensure!(
                cipher
                    .decrypt((&nonce).into(), encrypted.as_slice())
                    .map_err(|_| anyhow::anyhow!("self test"))?
                    == b"self test",
                "self test mismatch"
            );
            Ok(())
        }
        check().map_err(Into::into)
    }
}
pub struct SafeMonitor {
    stop: mpsc::Sender<()>,
    healthy: Arc<AtomicBool>,
    task: Option<JoinHandle<()>>,
}
impl SafeMonitor {
    pub fn start() -> Self {
        let (stop, rx) = mpsc::channel();
        let healthy = Arc::new(AtomicBool::new(false));
        let result = healthy.clone();
        let task = thread::spawn(move || loop {
            result.store(
                SystemGuard::enforce_security_perimeter().is_ok(),
                Ordering::Release,
            );
            match rx.recv_timeout(Duration::from_secs(1)) {
                Err(mpsc::RecvTimeoutError::Timeout) => continue,
                _ => break,
            }
        });
        Self {
            stop,
            healthy,
            task: Some(task),
        }
    }
    pub fn stop(&self) {
        let _ = self.stop.send(());
    }
    pub fn healthy(&self) -> bool {
        self.healthy.load(Ordering::Acquire)
    }
}
impl Drop for SafeMonitor {
    fn drop(&mut self) {
        self.stop();
        if let Some(task) = self.task.take() {
            let _ = task.join();
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn padded_password_files_authenticate_and_never_clobber_existing_outputs() {
        let root = std::env::temp_dir().join(format!("etp-sfs-{}", rand::random::<u64>()));
        std::fs::create_dir(&root).unwrap();
        let source = root.join("source");
        let sealed = root.join("sealed");
        let restored = root.join("restored");
        std::fs::write(&source, b"private binary\x80\0\0").unwrap();
        SafeFileSystem::encrypt_file(&source, &sealed, "test password").unwrap();
        let bytes = std::fs::read(&sealed).unwrap();
        assert_eq!(bytes.len(), 16384);
        assert!(!bytes.windows(7).any(|w| w == b"private"));
        SafeFileSystem::decrypt_file(&sealed, &restored, "test password").unwrap();
        assert_eq!(
            std::fs::read(&restored).unwrap(),
            std::fs::read(&source).unwrap()
        );
        assert!(SafeFileSystem::decrypt_file(&sealed, &restored, "test password").is_err());
        let mut tampered = bytes;
        tampered[55] ^= 1;
        std::fs::write(&sealed, tampered).unwrap();
        assert!(
            SafeFileSystem::decrypt_file(&sealed, &root.join("invalid"), "test password").is_err()
        );
        assert!(!root.join("invalid").exists());
        SystemGuard::enforce_security_perimeter().unwrap();
        std::fs::remove_dir_all(root).unwrap();
    }
}
