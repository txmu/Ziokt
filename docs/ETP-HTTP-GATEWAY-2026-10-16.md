# ETP local HTTP gateway completion

## Actual data path

`GET /fs/<64 lowercase hexadecimal characters>` now reads an explicitly shared or
fully downloaded local object from `FileShareFlavor`. `read_shared` looks up the
existing manifest, opens only its content-addressed storage entry, checks size
and every existing BLAKE3 chunk digest, and returns a bounded immutable snapshot.
Only after validation does HTTP return 200, then send that snapshot in 16 KiB
writes. Unknown, incomplete, changed or unshared objects return 404. Peer display
filenames never become host paths or HTTP header values. Unix reads reject final
symlinks and avoid FIFO open blocking; Windows opens reparse points themselves
for regular-file validation.

This endpoint does **not** initiate a remote download and does not imply DHT
availability, replication, or blockchain confirmation. The maximum object size
remains the existing FileShare limit: 1024 chunks of 16 KiB. A verified snapshot
can use up to 16 MiB; at most eight HTTP connections are active. Local file work
runs off the async executor and retains its connection budget even if its caller
times out.

## HTTP boundary

- Listener is IPv4 loopback only (`127.0.0.1`). AirGap refuses startup.
- Exact loopback Host plus port; reject DNS rebinding hosts, duplicate headers,
  foreign Origin and browser cross-origin/site requests.
- Only HTTP/1.1 GET, no transfer encoding or body, no pipelining, bounded 8 KiB
  complete headers, two-second header deadline and thirty-second request deadline.
- Exact hash paths; query strings, traversal, percent-encoded traversal and
  arbitrary filenames do not resolve to local files.
- Complete content length, connection close, attachment disposition, no-store,
  nosniff and sandbox CSP. The TNS response uses JSON encoding rather than string
  interpolation. Response bodies are sent with bounded chunks and write deadline.
- Dropping the final gateway reference closes its listener. In-flight requests
  retain their finite deadline. The listener is not public authentication: other
  local non-browser processes remain inside the local read-only trust boundary.

## Startup compatibility

`HttpGatewayFlavor::bind(port, tns, fs).await?` returns the actual bound address via
`local_addr()` and propagates startup errors, including port conflicts. Port zero
is supported for isolated tests. Direct examples now use this path. The existing
`new` constructor remains deprecated for source compatibility: it schedules
startup and logs binding failure; its returned object is not proof of a bound
listener. Use `bind` whenever startup must be verified. No packet or object
format changed. The incorrect public `0.0.0.0` example comment was corrected.

## Tests and verification status

Three native Rust tests use real temporary FileShare/sled storage, real loopback
listeners and TCP streams:

1. Return exact shared bytes and length, then refuse altered storage.
2. Refuse rebinding, foreign Origin, cross-site/same-site browser requests,
   duplicate Host, request bodies, transfer encoding, traversal, unknown hashes
   and excessive headers.
3. Accept fragmented headers; enforce the eight-connection budget and header
   deadline; close the listener after the final gateway reference is dropped.

`rustfmt --edition 2021 --config skip_children=true` parsed both changed runtime
modules. `git diff --check` passed. **No cargo compilation or Rust test execution
was performed locally.** These tests must run in CI with the existing persistence
feature/full build. CI availability is reported separately; tests are not counted
as passed merely because their source parses.
