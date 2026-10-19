# Public Ziokt Reader and Netnews deployment

Deployed on 2026-10-19 to the host already resolving `read.ziokt.com` and `nntp.ziokt.com` to `43.207.75.185`.

- `https://read.ziokt.com/` is served through the existing Caddy HTTPS service to a Content Fabric process bound only to `127.0.0.1:8210`.
- `nntp.ziokt.com` resolves to the same host. Its HTTPS root documents the NNTP endpoint. NNTP is available over implicit TLS 1.2+ at TCP port `563` and as plaintext read-only compatibility on standard port `119`. Both use bounded `socat` forwarders to `127.0.0.1:8119`.
- The public identity has a fixed operation allowlist for reading public book/news metadata and public objects. Attempts to publish, change subscriptions, synchronize peers or change settings are rejected. The browser hides those controls for guests. Sign-in reveals write controls and expects the separate Ziokt application credential.
- Public NNTP reads only. The NNTP process receives an empty credential set and rejects unauthenticated POST on both listeners. The TLS endpoint loads the Caddy-managed Let’s Encrypt certificate; a systemd path watcher restarts the listener when Caddy renews the certificate. Port 119 has no credential accepted and carries public text only; prefer TLS port 563. Authenticated posting goes through the HTTPS reader API with a separately scoped application credential.
- Caddy manages valid HTTPS certificates for both DNS names. HTTP is not used for the reader site. Port 119 carries only public NNTP content and no password or write credential.
- Content quota is 512 MiB, HTTP and NNTP bind locally, and services have systemd memory, CPU, task and file descriptor limits. State and app credentials are private under `/home/admin/.local/share/ziokt-content`.

## Checks performed on the deployed host

HTTPS GET to both names returned 200 with normal certificate verification. Anonymous read API returned 200 for Library search, public groups, and capability discovery; unauthenticated article publication and peer sync returned 403. A real Chromium session opened the public announcement and confirmed guest write controls are hidden. Real TCP connections to `nntp.ziokt.com:119` and TLS 1.3 on `nntp.ziokt.com:563` succeeded. Both list `ziokt.announce` and reject unauthenticated POST; a full TLS ARTICLE response contained the seeded announcement. The host reached both ports through the public DNS name.

A short public announcement was seeded in `ziokt.announce`; `ziokt.general` accepts application-authenticated public submissions through the HTTPS reader. The Library includes the repository’s original 476-byte CC0 sample collection; its public search and safe text reader were verified over HTTPS. Posting from ordinary clients is not enabled over plaintext NNTP; use the authorized web/extension application.

No AWS security-group rules were changed. Public reachability was tested from this host to its public DNS address. Availability from unrelated networks still depends on the provider ingress rules. Thunderbird compatibility and authenticated NNTP posting are not deployed; posting remains available through the HTTPS Ziokt application.

## Operations

```sh
sudo systemctl status ziokt-content ziokt-nntp-public ziokt-nntps-public ziokt-nntps-cert.path ziokt-https
sudo journalctl -u ziokt-content -u ziokt-nntp-public -u ziokt-nntps-public -u ziokt-https
```

The private operator application credential is in `/home/admin/.local/share/ziokt-content/application.token` (mode 0600). Do not copy it into public plugin packages, logs, shell history, or public deployment configuration. `deploy/content-fabric/public-read.example.json` contains a placeholder only. Live storage is capped at 512 MiB because this host has limited free disk and RAM; monitor before adding public content.

## Committed release activation

The content service now starts from `/home/admin/.local/share/ziokt-content/current`, a managed symlink to a fixed committed source release. The service may write only its `state` directory. `tools/stage_content_release.py` streams tracked `ziokt` and `spec` files from a Git commit, hashes every file and verifies the release before an optional atomic symlink switch. It excludes live credentials and databases. Restart the Content/NNTP services after activation; a pointer switch alone does not reload running Python code. Preserve a stopped-writer private checkpoint before schema changes. Source rollback and database rollback are distinct operations; use the matching checkpoint when rolling back an incompatible schema.
