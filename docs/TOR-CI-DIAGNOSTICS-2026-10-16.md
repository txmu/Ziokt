# Real Tor CI failure diagnostics

Run `38851598403`, job `116813790064`, failed after successful Tor bootstrap:
its real onion endpoint did not finish authenticated Community synchronization
within the existing 180-second retry window. The log only retained
`CARRIER_UNAVAILABLE`; it did not retain the SOCKS response, negotiation phase or
Tor health. That evidence cannot distinguish descriptor publication/rendezvous
failure from a carrier implementation problem. A public-network outage is not
established, and the test is not classified as passed or skipped.

The client uses authenticated SOCKS5 domain CONNECT with fresh isolation values.
The `<torS0X>0` username format matches the Tor specification, including Tor
0.4.9's newer isolation format:
https://spec.torproject.org/socks-extensions.html

Changes keep the same deadline, mandatory actual network synchronization and
nested onion verification:

- Onion carrier errors retain their existing `CARRIER_UNAVAILABLE` code, but add
  a bounded, sanitized stage, exception class and SOCKS REP byte. No destination,
  proxy address, credentials or raw socket error text is included.
- The isolated CI Tor process enables `ExtendedErrors`, allowing Tor's documented
  descriptor/introduction/rendezvous error codes to be distinguished.
- A private, loopback-only cookie-authenticated control port supplies failure-only
  circuit-established/network-liveness/circuit-state counts. The control parser
  is bounded and handles multiline data blocks; cookies, relay paths, service
  identities and circuit IDs are never returned in the summary.
- Attempt numbers and sanitized errors are printed immediately, instead of
  discarding every earlier failure. Temporary Tor stdout buffering is bounded.
- Diagnostic failure cannot turn a failed network test into success. A bootstrap
  or onion-sync failure remains a failure with the original time budget. No
  clearnet fallback, authentication downgrade, timeout inflation or fake skip was
  introduced.

Local verification used real loopback sockets only:

```
PYTHONPATH=tests python3 -m unittest test_tor_diagnostics test_community_network.CommunityNetworkTests.test_socks5_actual_stream_remote_dns_and_isolation test_community_network.CommunityNetworkTests.test_multihop_selected_candidate_uses_real_tls_without_local_onion_dns test_community_network.CommunityNetworkTests.test_multihop_authentication_downgrade_stops_before_final_peer -v
```

Result: **5 passed, 0 failed, 0 skipped**, 3.380 seconds. Tests include a real SOCKS
rejection with extended descriptor-not-found code `0xf0`, a real local control
conversation with authenticated commands/multiline circuit data, and existing
actual mTLS forwarding/isolation/no-downgrade cases. Python compile and diff
checks passed. This is not a new public-network Tor pass; the mandatory CI gate
must be rerun to obtain the newly preserved diagnostic evidence.
