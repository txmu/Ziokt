//! Bounded, pinned read-only RPC. No proxies, redirects, credentials or write methods.
use anyhow::{ensure, Result};
use serde_json::{json, Value};
use std::time::Duration;
#[derive(Clone)]
pub struct ReadOnlyRpc {
    endpoint: reqwest::Url,
    client: reqwest::Client,
}
impl ReadOnlyRpc {
    pub fn validate_endpoint(endpoint: &str) -> Result<reqwest::Url> {
        let url = reqwest::Url::parse(endpoint)?;
        let local = url
            .host_str()
            .and_then(|h| h.trim_matches(['[', ']']).parse::<std::net::IpAddr>().ok())
            .map(|ip| ip.is_loopback())
            .unwrap_or(false);
        ensure!(
            (url.scheme() == "https" || url.scheme() == "http" && local)
                && url.username().is_empty()
                && url.password().is_none()
                && url.fragment().is_none(),
            "HTTPS or literal loopback HTTP RPC required"
        );
        Ok(url)
    }
    pub fn new(endpoint: &str, timeout: Duration) -> Result<Self> {
        ensure!(
            timeout > Duration::ZERO && timeout <= Duration::from_secs(30),
            "RPC deadline"
        );
        Ok(Self {
            endpoint: Self::validate_endpoint(endpoint)?,
            client: reqwest::Client::builder()
                .no_proxy()
                .redirect(reqwest::redirect::Policy::none())
                .timeout(timeout)
                .build()?,
        })
    }
    pub async fn call(&self, method: &str, params: Value) -> Result<Value> {
        ensure!(
            matches!(method, "eth_call" | "eth_chainId" | "eth_getCode"),
            "only fixed read operations allowed"
        );
        ensure!(
            params.is_array() && serde_json::to_vec(&params)?.len() <= 16384,
            "RPC parameters budget"
        );
        let mut response = self
            .client
            .post(self.endpoint.clone())
            .json(&json!({"jsonrpc":"2.0","id":1,"method":method,"params":params}))
            .send()
            .await?
            .error_for_status()?;
        let mut bytes = Vec::new();
        while let Some(chunk) = response.chunk().await? {
            ensure!(bytes.len() + chunk.len() <= 131072, "RPC reply budget");
            bytes.extend_from_slice(&chunk);
        }
        let value: Value = serde_json::from_slice(&bytes)?;
        ensure!(
            value.get("jsonrpc") == Some(&json!("2.0"))
                && value.get("id") == Some(&json!(1))
                && value.get("error").is_none(),
            "RPC envelope rejected"
        );
        Ok(value
            .get("result")
            .ok_or_else(|| anyhow::anyhow!("missing RPC result"))?
            .clone())
    }
    pub async fn eth_call(&self, address: &str, data: &[u8]) -> Result<Vec<u8>> {
        ensure!(
            address.len() == 42
                && address.starts_with("0x")
                && address[2..].bytes().all(|b| b.is_ascii_hexdigit())
                && data.len() <= 8192,
            "bounded address and calldata required"
        );
        let value = self
            .call(
                "eth_call",
                json!([{"to":address,"data":format!("0x{}",hex::encode(data))},"latest"]),
            )
            .await?;
        let text = value
            .as_str()
            .ok_or_else(|| anyhow::anyhow!("hex result required"))?;
        ensure!(
            text.starts_with("0x") && text.len() <= 65538,
            "hex reply budget"
        );
        Ok(hex::decode(&text[2..])?)
    }
    #[cfg(feature = "ens-gateway")]
    pub async fn get_ens_text_record(&self, name: &str, key: &str) -> Result<String> {
        use sha3::{Digest, Keccak256};
        ensure!(
            name.len() <= 253
                && name.contains('.')
                && name.is_ascii()
                && name.split('.').all(|part| !part.is_empty()
                    && part.len() <= 63
                    && part.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-'))
                && !key.is_empty()
                && key.len() <= 255,
            "bounded ASCII ENS name and text key required"
        );
        let mut node = [0u8; 32];
        for part in name.to_ascii_lowercase().split('.').rev() {
            let label = Keccak256::digest(part.as_bytes());
            let mut hash = Keccak256::new();
            hash.update(node);
            hash.update(label);
            node = hash.finalize().into();
        }
        let mut request = Keccak256::digest(b"resolver(bytes32)")[..4].to_vec();
        request.extend_from_slice(&node);
        let result = self
            .eth_call("0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e", &request)
            .await?;
        ensure!(
            result.len() == 32
                && result[..12].iter().all(|b| *b == 0)
                && result[12..].iter().any(|b| *b != 0),
            "ENS resolver unavailable"
        );
        let resolver = format!("0x{}", hex::encode(&result[12..]));
        let mut request = Keccak256::digest(b"text(bytes32,string)")[..4].to_vec();
        request.extend_from_slice(&node);
        let mut offset = [0; 32];
        offset[31] = 64;
        request.extend_from_slice(&offset);
        let mut length = [0; 32];
        length[31] = key.len() as u8;
        request.extend_from_slice(&length);
        request.extend_from_slice(key.as_bytes());
        request.resize(4 + 96 + key.len().div_ceil(32) * 32, 0);
        let result = self.eth_call(&resolver, &request).await?;
        fn word(data: &[u8]) -> Result<usize> {
            ensure!(
                data.len() == 32 && data[..24].iter().all(|b| *b == 0),
                "bounded ABI word"
            );
            Ok(u64::from_be_bytes(data[24..].try_into()?) as usize)
        }
        ensure!(result.len() >= 64, "short ENS text result");
        let offset = word(&result[..32])?;
        ensure!(offset == 32, "unexpected ENS ABI offset");
        let size = word(&result[32..64])?;
        ensure!(size <= 4096 && size <= result.len() - 64, "ENS text budget");
        Ok(std::str::from_utf8(&result[64..64 + size])?.to_owned())
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rpc_rejects_plaintext_public_and_credential_urls() {
        for endpoint in [
            "http://example.org",
            "file:///etc/passwd",
            "https://user:password@example.org",
            "https://example.org/#fragment",
        ] {
            assert!(ReadOnlyRpc::validate_endpoint(endpoint).is_err());
        }
        assert!(ReadOnlyRpc::validate_endpoint("http://127.0.0.1:8545").is_ok());
    }
    #[tokio::test]
    async fn write_methods_are_refused_before_network_io() {
        let rpc = ReadOnlyRpc::new("http://127.0.0.1:1", Duration::from_secs(1)).unwrap();
        assert!(rpc.call("eth_sendRawTransaction", json!([])).await.is_err());
    }
}
