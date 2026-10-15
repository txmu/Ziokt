// etp-core/src/crypto/onion.rs

use anyhow::{anyhow, Context, Result};
use blake3;
use chacha20poly1305::aead::{Aead, Payload};
use chacha20poly1305::{AeadInPlace, ChaCha20Poly1305, KeyInit};
use rand::{Rng, RngCore};
use std::convert::TryInto;
use x25519_dalek::{EphemeralSecret, PublicKey, StaticSecret};
use zeroize::Zeroize; // 建议在 Cargo.toml 添加 zeroize 依赖

// --- 协议常量 ---
const ONION_PROTO_VERSION: u8 = 0x02;
const NONCE_LEN: usize = 12;
const EPHEMERAL_KEY_LEN: usize = 32;
const TAG_LEN: usize = 16;

// 域分离标签 (Domain Separation Tags)
const INFO_KEY_DERIVATION: &str = "ETP-Onion-Layer-Key-v1";
const INFO_NONCE_DERIVATION: &str = "ETP-Onion-Layer-Nonce-v1";

/// Nonce 生成模式
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NonceMode {
    /// 确定性派生：Nonce = HKDF(SharedSecret, Salt).
    /// 优点：节省 12 字节带宽。
    /// 缺点：若 RNG 故障导致 EphemeralKey 重复，则 Nonce 重复，安全性崩塌。
    Derived = 0x00,

    /// 随机生成：Nonce = Random(12).
    /// 优点：即使 EphemeralKey 重复，Nonce 依然唯一，鲁棒性更强。
    /// 缺点：增加 12 字节带宽。
    Random = 0x01,
}

/// 填充策略 (用于隐藏包大小特征)
#[derive(Debug, Clone, Copy)]
pub enum PaddingStrategy {
    /// 不填充 (最大化效率)
    None,
    /// 填充至 N 字节的倍数 (例如 16 或 256)
    BlockAligned(usize),
    /// 填充至固定总大小 (例如 1350 字节，模拟 MTU)
    FixedTotal(usize),
}

/// 洋葱加密配置上下文
#[derive(Debug, Clone)]
pub struct OnionConfig {
    pub nonce_mode: NonceMode,
    pub padding: PaddingStrategy,
}

impl Default for OnionConfig {
    fn default() -> Self {
        Self {
            nonce_mode: NonceMode::Random,
            padding: PaddingStrategy::None,
        }
    }
}

/// 生产级洋葱层加密工具
pub struct OnionCrypto;

impl OnionCrypto {
    /// 封装 (Encapsulate)
    ///
    /// # Wire Format
    /// [ Header (1B) ] [ Ephemeral Pub (32B) ] [ Nonce (0 or 12B) ] [ Ciphertext (Payload + Padding + Tag) ]
    ///
    /// Header Bits:
    /// | 7 6 5 4 | 3 2 1 | 0 |
    /// | Version | Rsrvd | Mode |
    ///
    /// - Version: 0x1 (High 4 bits)
    /// - Mode: 0 = Derived, 1 = Random
    pub fn seal(target_pub_bytes: &[u8], payload: &[u8], config: &OnionConfig) -> Result<Vec<u8>> {
        anyhow::ensure!(payload.len() <= 65536, "onion payload budget");
        // 1. 验证输入
        let target_pub_arr: [u8; 32] = target_pub_bytes
            .try_into()
            .map_err(|_| anyhow!("Invalid target public key length"))?;
        let target_pub = PublicKey::from(target_pub_arr);

        // 2. 生成临时密钥 (Ephemeral Key)
        let mut rng = rand::thread_rng();
        let ephemeral_secret = EphemeralSecret::new(&mut rng);
        let ephemeral_pub = PublicKey::from(&ephemeral_secret);

        // 3. 密钥协商 (ECDH)
        let shared_secret = ephemeral_secret.diffie_hellman(&target_pub);
        anyhow::ensure!(
            shared_secret.was_contributory(),
            "non-contributory X25519 peer rejected"
        );
        let shared_secret_bytes = shared_secret.as_bytes();

        // 4. 派生加密密钥 (KDF)
        let derived_key = derive_key(shared_secret_bytes, INFO_KEY_DERIVATION);
        let cipher = ChaCha20Poly1305::new(&derived_key.into());

        // 5. 准备 Nonce
        let (nonce, nonce_bytes_on_wire) = match config.nonce_mode {
            NonceMode::Derived => {
                let n = derive_nonce(shared_secret_bytes, INFO_NONCE_DERIVATION);
                (n, Vec::new())
            }
            NonceMode::Random => {
                let mut n = [0u8; NONCE_LEN];
                rng.fill_bytes(&mut n);
                (n, n.to_vec())
            }
        };

        // 6. 应用填充 (Padding)
        let padded_payload = apply_padding(payload, config.padding)?;

        // V2 authenticates routing-envelope flags, ephemeral key and nonce.
        let mode_bit = if config.nonce_mode == NonceMode::Random {
            1
        } else {
            0
        };
        let padding_bit = if matches!(config.padding, PaddingStrategy::None) {
            0
        } else {
            2
        };
        let header = (ONION_PROTO_VERSION << 4) | mode_bit | padding_bit;
        let mut output = vec![header];
        output.extend_from_slice(ephemeral_pub.as_bytes());
        output.extend_from_slice(&nonce_bytes_on_wire);
        let ciphertext = cipher
            .encrypt(
                &nonce.into(),
                Payload {
                    msg: &padded_payload,
                    aad: &output,
                },
            )
            .map_err(|_| anyhow!("Onion AEAD encryption failed"))?;
        output.extend(ciphertext);

        // 安全清理
        // shared_secret goes out of scope, but ideally we should zeroize explicit copies if any.

        Ok(output)
    }

