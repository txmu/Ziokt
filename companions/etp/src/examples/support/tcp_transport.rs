//! Bounded native packet carriage for networks where direct UDP is unavailable.
//! Native Noise, onion encryption, peer pins and replay checks remain in EtpEngine.
use etp_core::network::node::PacketTransport;
use std::{collections::HashSet, io, net::SocketAddr, sync::Arc, time::Duration};
use tokio::{io::{AsyncReadExt, AsyncWriteExt}, net::{TcpListener,TcpStream}, sync::{mpsc,Mutex,Semaphore}, time::timeout};
const MAX_PACKET:usize=65535;
#[derive(Debug)]
pub struct TcpPacketTransport {
    local:SocketAddr,
    peers:Arc<HashSet<SocketAddr>>,
    incoming:Mutex<mpsc::Receiver<(Vec<u8>,SocketAddr)>>,
    listener:tokio::task::JoinHandle<()>,
}
impl TcpPacketTransport {
    pub async fn bind(local:SocketAddr,peers:HashSet<SocketAddr>)->io::Result<Self> {
        let socket=TcpListener::bind(local).await?;
        let local=socket.local_addr()?;
        let peers=Arc::new(peers);let allowed=peers.clone();
        let (send,receive)=mpsc::channel(128);let slots=Arc::new(Semaphore::new(32));
        let listener=tokio::spawn(async move {
            loop {
                let Ok((mut stream,source))=socket.accept().await else {break};
                if !allowed.iter().any(|peer|peer.ip()==source.ip()) {continue}
                let Ok(slot)=slots.clone().try_acquire_owned() else {continue};
                let send=send.clone();let allowed=allowed.clone();
                tokio::spawn(async move {
                    let _slot=slot;
                    let _=timeout(Duration::from_secs(3),async {
                        let mut header=[0u8;6];stream.read_exact(&mut header).await?;
                        let port=u16::from_be_bytes([header[0],header[1]]);
                        let size=u32::from_be_bytes([header[2],header[3],header[4],header[5]]) as usize;
                        let peer=SocketAddr::new(source.ip(),port);
                        if !allowed.contains(&peer) || size==0 || size>MAX_PACKET {return Err(io::Error::new(io::ErrorKind::InvalidData,"unapproved peer or packet budget"))}
                        let mut body=vec![0;size];stream.read_exact(&mut body).await?;
                        send.try_send((body,peer)).map_err(|_|io::Error::new(io::ErrorKind::WouldBlock,"packet queue full"))
                    }).await;
                });
            }
        });
        Ok(Self{local,peers,incoming:Mutex::new(receive),listener})
    }
}
impl Drop for TcpPacketTransport { fn drop(&mut self){self.listener.abort();} }
#[async_trait::async_trait]
impl PacketTransport for TcpPacketTransport {
    async fn send_to(&self,body:&[u8],target:SocketAddr)->io::Result<usize> {
        if !self.peers.contains(&target) || body.is_empty() || body.len()>MAX_PACKET {return Err(io::Error::new(io::ErrorKind::InvalidInput,"unapproved peer or packet budget"))}
        timeout(Duration::from_secs(3),async {
            let mut stream=TcpStream::connect(target).await?;stream.set_nodelay(true)?;
            stream.write_u16(self.local.port()).await?;stream.write_u32(body.len() as u32).await?;
            stream.write_all(body).await?;stream.shutdown().await?;Ok(body.len())
        }).await.map_err(|_|io::Error::new(io::ErrorKind::TimedOut,"TCP packet send timeout"))?
    }
    async fn recv_from(&self,body:&mut [u8])->io::Result<(usize,SocketAddr)> {
        let Some((packet,peer))=self.incoming.lock().await.recv().await else {return Err(io::Error::new(io::ErrorKind::UnexpectedEof,"packet listener stopped"))};
        if packet.len()>body.len(){return Err(io::Error::new(io::ErrorKind::InvalidData,"receive buffer budget"))}
        body[..packet.len()].copy_from_slice(&packet);Ok((packet.len(),peer))
    }
    fn local_addr(&self)->io::Result<SocketAddr> {Ok(self.local)}
}

#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    async fn actual_tcp_packets_preserve_both_endpoint_ports_and_bounds() {
        let reserve_a=std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let reserve_b=std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let a_address=reserve_a.local_addr().unwrap();let b_address=reserve_b.local_addr().unwrap();
        drop(reserve_a);drop(reserve_b);
        let a=TcpPacketTransport::bind(a_address,HashSet::from([b_address])).await.unwrap();
        let b=TcpPacketTransport::bind(b_address,HashSet::from([a_address])).await.unwrap();
        let message=vec![37;16384];a.send_to(&message,b_address).await.unwrap();
        let mut data=vec![0;65535];
        let (size,peer)=timeout(Duration::from_secs(2),b.recv_from(&mut data)).await.unwrap().unwrap();
        assert_eq!(peer,a_address);assert_eq!(&data[..size],message.as_slice());
        b.send_to(b"reply",a_address).await.unwrap();
        let (size,peer)=timeout(Duration::from_secs(2),a.recv_from(&mut data)).await.unwrap().unwrap();
        assert_eq!(peer,b_address);assert_eq!(&data[..size],b"reply");
        assert!(a.send_to(&vec![0;65536],b_address).await.is_err());
        assert!(a.send_to(b"x","127.0.0.1:9".parse().unwrap()).await.is_err());
    }
}
