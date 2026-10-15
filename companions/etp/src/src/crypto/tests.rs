// 文件: etp-core/src/crypto/tests.rs

use super::noise::{KeyPair, NoiseSession};
use crate::wire::frame::Frame;
use crate::wire::packet::{DecryptedPacket, RawPacket};

#[test]
fn test_crypto_handshake_and_transport() {
    println!("--- Starting Crypto Handshake Test ---");

    // 1. 生成身份
    let server_keys = KeyPair::generate();
    let client_keys = KeyPair::generate();

    // 2. 初始化会话
    let mut client_session =
        NoiseSession::new_initiator(&client_keys, &server_keys.public).unwrap();
    let mut server_session = NoiseSession::new_responder(&server_keys).unwrap();

    let mut buf_1 = vec![0u8; 65535];
    let mut buf_2 = vec![0u8; 65535];

    // --- 握手阶段 (Noise IK) ---
    // Client -> Server
    let (len, _) = client_session
        .write_handshake_message(&[], &mut buf_1)
        .unwrap();
    // Server <- Client
    let (len, _) = server_session
        .read_handshake_message(&buf_1[..len], &mut buf_2)
        .unwrap();

    // Server -> Client
    let (len, _) = server_session
        .write_handshake_message(&[], &mut buf_1)
        .unwrap();
    // Client <- Server
    let (_, client_done) = client_session
        .read_handshake_message(&buf_1[..len], &mut buf_2)
        .unwrap();

    assert!(client_done, "Handshake should be finished");

    // --- 传输阶段 ---
    let mut packet = DecryptedPacket::new(100, 1);
    packet.add_frame(Frame::Stream {
        stream_id: 1,
        offset: 0,
        fin: false,
        data: b"Secret Data".to_vec(),
    });

    // 客户端加密
    let raw_packet = RawPacket::encrypt_and_seal(
        &packet,
        &mut client_session,
        Some(200),
        &crate::plugin::StandardDialect,
    )
    .unwrap();

    // 服务端解密
    // 注意：服务端也需要是 Transport 模式，上面的 read_handshake_message 应该已经转换了状态
    // 我们在这里做一个简单的模拟，因为单元测试里我们要确保 server_session 也是 ready 的
    // 在上面的代码里 server_session 在 write_handshake_message 后就 finished 了

    let received_logic = RawPacket::unseal_and_decrypt(
        &raw_packet.data,
        &mut server_session,
        &crate::plugin::StandardDialect,
    )
    .unwrap();

    if let Frame::Stream { data, .. } = &received_logic.frames()[0] {
        assert_eq!(data, b"Secret Data");
    } else {
        panic!("Wrong frame type");
    }
}

#[test]
fn lossy_transport_authenticates_nonce_and_rejects_replay() {
    let a = KeyPair::generate();
    let b = KeyPair::generate();
    let mut client = NoiseSession::new_initiator(&a, &b.public).unwrap();
    let mut server = NoiseSession::new_responder(&b).unwrap();
    let mut buffer = [0u8; 1024];
    let mut out = [0u8; 1024];
    let (n, _) = client.write_handshake_message(&[], &mut buffer).unwrap();
    server
        .read_handshake_message(&buffer[..n], &mut out)
        .unwrap();
    let (n, _) = server.write_handshake_message(&[], &mut buffer).unwrap();
    client
        .read_handshake_message(&buffer[..n], &mut out)
        .unwrap();
    let mut records = Vec::new();
    for i in 0..3u8 {
        let n = client.encrypt(&[i], &mut buffer).unwrap();
        records.push(buffer[..n].to_vec());
    }
    assert_eq!(server.decrypt(&records[2], &mut out).unwrap(), 1);
    assert_eq!(out[0], 2);
    assert!(server.decrypt(&records[2], &mut out).is_err());
    let mut forged = records[1].clone();
    forged[0] ^= 1;
    assert!(server.decrypt(&forged, &mut out).is_err());
    assert_eq!(server.decrypt(&records[0], &mut out).unwrap(), 1);
    assert_eq!(out[0], 0);
    assert_eq!(server.decrypt(&records[1], &mut out).unwrap(), 1);
    assert_eq!(out[0], 1);
    assert!(server.decrypt(&records[0], &mut out).is_err());
}
