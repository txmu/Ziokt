use super::socks5::{RuleBasedRouter, Socks5Server};
use std::{net::SocketAddr, sync::Arc, time::Duration};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    sync::mpsc,
};
#[tokio::test]
async fn socks5_routes_framed_stream_and_receives_reply() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let exit: SocketAddr = "127.0.0.1:18081".parse().unwrap();
    let (tx, mut rx) = mpsc::channel(16);
    let (down_tx, down_rx) = mpsc::channel(16);
    let server = Socks5Server::new(
        address.to_string(),
        tx,
        Arc::new(RuleBasedRouter::new(vec![exit])),
        8,
    );
    let task = tokio::spawn(server.run_with_listener(listener, down_rx));
    let exchange = async {
        let mut socket = TcpStream::connect(address).await.unwrap();
        socket.write_all(&[5, 1, 0]).await.unwrap();
        let mut greeting = [0; 2];
        socket.read_exact(&mut greeting).await.unwrap();
        assert_eq!(greeting, [5, 0]);
        socket
            .write_all(&[5, 1, 0, 1, 127, 0, 0, 1, 0, 80])
            .await
            .unwrap();
        let mut reply = [0; 10];
        socket.read_exact(&mut reply).await.unwrap();
        assert_eq!(reply[1], 0);
        let (peer, stream, metadata, closed) = rx.recv().await.unwrap();
        assert_eq!(peer, exit);
        assert_eq!(metadata[0], 1);
        assert!(!closed);
        socket.write_all(b"sealed bytes").await.unwrap();
        let (peer, id, data, closed) = rx.recv().await.unwrap();
        assert_eq!((peer, id), (exit, stream));
        assert_eq!(data, b"sealed bytes");
        assert!(!closed);
        down_tx
            .send((exit, stream, b"reply".to_vec()))
            .await
            .unwrap();
        let mut received = [0; 5];
        socket.read_exact(&mut received).await.unwrap();
        assert_eq!(&received, b"reply");
    };
    tokio::time::timeout(Duration::from_secs(3), exchange)
        .await
        .unwrap();
    task.abort();
}
