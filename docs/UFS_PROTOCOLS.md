# UFS protocols in Ziokt

The same native UFS implementation serves HTTP/HTTPS and WebDAV, FTP/explicit FTPS, Gopher, Telnet/Telnet over TLS, SSH SFTP and NNTP/NNTPS. DCPM package APIs continue to use their signed package store. Protocol accounts share their configured UFS home; each new account has a separate home unless the operator explicitly assigns a shared directory. Gopher's unauthenticated menu serves its separate public directory.

Install the protocol runtime and enable the listeners in an existing native configuration:

```sh
python3 -m pip install -r requirements-ufs.txt
python3 tools/configure_ufs_protocols.py --config /absolute/path/dcpm-ufs.json --hostname node.example.org
python3 companions/ufsdcpm/src/dcpm_ufs_integration.py system start --config /absolute/path/dcpm-ufs.json
```

The configurator preserves existing identities, package signing keys and passwords. It backs up the configuration privately and creates a persistent TLS identity if a certificate/key pair was not supplied. Use `--tls-cert` and `--tls-key` to use an existing certificate. Clients verify that certificate and the advertised SSH host key. With the default port base, FTP/FTPS use 22021/22022, Telnet 22023, SFTP 22024, Gopher 22070 and NNTP 22019. FTP passive data ports are 22800–22831. Public authenticated FTP, Telnet and NNTP use TLS; plaintext variants remain available on loopback and inside explicitly configured encrypted tunnels.

Read the actual listeners through Ziokt's CLI:

```sh
python3 -m ziokt companion ufsdcpm protocols --config /absolute/path/dcpm-ufs.json
```

The authenticated native HTTP API also exposes `GET /api/protocols`. Set `ufs_protocols_config` in the private MCP configuration to expose `ufs_protocols_status` with the `ufs:read` scope. Caller arguments cannot select a configuration path or endpoint.

The standalone extended entry point uses the same protocol hub:

```sh
python3 companions/ufsdcpm/src/ufs_extra_protocols.py --config /absolute/path/ufs.json
python3 companions/ufsdcpm/src/ufs_extra_protocols.py --config /absolute/path/ufs.json --install
python3 deploy.py --root /installation/root service status
```

The hub checks its actual listening sockets. A failed listener stops the component so its supervisor can restart the complete set. Shutdown closes accepted SSH transports and listeners. Linux systemd, macOS launchd and Windows scheduled-task lifecycle tests exercise actual startup, crash recovery, stop/start, restart and removal; protocol storage acceptance runs on the two Linux nodes.

Reproduce native protocol acceptance with `python3 -m unittest discover -s tests -p test_ufs_protocols.py -v`. The cross-host harness `ci/ufs_crosshost.py` creates separate private test accounts and certificates on each host, transfers data over the public protocol ports, and verifies FTP/SFTP/Telnet uploads through authenticated HTTPS. Its client descriptors contain test credentials and stay private.