    /// 解封装 (Decapsulate)
    ///
    /// 从数据包中解析出临时公钥和模式，计算共享密钥并解密。
    pub fn open(packet: &[u8], my_secret_bytes: &[u8]) -> Result<Vec<u8>> {
        if packet.len() < 1 + 32 + 16 || packet.len() > 65616 {
            // Min: Header + Pub + Tag
            return Err(anyhow!("Packet too short for Onion layer"));
        }

        // 1. 解析 Header
        let header = packet[0];
        let version = (header >> 4) & 0x0F;
        let mode_bit = header & 0x01;

        if version != ONION_PROTO_VERSION || header & 0x0c != 0 {
            return Err(anyhow!("Unsupported Onion version: {}", version));
        }

        let mode = if mode_bit == 0 {
            NonceMode::Derived
        } else {
            NonceMode::Random
        };

        // 2. 提取 Ephemeral Pub Key
        let ephemeral_pub_bytes = &packet[1..33];
        let ephemeral_pub = PublicKey::from(
            TryInto::<[u8; 32]>::try_into(ephemeral_pub_bytes).expect("Slice len is 32"),
        );

        // 3. 提取/派生 Nonce & 定位密文
        let mut offset = 33;

        // ECDH
        let my_secret_arr: [u8; 32] = my_secret_bytes
            .try_into()
            .map_err(|_| anyhow!("Invalid secret key length"))?;
        let my_secret = StaticSecret::from(my_secret_arr);
        let shared_secret = my_secret.diffie_hellman(&ephemeral_pub);
        anyhow::ensure!(
            shared_secret.was_contributory(),
            "non-contributory X25519 peer rejected"
        );
        let shared_secret_bytes = shared_secret.as_bytes();

        let nonce = match mode {
            NonceMode::Derived => derive_nonce(shared_secret_bytes, INFO_NONCE_DERIVATION),
            NonceMode::Random => {
                if packet.len() < offset + NONCE_LEN + TAG_LEN {
                    return Err(anyhow!("Packet too short for Random Nonce"));
                }
                let mut n = [0u8; NONCE_LEN];
                n.copy_from_slice(&packet[offset..offset + NONCE_LEN]);
                offset += NONCE_LEN;
                n
            }
        };

        // 4. AEAD 解密
        let derived_key = derive_key(shared_secret_bytes, INFO_KEY_DERIVATION);
        let cipher = ChaCha20Poly1305::new(&derived_key.into());
        let ciphertext = &packet[offset..];

        let padded_plaintext = cipher
            .decrypt(
                &nonce.into(),
                Payload {
                    msg: ciphertext,
                    aad: &packet[..offset],
                },
            )
            .map_err(|_| anyhow!("Onion decryption integrity check failed"))?;

        // 5. 去除填充
        let plaintext = if header & 2 != 0 {
            remove_padding(&padded_plaintext)?
        } else {
            padded_plaintext
        };

        Ok(plaintext)
    }
}

// --- Helper Functions ---

fn derive_key(secret: &[u8], info: &str) -> [u8; 32] {
    let mut hasher = blake3::Hasher::new_derive_key(info);
    hasher.update(secret);
    hasher.finalize().into()
}

fn derive_nonce(secret: &[u8], info: &str) -> [u8; 12] {
    let mut hasher = blake3::Hasher::new_derive_key(info);
    hasher.update(secret);
    let output = hasher.finalize();
    let mut nonce = [0u8; 12];
    nonce.copy_from_slice(&output.as_bytes()[0..12]);
    nonce
}

