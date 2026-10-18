'use strict';
const { BaseTransport } = require('./BaseTransport');

class WatchatServerTransport extends BaseTransport {
  constructor(options = {}) {
    super({
      id: 'watchat-server',
      name: 'WATChat Native Server',
      defaultHops: 1,
      isSingleHop: true
    });
    this.serverSender = options.sendFn || null; // function(recipientId, envelope)
  }

  setSender(fn) {
    this.serverSender = fn;
  }

  async send(envelope) {
    if (!this.connected) throw new Error('TRANSPORT_DISCONNECTED');
    envelope.transport = this.id;
    envelope.hops = 1;
    envelope.route = ['server'];

    if (this.serverSender) {
      await this.serverSender(envelope.to, envelope);
    }

    return {
      accepted: true,
      hops: 1,
      transport: this.id,
      state: 'transport',
      direct: false
    };
  }

  status() {
    return {
      ...super.status(),
      connectionType: 'websocket-server-relay'
    };
  }
}

module.exports = { WatchatServerTransport };
