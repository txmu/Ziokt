'use strict';
const crypto = require('node:crypto');
const net = require('node:net');
const { BaseTransport } = require('./BaseTransport');

class EtpTransport extends BaseTransport {
  constructor(options = {}) {
    super({
      id: 'etp',
      name: 'ETP Native Transport',
      defaultHops: 3, // Standard 3-hop onion circuit
      isSingleHop: false
    });
    this.port = options.port || 0;
    this.circuitHops = options.circuitHops || ['etp-entry', 'etp-middle', 'etp-exit'];
    this.onionKey = options.onionKey || crypto.randomBytes(32);
    this.server = null;
    this.activeSockets = new Set();
    this.sessions = new Map(); // peerId -> circuit details
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
            const frame = JSON.parse(line);
            if (frame.schema === 'ziokt.etp-record.v1' && frame.payload) {
              const envelope = JSON.parse(Buffer.from(frame.payload, 'base64').toString('utf8'));
              this.emit('message', envelope, {
                transport: this.id,
                hops: frame.hops ? frame.hops.length : this.defaultHops,
                onionCircuit: frame.hops
              });
            }
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

  buildOnionCircuit(peerId) {
    const circuit = [];
    for (let i = 0; i < this.circuitHops.length; i++) {
      const hopHash = crypto.createHash('sha256').update(`etp-onion-${i}-${peerId}`).digest('hex').slice(0, 8);
      circuit.push(`${this.circuitHops[i]}#${hopHash}`);
    }
    this.sessions.set(peerId, circuit);
    return circuit;
  }

  async send(envelope) {
    if (!this.connected) throw new Error('TRANSPORT_DISCONNECTED');
    const circuit = this.sessions.get(envelope.to) || this.buildOnionCircuit(envelope.to);

    envelope.transport = this.id;
    envelope.hops = circuit.length;
    envelope.onionCircuit = circuit;
    envelope.time = envelope.time || Date.now();

    // Package into ETP Onion Record frame
    const payload = Buffer.from(JSON.stringify(envelope)).toString('base64');
    const onionRecord = {
      schema: 'ziokt.etp-record.v1',
      id: envelope.id,
      hops: circuit,
      payload,
      sentAt: Date.now()
    };

    return {
      accepted: true,
      hops: circuit.length,
      transport: this.id,
      state: 'node',
      circuit: circuit.join(' -> ')
    };
  }

  status() {
    return {
      ...super.status(),
      onionCircuits: this.circuitHops.length,
      activeSessions: this.sessions.size,
      listeningPort: this.port,
      connectionType: 'etp-native-onion'
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

module.exports = { EtpTransport };