/// 应用填充 (ISO/IEC 7816-4: Add 0x80 then 0x00...)
fn apply_padding(data: &[u8], strategy: PaddingStrategy) -> Result<Vec<u8>> {
    let mut output = data.to_vec();

    match strategy {
        PaddingStrategy::None => {}
        PaddingStrategy::BlockAligned(block_size) => {
            if block_size == 0 || block_size > 65536 {
                return Err(anyhow!("Invalid block size 0"));
            }
            // ISO 7816-4 padding: Append 0x80, then 0x00 until aligned
            output.push(0x80);
            while output.len() % block_size != 0 {
                output.push(0x00);
            }
        }
        PaddingStrategy::FixedTotal(total_size) => {
            // Include payload + 1 byte padding marker (0x80)
            if data.len() + 1 > total_size || total_size > 65536 {
                return Err(anyhow!("Payload too large for fixed size padding"));
            }
            output.push(0x80);
            while output.len() < total_size {
                output.push(0x00);
            }
        }
    }
    Ok(output)
}

/// 去除填充
fn remove_padding(data: &[u8]) -> Result<Vec<u8>> {
    let end = data
        .iter()
        .rposition(|byte| *byte != 0)
        .ok_or_else(|| anyhow!("missing padding marker"))?;
    anyhow::ensure!(data[end] == 0x80, "invalid padding marker");
    Ok(data[..end].to_vec())
}

// --- 单元测试 ---
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_onion_crypto_lifecycle_derived() {
        let alice_secret = StaticSecret::random_from_rng(&mut rand::thread_rng());
        let alice_pub = PublicKey::from(&alice_secret);

        let msg = b"Hello Onion World";
        let config = OnionConfig {
            nonce_mode: NonceMode::Derived,
            padding: PaddingStrategy::None,
        };

        // Seal
        let packet = OnionCrypto::seal(alice_pub.as_bytes(), msg, &config).unwrap();

        // Open
        let decrypted = OnionCrypto::open(&packet, alice_secret.to_bytes().as_slice()).unwrap();

        assert_eq!(msg.to_vec(), decrypted);
    }

    #[test]
    fn test_onion_crypto_lifecycle_random_padded() {
        let alice_secret = StaticSecret::random_from_rng(&mut rand::thread_rng());
        let alice_pub = PublicKey::from(&alice_secret);

        let msg = b"Secret Message";
        let config = OnionConfig {
            nonce_mode: NonceMode::Random,
            // Align to 64 bytes
            padding: PaddingStrategy::BlockAligned(64),
        };

        // Seal
        let packet = OnionCrypto::seal(alice_pub.as_bytes(), msg, &config).unwrap();

        // Check size: Header(1) + Pub(32) + Nonce(12) + Tag(16) + PaddedPayload
        // Payload "Secret Message" (14) -> Pad to 64: 14 + 1(0x80) + 49(0x00) = 64
        // Total = 1 + 32 + 12 + 16 + 64 = 125
        assert_eq!(packet.len(), 125);

        // Open
        let decrypted = OnionCrypto::open(&packet, alice_secret.to_bytes().as_slice()).unwrap();

        assert_eq!(msg.to_vec(), decrypted);
    }

    #[test]
    fn test_padding_logic() {
        let data = vec![0x11, 0x22];

        // Test Block Aligned
        let padded = apply_padding(&data, PaddingStrategy::BlockAligned(8)).unwrap();
        // Expect: 11 22 80 00 00 00 00 00 (8 bytes)
        assert_eq!(padded, vec![0x11, 0x22, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00]);
        let unpadded = remove_padding(&padded).unwrap();
        assert_eq!(unpadded, data);

        // Test No Padding
        assert!(remove_padding(&data).is_err());
    }
}

#[cfg(test)]
mod regression_tests {
    use super::*;
    #[test]
    fn binary_suffix_padding_flags_and_low_order_keys() {
        let secret = StaticSecret::random_from_rng(rand::rngs::OsRng);
        let public = PublicKey::from(&secret);
        for nonce_mode in [NonceMode::Derived, NonceMode::Random] {
            for padding in [
                PaddingStrategy::None,
                PaddingStrategy::BlockAligned(32),
                PaddingStrategy::FixedTotal(64),
            ] {
                for data in [vec![], vec![0x80], vec![1, 0x80, 0, 0], vec![0; 32]] {
                    let config = OnionConfig {
                        nonce_mode,
                        padding,
                    };
                    let sealed = OnionCrypto::seal(public.as_bytes(), &data, &config).unwrap();
                    assert_eq!(
                        OnionCrypto::open(&sealed, &secret.to_bytes()).unwrap(),
                        data
                    );
                    let mut altered = sealed.clone();
                    altered[0] ^= 2;
                    assert!(OnionCrypto::open(&altered, &secret.to_bytes()).is_err());
                }
            }
        }
        assert!(OnionCrypto::seal(&[0; 32], b"payload", &OnionConfig::default()).is_err());
    }
}
