//! Noise IK sessions with explicit authenticated transport nonces for lossy P2P.
use anyhow::{anyhow, ensure, Result};
use snow::{Builder, HandshakeState, TransportState};
use zeroize::Zeroize;
const NOISE_PATTERN: &str = "Noise_IK_25519_ChaChaPoly_BLAKE2s";

#[derive(Clone)]
pub struct KeyPair {
    pub public: Vec<u8>,
    pub private: Vec<u8>,
}
impl Drop for KeyPair {
    fn drop(&mut self) {
        self.private.zeroize();
    }
}
impl KeyPair {
    pub fn generate() -> Self {
        let pair = Builder::new(NOISE_PATTERN.parse().expect("fixed Noise pattern"))
            .generate_keypair()
            .expect("OS entropy required");
        Self {
            public: pair.public,
            private: pair.private,
        }
    }
}
pub enum NoiseSession {
    Handshaking(HandshakeState),
    Transport {
        state: TransportState,
        highest: Option<u64>,
        seen: u128,
        #[cfg(test)]
        binding: Vec<u8>,
    },
    Failed,
}
impl NoiseSession {
    pub fn new_initiator(local: &KeyPair, remote: &[u8]) -> Result<Self> {
        ensure!(
            local.private.len() == 32 && remote.len() == 32 && remote.iter().any(|b| *b != 0),
            "explicit Noise peer key required"
        );
        Ok(Self::Handshaking(
            Builder::new(NOISE_PATTERN.parse()?)
                .local_private_key(&local.private)
                .remote_public_key(remote)
                .build_initiator()?,
        ))
    }
    pub fn new_responder(local: &KeyPair) -> Result<Self> {
        ensure!(local.private.len() == 32, "invalid Noise private key");
        Ok(Self::Handshaking(
            Builder::new(NOISE_PATTERN.parse()?)
                .local_private_key(&local.private)
                .build_responder()?,
        ))
    }
    fn finish(&mut self) -> Result<()> {
        let old = std::mem::replace(self, Self::Failed);
        let Self::Handshaking(state) = old else {
            return Err(anyhow!("handshake not active"));
        };
        #[cfg(test)]
        let binding = state.get_handshake_hash().to_vec();
        *self = Self::Transport {
            #[cfg(test)]
            binding,
            state: state.into_transport_mode()?,
            highest: None,
            seen: 0,
        };
        Ok(())
    }
    pub fn write_handshake_message(
        &mut self,
        payload: &[u8],
        out: &mut [u8],
    ) -> Result<(usize, bool)> {
        let Self::Handshaking(state) = self else {
            return Err(anyhow!("handshake not active"));
        };
        let len = state.write_message(payload, out)?;
        let done = state.is_handshake_finished();
        if done {
            self.finish()?;
        }
        Ok((len, done))
    }
    pub fn read_handshake_message(
        &mut self,
        input: &[u8],
        out: &mut [u8],
    ) -> Result<(usize, bool)> {
        let Self::Handshaking(state) = self else {
            return Err(anyhow!("handshake not active"));
        };
        let len = state.read_message(input, out)?;
        let done = state.is_handshake_finished();
        if done {
            self.finish()?;
        }
        Ok((len, done))
    }
    #[cfg(test)]
    pub(crate) fn diagnostic_state(&self) -> String {
        match self {
            Self::Transport { state, highest, binding, .. } => format!("binding={:02x?}, send_nonce={}, recv_nonce={:?}", &binding[..binding.len().min(8)], state.sending_nonce(), highest),
            Self::Handshaking(_) => "handshaking".into(),
            Self::Failed => "failed".into(),
        }
    }

    pub fn encrypt(&mut self, plaintext: &[u8], out: &mut [u8]) -> Result<usize> {
        let Self::Transport { state, .. } = self else {
            return Err(anyhow!("handshake incomplete"));
        };
        ensure!(
            out.len() >= plaintext.len().saturating_add(24),
            "transport output too short"
        );
        let nonce = state.sending_nonce();
        ensure!(
            nonce < u64::MAX,
            "session nonce exhausted; authenticated reconnect required"
        );
        out[..8].copy_from_slice(&nonce.to_be_bytes());
        Ok(8 + state.write_message(plaintext, &mut out[8..])?)
    }
    pub fn decrypt(&mut self, input: &[u8], out: &mut [u8]) -> Result<usize> {
        ensure!(input.len() >= 24, "truncated transport record");
        let Self::Transport {
            state,
            highest,
            seen,
            ..
        } = self
        else {
            return Err(anyhow!("handshake incomplete"));
        };
        let nonce = u64::from_be_bytes(input[..8].try_into()?);
        ensure!(nonce < u64::MAX, "invalid transport nonce");
        if let Some(top) = *highest {
            if nonce <= top {
                let delta = top - nonce;
                ensure!(
                    delta < 128 && (*seen & (1u128 << delta)) == 0,
                    "replayed or stale transport record"
                );
            }
        }
        state.set_receiving_nonce(nonce);
        let len = state.read_message(&input[8..], out)?;
        // Authentication succeeds before the replay window advances.
        match *highest {
            None => {
                *highest = Some(nonce);
                *seen = 1;
            }
            Some(top) if nonce > top => {
                let delta = nonce - top;
                *seen = if delta >= 128 {
                    1
                } else {
                    (*seen << delta) | 1
                };
                *highest = Some(nonce);
            }
            Some(top) => *seen |= 1u128 << (top - nonce),
        }
        Ok(len)
    }
    pub fn get_remote_static(&self) -> Option<&[u8]> {
        match self {
            Self::Handshaking(s) => s.get_remote_static(),
            Self::Transport { state, .. } => state.get_remote_static(),
            Self::Failed => None,
        }
    }
    /// Only for explicitly coordinated peers. Engine rotation uses a fresh IK handshake.
    pub fn rekey(&mut self) -> Result<()> {
        match self {
            Self::Transport { state, .. } => {
                state.rekey_outgoing();
                state.rekey_incoming();
                Ok(())
            }
            _ => Err(anyhow!("handshake incomplete")),
        }
    }
}
