'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const net = require('node:net');
const { spawn } = require('node:child_process');
const { WebSocket } = require('ws');
const { TransportManager } = require('../backend/transports/TransportManager');
const { ZioktP2PTransport } = require('../backend/transports/ZioktP2PTransport');
const { ZioktMultihopTransport } = require('../backend/transports/ZioktMultihopTransport');
const { WatchatServerTransport } = require('../backend/transports/WatchatServerTransport');
const { Shadow6Transport } = require('../backend/transports/Shadow6Transport');
const { EtpTransport } = require('../backend/transports/EtpTransport');

const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

async function freePort() {
  const server = net.createServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  return port;
}

test('Five communication modes and unified TransportManager unit verification', async t => {
  const tm = new TransportManager();
  t.after(() => tm.close());

  const modes = tm.getAllModesStatus();
  assert.equal(modes.length, 5);
  const ids = modes.map(m => m.id).sort();
  assert.deepEqual(ids, ['etp', 'shadow6', 'watchat-server', 'ziokt-multihop', 'ziokt-p2p'].sort());

  // Mode: WATChat Server (DEFAULT)
  assert.equal(tm.getUserMode('user-1'), 'watchat-server');
  const envDefault = {
    id: crypto.randomUUID(),
    from: 'user-1',
    to: 'user-2',
    kind: 'sealed',
    ciphertext: crypto.randomBytes(2048).toString('base64'),
    nonce: crypto.randomUUID()
  };
  const resDefault = await tm.routeMessage(envDefault);
  assert.equal(resDefault.transport, 'watchat-server');
  assert.equal(resDefault.hops, 1);
  assert.equal(resDefault.state, 'node');

  // Mode 1: Ziokt P2P Single-Hop
  const envP2P = {
    id: crypto.randomUUID(),
    from: 'user-1',
    to: 'user-2',
    kind: 'sealed',
    ciphertext: crypto.randomBytes(2048).toString('base64'),
    nonce: crypto.randomUUID()
  };
  const resP2P = await tm.routeMessage(envP2P, 'ziokt-p2p');
  assert.equal(resP2P.transport, 'ziokt-p2p');
  assert.equal(resP2P.hops, 1);
  assert.equal(resP2P.direct, true);
  assert.equal(resP2P.state, 'node');

  // Mode 2: Ziokt P2P Multi-Hop
  const envMulti = {
    id: crypto.randomUUID(),
    from: 'user-1',
    to: 'user-2',
    kind: 'sealed',
    ciphertext: crypto.randomBytes(2048).toString('base64'),
    hops: 3,
    nonce: crypto.randomUUID()
  };
  const resMulti = await tm.routeMessage(envMulti, 'ziokt-multihop');
  assert.equal(resMulti.transport, 'ziokt-multihop');
  assert.equal(resMulti.hops, 3);
  assert.equal(resMulti.state, 'node');

  // Mode 3: WATChat Native Server
  let serverDelivered = null;
  tm.getTransport('watchat-server').setSender((recipientId, env) => {
    serverDelivered = { recipientId, env };
  });
  const envServer = {
    id: crypto.randomUUID(),
    from: 'user-1',
    to: 'user-2',
    kind: 'sealed',
    ciphertext: crypto.randomBytes(2048).toString('base64'),
    nonce: crypto.randomUUID()
  };
  const resServer = await tm.routeMessage(envServer, 'watchat-server');
  assert.equal(resServer.transport, 'watchat-server');
  assert.equal(resServer.hops, 1);
  assert.ok(serverDelivered && serverDelivered.recipientId === 'user-2');

  // Mode 4: Shadow6 Native Transport
  const envShadow = {
    id: crypto.randomUUID(),
    from: 'user-1',
    to: 'user-2',
    kind: 'sealed',
    ciphertext: crypto.randomBytes(2048).toString('base64'),
    nonce: crypto.randomUUID()
  };
  const resShadow = await tm.routeMessage(envShadow, 'shadow6');
  assert.equal(resShadow.transport, 'shadow6');
  assert.equal(resShadow.hops, 1);

  // Mode 5: ETP Native Transport
  const envEtp = {
    id: crypto.randomUUID(),
    from: 'user-1',
    to: 'user-2',
    kind: 'sealed',
    ciphertext: crypto.randomBytes(2048).toString('base64'),
    nonce: crypto.randomUUID()
  };
  const resEtp = await tm.routeMessage(envEtp, 'etp');
  assert.equal(resEtp.transport, 'etp');
  assert.equal(resEtp.hops, 3); // 3-hop onion circuit

  // Controlled Cross-Mode Bridging:
  // Alice on ziokt-p2p, Bob on shadow6
  tm.setUserMode('alice', 'ziokt-p2p');
  tm.setUserMode('bob', 'shadow6');
  const envBridge = {
    id: crypto.randomUUID(),
    from: 'alice',
    to: 'bob',
    kind: 'sealed',
    ciphertext: crypto.randomBytes(2048).toString('base64'),
    nonce: crypto.randomUUID()
  };
  const resBridge = await tm.routeMessage(envBridge);
  assert.equal(resBridge.sourceMode, 'ziokt-p2p');
  assert.equal(resBridge.targetMode, 'shadow6');
  assert.ok(resBridge.bridged);
  assert.equal(resBridge.bridged.from, 'ziokt-p2p');
  assert.equal(resBridge.bridged.to, 'shadow6');

  // Anti-loop protection: reject packets with bridgeHops > 2
  const envLoop = {
    id: crypto.randomUUID(),
    from: 'alice',
    to: 'bob',
    kind: 'sealed',
    ciphertext: crypto.randomBytes(2048).toString('base64'),
    nonce: crypto.randomUUID(),
    bridgeHops: 3
  };
  await assert.rejects(async () => tm.routeMessage(envLoop), /BRIDGE_LOOP_DETECTED/);

  // Anti-replay protection: duplicate nonces across different message IDs are rejected
  const replayNonce = 'test-nonce-12345';
  await tm.routeMessage({ ...envBridge, id: crypto.randomUUID(), nonce: replayNonce });
  await assert.rejects(
    async () => tm.routeMessage({ ...envBridge, id: crypto.randomUUID(), nonce: replayNonce }),
    /REPLAY_DETECTED/
  );
});

