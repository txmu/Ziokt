'use strict';
const crypto = require('node:crypto');
const { BaseTransport } = require('./BaseTransport');

class ZioktMultihopTransport extends BaseTransport {
  constructor(options = {}) {
    super({
      id: 'ziokt-multihop',
      name: 'Ziokt P2P Multi-Hop',
      defaultHops: options.hops || 3,
      isSingleHop: false
    });
    this.maxHops = options.maxHops || 5;
    this.relays = options.relays || ['relay-alpha', 'relay-beta', 'relay-gamma'];
  }

  setHops(hops) {
    if (typeof hops === 'number' && hops >= 2 && hops <= this.maxHops) {
      this.defaultHops = hops;
    }
  }

  async send(envelope) {
    if (!this.connected) throw new Error('TRANSPORT_DISCONNECTED');
    const hopsCount = envelope.hops && envelope.hops >= 2 ? Math.min(envelope.hops, this.maxHops) : this.defaultHops;

    // Simulate multi-hop routing circuit without revealing real relay identities
    const route = [];
    for (let i = 0; i < hopsCount; i++) {
      const hopHash = crypto.createHash('sha256').update(`relay-${i}-${envelope.id}`).digest('hex').slice(0, 8);
      route.push(`relay#${hopHash}`);
    }

    envelope.transport = this.id;
    envelope.hops = hopsCount;
    envelope.route = route;
    envelope.routedAt = Date.now();

    // Verify TTL to avoid forward loops
    if (envelope.ttl !== undefined && envelope.ttl <= 0) {
      throw new Error('TTL_EXPIRED');
    }
    envelope.ttl = (envelope.ttl || hopsCount) - 1;

    return {
      accepted: true,
      hops: hopsCount,
      transport: this.id,
      state: 'node',
      routeSummary: `${hopsCount}-hop routed mesh`
    };
  }

  status() {
    return {
      ...super.status(),
      configuredHops: this.defaultHops,
      maxHops: this.maxHops,
      activeRelayPool: this.relays.length,
      connectionType: 'multi-hop-mesh'
    };
  }
}

module.exports = { ZioktMultihopTransport };
