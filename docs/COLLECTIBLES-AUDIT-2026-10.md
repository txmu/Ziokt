# Collectible receipt binding follow-up (2026-10)

`accept_gift` now requires the signed transaction's token ID to match the signed
snapshot's token ID. Previously, a sender could put the encrypted receipt for
collectible A inside a valid transfer of collectible B. A matching native fact
for B and a valid receipt for A could then be misreported as a confirmed receipt
for A. A negative test now uses a genuinely signed transaction for the other
collectible and rejects it before receipt acceptance.

ZKC validation also rejects non-string kinds and malformed fact/inclusion
objects with protocol errors instead of unhandled Python exceptions.

No transaction, snapshot, pack or database format changes. Existing correctly
bound receipts remain valid. The native ledger still enforces current-holder
issuance, ownership nonce, fresh receiving address and transaction deduplication;
these rules are not replaced by the client-side snapshot check.

The `fact` argument and ZKC `query` callback must come from the authenticated,
reviewed native provider. They are not self-authenticating arbitrary dictionaries.
The CLI obtains them through NativeClient; the native provider verifies signed
transaction inclusion on its observed canonical branch. Confirmation describes
that branch at observation time, not a guarantee against every future reorg.
A ZKC pack transports edition references and is not an exclusive ownership
transfer. No gas, issuance cap or economic rule has been added.

Validation commands:

```
PYTHONPATH=tests:. python3 -m unittest test_collectibles test_collectible_network test_community_network -q
PYTHONPATH=tests:. python3 -m unittest test_collectibles.Collectibles -q
```

The affected integration group passed 20 tests in 74.540 seconds, with no skips
or failures, including the actual native ledger/current-holder edition test,
the real two-hop lost-ack/route-failure test, and the new three-node Community
matrix. The final malformed-input guard changes were then covered by the four
collectible unit tests again (0.154 seconds, no failures/skips). Python reported
unclosed-SQLite `ResourceWarning`s in existing native test/fixture paths; these
were warnings, not asserted failures, and this review does not claim they were
resolved.