test('End-to-end integration: 5 communication modes, switching, and 5-stage ACKs in live server', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'watchat-trans-test-'));
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;

  const child = spawn(process.execPath, [path.resolve(__dirname, '../backend/server.js')], {
    env: {
      ...process.env,
      PORT: String(port),
      DATA_DIR: dir,
      ADMIN_PASSWORD: 'admin-password-strong-1234',
      ZIOKT_STANDALONE: '1',
      ZIOKT_BRIDGE_CONFIG: '',
      SIM_BRIDGE_CONFIG: '',
      WATCHAT_PUSH_CONFIG: '',
      WATCHAT_WEBHOOK_CONFIG: '',
      WATCHAT_ORIGIN: ''
    },
    stdio: ['ignore', 'pipe', 'pipe']
  });

  t.after(async () => {
    child.kill();
    await delay(50);
    fs.rmSync(dir, { recursive: true, force: true });
  });

  let ready = false;
  for (let i = 0; i < 100; i++) {
    try {
      if ((await fetch(base)).ok) { ready = true; break; }
    } catch (_) {}
    await delay(20);
  }
  assert.ok(ready, 'Server failed to start');

  async function request(url, { cookie, data, method = data ? 'POST' : 'GET', origin = base } = {}) {
    const headers = { Origin: origin };
    if (cookie) headers.Cookie = cookie;
    if (data) headers['Content-Type'] = 'application/json';
    return fetch(base + url, { method, headers, body: data ? JSON.stringify(data) : undefined });
  }

  async function login(username, password) {
    const r = await request('/api/login', { data: { username, password } });
    assert.equal(r.status, 200);
    return { cookie: r.headers.get('set-cookie').split(';')[0], user: (await r.json()).user };
  }

  const admin = await login('admin', 'admin-password-strong-1234');
  for (const name of ['user1', 'user2']) {
    await request('/api/users', { cookie: admin.cookie, data: { username: name, name, password: name + '-password-1234' } });
  }
  const u1 = await login('user1', 'user1-password-1234');
  const u2 = await login('user2', 'user2-password-1234');

  await request('/api/contacts', { cookie: u1.cookie, data: { id: u2.user.id } });

  // 1. Check /api/transport/modes endpoint
  const modesRes = await (await request('/api/transport/modes', { cookie: u1.cookie })).json();
  assert.equal(modesRes.current, 'watchat-server'); // Default is WATChat Server!
  assert.equal(modesRes.modes.length, 5);

  // 2. Switch mode via /api/transport/mode
  const switchRes = await (await request('/api/transport/mode', { cookie: u1.cookie, data: { mode: 'shadow6' } })).json();
  assert.equal(switchRes.ok, true);
  assert.equal(switchRes.mode, 'shadow6');

  const afterSwitch = await (await request('/api/transport/modes', { cookie: u1.cookie })).json();
  assert.equal(afterSwitch.current, 'shadow6');

  // Switch back to watchat-server (default)
  await request('/api/transport/mode', { cookie: u1.cookie, data: { mode: 'watchat-server' } });

  // 3. Connect via WebSockets and test 5-stage ACKs
  const ws1 = new WebSocket(base.replace('http:', 'ws:') + '/ws', { headers: { Cookie: u1.cookie, Origin: base } });
  const ws2 = new WebSocket(base.replace('http:', 'ws:') + '/ws', { headers: { Cookie: u2.cookie, Origin: base } });
  t.after(() => { ws1.close(); ws2.close(); });

  const events1 = [];
  const events2 = [];
  ws1.on('message', m => events1.push(JSON.parse(m)));
  ws2.on('message', m => events2.push(JSON.parse(m)));

  await Promise.all([
    new Promise(r => ws1.once('open', r)),
    new Promise(r => ws2.once('open', r))
  ]);

  // Stage 1 & 2: Send message with ziokt-p2p mode
  const msgId = crypto.randomUUID();
  const testEnvelope = {
    action: 'send',
    id: msgId,
    to: u2.user.id,
    kind: 'sealed',
    ciphertext: crypto.randomBytes(2048).toString('base64'),
    attachments: [],
    transport: 'ziokt-p2p',
    hops: 1,
    nonce: crypto.randomUUID()
  };
  ws1.send(JSON.stringify(testEnvelope));
  await delay(120);

  // Sender receives ACK: stage reaches 'node'
  const ack = events1.find(e => e.type === 'ack' && e.id === msgId);
  assert.ok(ack, 'Sender must receive ack');
  assert.equal(ack.transport, 'ziokt-p2p');
  assert.equal(ack.hops, 1);
  assert.equal(ack.state, 'node');

  // Recipient receives message
  const receivedMsg = events2.find(e => e.type === 'message' && e.message.id === msgId);
  assert.ok(receivedMsg, 'Recipient must receive message');
  assert.equal(receivedMsg.transport, 'ziokt-p2p');
  assert.equal(receivedMsg.hops, 1);

  // Stage 4: Recipient confirms receipt
  ws2.send(JSON.stringify({ action: 'received', id: msgId }));
  await delay(100);

  const receiptConfirmed = events1.find(e => e.type === 'receipt' && e.id === msgId && e.state === 'recipient-confirmed');
  assert.ok(receiptConfirmed, 'Sender must receive recipient-confirmed receipt');

  // Stage 5: Recipient reads message
  ws2.send(JSON.stringify({ action: 'read', id: msgId }));
  await delay(100);

  const receiptRead = events1.find(e => e.type === 'receipt' && e.id === msgId && e.state === 'read');
  assert.ok(receiptRead, 'Sender must receive read receipt');
});
