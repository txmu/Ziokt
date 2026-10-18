// ==============================================================================
// Ziokt Unified Graphical Client - Tauri 2 Native Core Library
// ==============================================================================

use serde::{Deserialize, Serialize};
use std::time::Instant;

#[derive(Serialize, Deserialize, Debug)]
pub struct SystemInfo {
    pub os: String,
    pub arch: String,
    pub client_version: String,
    pub cores: usize,
    pub native_engine: String,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct ComponentStatus {
    pub name: String,
    pub status: String,
    pub port: u16,
    pub message: String,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct PingResult {
    pub endpoint: String,
    pub latency_ms: u64,
    pub reachable: bool,
}

#[tauri::command]
fn get_system_info() -> SystemInfo {
    SystemInfo {
        os: std::env::consts::OS.to_string(),
        arch: std::env::consts::ARCH.to_string(),
        client_version: env!("CARGO_PKG_VERSION").to_string(),
        cores: std::thread::available_parallelism()
            .map(|n| n.get())
            .unwrap_or(1),
        native_engine: "Tauri 2 + Rust Core".to_string(),
    }
}

#[tauri::command]
async fn manage_component(name: String, action: String) -> Result<ComponentStatus, String> {
    let (unit, port) = match name.as_str() {
        "corium" => ("ziokt-corium-consensus.service", 8545),
        "shadow6" => ("shadow6-cluster.service", 8186),
        "ufs" => ("ziokt-gateway.service", 8185),
        "watchat" => ("ziokt-watchat.service", 8181),
        "etp" => ("ziokt-etp.service", 9050),
        _ => return Err("Unknown component".into()),
    };
    if !["start", "stop", "status"].contains(&action.as_str()) { return Err("Invalid action".into()); }
    if !cfg!(target_os = "linux") { return Err("Local service management requires Linux systemd; use the configured native gateway on this platform".into()); }
    if action != "status" {
        let mut command = tokio::process::Command::new("systemctl");
        command.args(["--no-ask-password", &action, unit]).kill_on_drop(true);
        let result = tokio::time::timeout(std::time::Duration::from_secs(20), command.output()).await
            .map_err(|_| "Service operation timed out")?.map_err(|_| "Cannot invoke system service manager")?;
        if !result.status.success() { return Err("Service operation rejected; verify installed unit and local privileges".into()); }
    }
    let mut command = tokio::process::Command::new("systemctl");
    command.args(["is-active", unit]).kill_on_drop(true);
    let result = tokio::time::timeout(std::time::Duration::from_secs(5), command.output()).await
        .map_err(|_| "Service status timed out")?.map_err(|_| "Cannot read service status")?;
    let state = String::from_utf8_lossy(&result.stdout).trim().to_string();
    if state.is_empty() { return Err("Service state unavailable".into()); }
    Ok(ComponentStatus { name, status: state, port, message: format!("Observed systemd unit {}", unit) })
}

#[tauri::command]
async fn ping_gateway(endpoint: String) -> Result<PingResult, String> {
    let url = tauri::Url::parse(&endpoint).map_err(|_| "Invalid gateway URL")?;
    if !["https", "http"].contains(&url.scheme()) || !url.username().is_empty() || url.password().is_some() {
        return Err("HTTP(S) URL without embedded credentials required".into());
    }
    let host = url.host_str().ok_or("Gateway host required")?;
    let port = url.port_or_known_default().ok_or("Gateway port required")?;
    let start = Instant::now();
    let reachable = matches!(tokio::time::timeout(std::time::Duration::from_secs(4), tokio::net::TcpStream::connect((host, port))).await, Ok(Ok(_)));
    Ok(PingResult { endpoint: endpoint.clone(), latency_ms: start.elapsed().as_millis() as u64, reachable })
}

#[tauri::command]
fn send_native_notification(_title: String, _body: String) -> Result<(), String> {
    Err("Native notification provider is not configured".into())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            get_system_info,
            manage_component,
            ping_gateway,
            send_native_notification
        ])
        .run(tauri::generate_context!())
        .expect("error while running ziokt client application");
}

#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    async fn ping_observes_actual_socket_and_failures() {
        let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let endpoint=format!("http://{}",listener.local_addr().unwrap());
        assert!(ping_gateway(endpoint.clone()).await.unwrap().reachable);
        drop(listener);
        assert!(!ping_gateway(endpoint).await.unwrap().reachable);
        assert!(ping_gateway("file:///etc/passwd".into()).await.is_err());
        assert!(ping_gateway("https://user:secret@example.com".into()).await.is_err());
    }
    #[tokio::test]
    async fn lifecycle_rejects_unlisted_components_and_actions() {
        assert!(manage_component("shell;id".into(),"start".into()).await.is_err());
        assert!(manage_component("corium".into(),"exec".into()).await.is_err());
    }
}
