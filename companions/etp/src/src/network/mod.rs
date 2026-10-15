pub mod discovery;
pub mod node;
pub mod socks5;
pub mod dht;
pub mod nat;

#[cfg(test)]
mod tests_routing;
#[cfg(test)]
mod tests_socks5;