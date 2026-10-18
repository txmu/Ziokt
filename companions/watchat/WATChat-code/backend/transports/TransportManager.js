'use strict';
const crypto = require('node:crypto');
const { ZioktP2PTransport } = require('./ZioktP2PTransport');
const { ZioktMultihopTransport } = require('./ZioktMultihopTransport');
const { WatchatServerTransport } = require('./WatchatServerTransport');
const { Shadow6Transport } = require('./Shadow6Transport');
const { EtpTransport } = require('./EtpTransport');

class TransportManager {
  constructor(options = {}) {
    this.transports = new Map();
    this.userModes = new Map(); // userId -> mode ('ziokt-p2p' default)
    this.processedNonces = new Map(); // nonce -> timestamp
    this.deliveryStates = new Map(); // messageId -> state ('queued'|'transport'|'node'|'confirmed'|'read')
    this.onMessageCallback = options.onMessage || null;
    this.onReceiptCallback = options.onReceipt || null;

    this._registerDefaultTransports(options);
  }

  _registerDefaultTransports(options) {
    this.registerTransport(new ZioktP2PTransport(options.p2p || {}));
    this.registerTransport(new ZioktMultihopTransport(options.multihop || {}));
    this.registerTransport(new WatchatServerTransport(options.server || {}));
    this.registerTransport(new Shadow6Transport(options.shadow6 || {}));
    this.registerTransport(new EtpTransport(options.etp || {}));
  }

  registerTransport(transport) {
    this.transports.set(transport.id, transport);
    transport.on('message', (envelope, meta) => this._handleIncomingMessage(envelope, meta));
  }

  getTransport(mode) {
    return this.transports.get(mode) || this.transports.get('ziokt-p2p');
  }

  getUserMode(userId) {
    return this.userModes.get(userId) || 'ziokt-p2p';
  }

  setUserMode(userId, mode) {
    if (this.transports.has(mode)) {
      this.userModes.set(userId, mode);
      return true;
    }
    return false;
  }

  _cleanReplayCache() {
    const now = Date.now();
    for (const [nonce, ts] of this.processedNonces) {
      if (now - ts > 600000) this.processedNonces.delete(nonce);
    }
  }

  /**
   * Unified envelope sending with cross-mode controlled bridging.
   */
  async routeMessage(envelope, senderMode = null) {
    this._cleanReplayCache();

    if (!envelope || !envelope.id || !envelope.to || !envelope.ciphertext) {
      throw new Error('INVALID_ENVELOPE');
    }

    // Anti-replay protection
    if (envelope.nonce) {
      const existing = this.processedNonces.get(envelope.nonce);
      if (existing && existing !== envelope.id) {
        throw new Error('REPLAY_DETECTED');
      }
      this.processedNonces.set(envelope.nonce, envelope.id);
    }

    // Mark queued -> transport
    this.deliveryStates.set(envelope.id, 'transport');

    const sourceMode = senderMode || envelope.transport || this.getUserMode(envelope.from);
    const targetMode = this.userModes.has(envelope.to) ? this.userModes.get(envelope.to) : sourceMode;

    let activeTransport = this.getTransport(sourceMode);
    let bridged = null;

    // Cross-Mode Controlled Bridging check:
    // If sender and receiver are on different modes, bridge without decrypting
    if (sourceMode !== targetMode) {
      // Anti-loop protection
      envelope.bridgeHops = (envelope.bridgeHops || 0) + 1;
      if (envelope.bridgeHops > 2) {
        throw new Error('BRIDGE_LOOP_DETECTED');
      }

      bridged = {
        from: sourceMode,
        to: targetMode,
        timestamp: Date.now()
      };
      envelope.bridged = bridged;
      activeTransport = this.getTransport(targetMode);
    }

    // Hand to transport adapter
    const sendResult = await activeTransport.send(envelope);

    // Update state to 'node' once handed off to network
    this.deliveryStates.set(envelope.id, 'node');

    return {
      id: envelope.id,
      transport: activeTransport.id,
      sourceMode,
      targetMode,
      bridged,
      hops: sendResult.hops || activeTransport.defaultHops,
      state: 'node',
      direct: sendResult.direct || false
    };
  }

  _handleIncomingMessage(envelope, meta) {
    if (!envelope || !envelope.id) return;
    this.deliveryStates.set(envelope.id, 'confirmed');

    if (this.onMessageCallback) {
      this.onMessageCallback(envelope, meta);
    }
  }

  markRead(messageId) {
    this.deliveryStates.set(messageId, 'read');
    if (this.onReceiptCallback) {
      this.onReceiptCallback(messageId, 'read');
    }
  }

  getDeliveryState(messageId) {
    return this.deliveryStates.get(messageId) || 'queued';
  }

  getAllModesStatus() {
    const list = [];
    for (const [id, t] of this.transports) {
      list.push(t.status());
    }
    return list;
  }

  close() {
    for (const [_, t] of this.transports) {
      try { t.close(); } catch (_) {}
    }
    this.transports.clear();
  }
}

module.exports = { TransportManager };
