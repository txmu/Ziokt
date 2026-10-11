# ZFCP/1 local-readonly-v1

Production providers carry `provider_runtime.py` independently: S vendors it,
C embeds it in its single Bash artifact. `tools/sync_providers.py --check` detects
protocol drift. Editing generated copies directly is unsupported.

The exact request fields are `protocol`, `request_id`, `federation_id`,
`provider_id`, `method`, `params`, `deadline_ms`, `nonce`. Requests are bounded
UTF-8/NFC JSON, reject duplicate keys/floats/unknown fields and use a 128-bit nonce.
One newline-terminated request and EOF are required per process. There is no
persistent replay protection in the read-only profile.

Native methods: `capabilities.get`, `status.get`, `objects.list`.
Pagination parameters: `kind`, `limit` (1..100), optional snapshot-bound `cursor`.
Every provider retains its own scope and authority. A disabled provider cannot
be activated by the federation configuration. Mutation methods are rejected.

Control frame limit 64 KiB; response limit 256 KiB; nesting 16; strings 8 KiB;
integers within +/- (2^53-1); deadline within 30 seconds; snapshot 4096 objects.
Inventory is stored metadata, not live connection or authenticated remote
identity evidence. Current kinds: S service; C package/environment.
