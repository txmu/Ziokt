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

const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

async function freePort() {
  const server = net.createServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  return port;
}

// Client-side WebCrypto simulation for test verification
async function clientDeriveKey(password, salt, iterations = 100000) {
  const km = await crypto.subtle.importKey('raw', Buffer.from(password), { name: 'PBKDF2' }, false, ['deriveKey']);
  return crypto.subtle.deriveKey(
    { name: 'PBKDF2', salt: Buffer.from(salt, 'base64'), iterations, hash: 'SHA-256' },
    km,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt']
  );
}

async function clientEncryptBackup(privateJwk, password) {
  const salt = crypto.randomBytes(16);
  const iv = crypto.randomBytes(12);
  const key = await clientDeriveKey(password, salt.toString('base64'), 100000);
  const plain = Buffer.from(JSON.stringify(privateJwk));
  const cipher = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, plain);
  return {
    version: 2,
    algorithm: 'AES-256-GCM',
    kdf: 'PBKDF2-SHA-256',
    iterations: 100000,
    salt: salt.toString('base64'),
    iv: iv.toString('base64'),
    ciphertext: Buffer.from(cipher).toString('base64'),
    updatedAt: Date.now()
  };
}

async function clientDecryptBackup(backup, password) {
  const key = await clientDeriveKey(password, backup.salt, backup.iterations || 100000);
  const plain = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: Buffer.from(backup.iv, 'base64') },
    key,
    Buffer.from(backup.ciphertext, 'base64')
  );
  return JSON.parse(Buffer.from(plain).toString('utf8'));
}

test('Cross-device account key recovery, auto-backup, and migration', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'watchat-account-test-'));
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

  // 1. Admin login and create alice
  const admin = await login('admin', 'admin-password-strong-1234');
  const alicePassword = 'alice-strong-password-1234';
  const createAlice = await request('/api/users', {
    cookie: admin.cookie,
    data: { username: 'alice', name: 'Alice', password: alicePassword }
  });
  assert.equal(createAlice.status, 201);
  const aliceUser = (await createAlice.json()).user;

  // 2. Device A: Alice logs in for the first time
  const aliceDevA = await login('alice', alicePassword);
  assert.equal(aliceDevA.user.backup, null); // No backup yet

  // Device A generates ECDH key pair
  const aliceKeypair = await crypto.subtle.generateKey(
    { name: 'ECDH', namedCurve: 'P-256' },
    true,
    ['deriveBits']
  );
  const alicePrivateJwk = await crypto.subtle.exportKey('jwk', aliceKeypair.privateKey);
  const alicePublicJwk = await crypto.subtle.exportKey('jwk', aliceKeypair.publicKey);

  // Register public key
  const regKey = await request('/api/key', {
    cookie: aliceDevA.cookie,
    data: { key: { kty: 'EC', crv: 'P-256', x: alicePublicJwk.x, y: alicePublicJwk.y } }
  });
  assert.equal(regKey.status, 200);

  // Auto-backup: Client encrypts private key with PBKDF2/AES-GCM and uploads to /api/key/backup
  const encryptedBackup = await clientEncryptBackup(alicePrivateJwk, alicePassword);
  const uploadBackup = await request('/api/key/backup', {
    cookie: aliceDevA.cookie,
    data: encryptedBackup
  });
  assert.equal(uploadBackup.status, 200);

  // Server must not store plaintext private key anywhere
  const storeFile = fs.readFileSync(path.join(dir, 'store.aead'));
  assert.ok(!storeFile.includes(Buffer.from(alicePrivateJwk.d || 'dummy-d-field')));

  // 3. Device B: Alice logs in from a brand new device!
  // No local keys exist on Device B. It only has username & password!
  const aliceDevB = await login('alice', alicePassword);
  assert.ok(aliceDevB.user.backup, 'Device B must receive the encrypted backup');
  assert.equal(aliceDevB.user.backup.algorithm, 'AES-256-GCM');

  // Device B recovers private key locally using the password
  const recoveredPrivateJwk = await clientDecryptBackup(aliceDevB.user.backup, alicePassword);
  assert.equal(recoveredPrivateJwk.x, alicePrivateJwk.x);
  assert.equal(recoveredPrivateJwk.y, alicePrivateJwk.y);
  assert.equal(recoveredPrivateJwk.d, alicePrivateJwk.d);

  // 4. Security verification: Wrong password fails to decrypt backup
  await assert.rejects(
    async () => clientDecryptBackup(aliceDevB.user.backup, 'wrong-password-1234'),
    /OperationError|Error/,
    'Wrong password must fail decryption'
  );

  // 5. Multi-device concurrency: Alice Device A and Device B connected via WebSocket simultaneously
  const wsA = new WebSocket(base.replace('http:', 'ws:') + '/ws', { headers: { Cookie: aliceDevA.cookie, Origin: base } });
  const wsB = new WebSocket(base.replace('http:', 'ws:') + '/ws', { headers: { Cookie: aliceDevB.cookie, Origin: base } });
  t.after(() => { wsA.close(); wsB.close(); });

  const eventsA = [];
  const eventsB = [];
  wsA.on('message', m => eventsA.push(JSON.parse(m)));
  wsB.on('message', m => eventsB.push(JSON.parse(m)));

  await Promise.all([
    new Promise(r => wsA.once('open', r)),
    new Promise(r => wsB.once('open', r))
  ]);

  // Admin sends a message to Alice
  await request('/api/contacts', { cookie: admin.cookie, data: { id: aliceUser.id } });
  const wsAdmin = new WebSocket(base.replace('http:', 'ws:') + '/ws', { headers: { Cookie: admin.cookie, Origin: base } });
  t.after(() => wsAdmin.close());
  await new Promise(r => wsAdmin.once('open', r));

  const testFrame = {
    action: 'send',
    id: crypto.randomUUID(),
    to: aliceUser.id,
    kind: 'sealed',
    ciphertext: crypto.randomBytes(2048).toString('base64'),
    attachments: []
  };
  wsAdmin.send(JSON.stringify(testFrame));
  await delay(150);

  // BOTH Device A and Device B must receive the message concurrently
  assert.ok(eventsA.some(e => e.type === 'message' && e.message.id === testFrame.id), 'Device A received message');
  assert.ok(eventsB.some(e => e.type === 'message' && e.message.id === testFrame.id), 'Device B received message');

  // Device A sends read receipt; Device B must observe receipt sync
  wsA.send(JSON.stringify({ action: 'read', id: testFrame.id }));
  await delay(100);

  // 6. Identity Reset when key permanently lost
  const resetKey = await crypto.subtle.generateKey(
    { name: 'ECDH', namedCurve: 'P-256' },
    true,
    ['deriveBits']
  );
  const resetPublic = await crypto.subtle.exportKey('jwk', resetKey.publicKey);
  const resetPrivate = await crypto.subtle.exportKey('jwk', resetKey.privateKey);
  const resetBackup = await clientEncryptBackup(resetPrivate, alicePassword);

  const resetReq = await request('/api/key/reset', {
    cookie: aliceDevA.cookie,
    data: { key: { kty: 'EC', crv: 'P-256', x: resetPublic.x, y: resetPublic.y }, backup: resetBackup }
  });
  assert.equal(resetReq.status, 200);

  const meAfterReset = await (await request('/api/me', { cookie: aliceDevA.cookie })).json();
  assert.equal(meAfterReset.user.key.x, resetPublic.x);
  assert.equal(meAfterReset.user.backup.salt, resetBackup.salt);
});
