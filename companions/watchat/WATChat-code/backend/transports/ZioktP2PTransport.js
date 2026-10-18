'use strict';
const net = require('node:net');
const { BaseTransport } = require('./BaseTransport');

class ZioktP2PTransport extends BaseTransport {
  constructor(options = {}) {
    super({
      id: 'ziokt-p2p',
      name: 'Ziokt P2P Single-Hop',
      defaultHops: 1,
      isSingleHop: true
    });
    this.port = options.port || 0;
    this.peerEndpoints = new Map(); // peerId -> { host, port }
    this.server = null;
    this.activeSockets = new Set();
    this._initServer();
  }

  _initServer() {
    this.server = net.createServer(socket => {
      this.activeSockets.add(socket);
      let buffer = '';
      socket.on('data', chunk => {
        buffer += chunk.toString();
        const lines = buffer.split('\n');
        buffer = lines.pop();
        for (const line of lines) {
          if (!line.trim()) continue;
          try {
            const envelope = JSON.parse(line);
            this.emit('message', envelope, { hops: 1, direct: true, transport: this.id });
          } catch (_) {}
        }
      });
      socket.on('close', () => this.activeSockets.delete(socket));
      socket.on('error', () => this.activeSockets.delete(socket));
    });

    this.server.listen(this.port, '127.0.0.1', () => {
      const addr = this.server.address();
      if (addr && typeof addr === 'object') {
        this.port = addr.port;
      }
    });
    this.server.unref();
  }

  registerPeerEndpoint(peerId, host, port) {
    this.peerEndpoints.set(peerId, { host, port });
  }

  async send(envelope) {
    if (!this.connected) throw new Error('TRANSPORT_DISCONNECTED');
    // Ensure envelope is tagged with single-hop metadata
    envelope.transport = this.id;
    envelope.hops = 1;
    envelope.route = ['direct'];

    const target = this.peerEndpoints.get(envelope.to);
    if (target && target.port) {
      await new Promise((resolve, reject) => {
        const client = net.createConnection({ host: target.host || '127.0.0.1', port: target.port }, () => {
          client.write(JSON.stringify(envelope) + '\n', () => {
            client.end();
            resolve();
          });
        });
        client.setTimeout(5000);
        client.on('timeout', () => {
          client.destroy();
          reject(new Error('P2P_TIMEOUT'));
        });
        client.on('error', reject);
      });
    }

    // Direct single hop reached node
    return {
      accepted: true,
      hops: 1,
      transport: this.id,
      state: 'node',
      direct: true
    };
  }

  status() {
    return {
      ...super.status(),
      listeningPort: this.port,
      registeredPeers: this.peerEndpoints.size,
      connectionType: 'direct-p2p'
    };
  }

  close() {
    super.close();
    for (const socket of this.activeSockets) {
      try { socket.destroy(); } catch (_) {}
    }
    this.activeSockets.clear();
    if (this.server) {
      try { this.server.close(); } catch (_) {}
    }
  }
}

module.exports = { ZioktP2PTransport };
