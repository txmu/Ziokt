'use strict';
const { EventEmitter } = require('node:events');

class BaseTransport extends EventEmitter {
  constructor(options = {}) {
    super();
    this.id = options.id || 'base';
    this.name = options.name || 'Base Transport';
    this.defaultHops = options.defaultHops || 1;
    this.isSingleHop = !!options.isSingleHop;
    this.connected = true;
  }

  /**
   * Send an opaque message envelope over this transport.
   * @param {Object} envelope Unified message envelope
   * @returns {Promise<{ accepted: boolean, hops: number, transport: string, state: string }>}
   */
  async send(envelope) {
    throw new Error('send() must be implemented by transport adapter');
  }

  /**
   * Check transport connectivity and status.
   * @returns {Object}
   */
  status() {
    return {
      id: this.id,
      name: this.name,
      connected: this.connected,
      hops: this.defaultHops,
      isSingleHop: this.isSingleHop
    };
  }

  close() {
    this.connected = false;
    this.removeAllListeners();
  }
}

module.exports = { BaseTransport };
