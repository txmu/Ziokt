# Public Ziokt Reader and Netnews deployment

Deployed on 2026-10-19 to the host already resolving `read.ziokt.com` and `nntp.ziokt.com` to `43.207.75.185`.

- `https://read.ziokt.com/` is served through the existing Caddy HTTPS service to a Content Fabric process bound only to `127.0.0.1:8210`.
- `nntp.ziokt.com` resolves to the same host. Its HTTPS root documents the NNTP endpoint. Standard NNTP is exposed at TCP port `119` through a bounded `socat` forwarder to `127.0.0.1:8119`.
- The public identity has a fixed operation allowlist for reading public book/news metadata and public objects. Attempts to publish, change subscriptions, synchronize peers or change settings are rejected. The browser hides those controls for guests. Sign-in reveals write controls and expects the separate Ziokt application credential.
- Public NNTP reads only. The NNTP process receives an empty credential set; it refuses AUTHINFO on the unencrypted listener and rejects unauthenticated POST. Authenticated posting goes through the HTTPS reader API with a separately scoped application credential.
- Caddy manages valid HTTPS certificates for both DNS names. HTTP is not used for the reader site. Port 119 carries only public NNTP content and no password or write credential.
- Content quota is 512 MiB, HTTP and NNTP bind locally, and services have systemd memory, CPU, task and file descriptor limits. State and app credentials are private under `/home/admin/.local/share/ziokt-content`.

## Checks performed on the deployed host

HTTPS GET to both names returned 200 with normal certificate verification. Anonymous read API returned 200 for Library search, public groups, and capability discovery; unauthenticated article publication and peer sync returned 403. A real Chromium session opened the public announcement and confirmed guest write controls are hidden. A real TCP connection to `nntp.ziokt.com:119` listed `ziokt.announce`; unauthenticated POST returned `480 Authentication required`. The host reached the public NNTP name and address on port 119.

A short public announcement was seeded in `ziokt.announce`; `ziokt.general` accepts application-authenticated public submissions through the HTTPS reader. The Library is online but currently has no book records. Posting from ordinary clients is not enabled over plaintext NNTP; use the authorized web/extension application.

No AWS security-group rules were changed. Public reachability was tested from this host to its public DNS address. Availability from unrelated networks still depends on the provider ingress rules. TLS NNTP on port 563 and authenticated Thunderbird posting are not deployed.

## Operations

```sh
sudo systemctl status ziokt-content ziokt-nntp-public ziokt-https
sudo journalctl -u ziokt-content -u ziokt-nntp-public -u ziokt-https
```

The private operator application credential is in `/home/admin/.local/share/ziokt-content/application.token` (mode 0600). Do not copy it into public plugin packages, logs, shell history, or public deployment configuration. `deploy/content-fabric/public-read.example.json` contains a placeholder only. Live storage is capped at 512 MiB because this host has limited free disk and RAM; monitor before adding public content.
