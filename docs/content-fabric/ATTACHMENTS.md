# Durable news attachments and shared content references

`netnews.post` accepts optional `attachments: [{"id":"cf1-...","name":"original.pdf"}]`. Upload bytes first through the bounded Content upload API or streaming CLI. The node checks object ownership and records the actual digest, MIME type, size, Merkle root and version in the signed article. At most eight distinct objects may be attached to a post. Private posts retain account-only access; publishing an owned object in a public post deliberately permits public reads.

Migration 4 creates indexed `content_references` and backfills existing books. Books and articles may retain the same account-scoped object. `content.references` returns only authorized active references. Withdrawal/expiry removes the reference from access decisions; another authorized public reference can still retain public availability. `content.object.release` refuses while a local active application reference retains the object. The node does not promise remote erasure.

A remote publisher cannot authorize a known local private object ID by placing it in a signed public book or post. Remote references grant reads only through an explicitly downloaded, verified remote-to-local alias; local references must belong to the local object owner and publisher.

`netnews.attachment.download` takes `article`, `id`, configured `sources` aliases and optional `max_chunks`. It uses the existing persistent multi-source transfer/checkpoint path, Merkle proofs and final digest. It never treats a remote reference or hash as cached bytes. A node may synchronize article metadata without fetching attachments.

The independent web application and WebExtensions upload, publish, retrieve and verify attachments using the shared application SDK. Browser transfers have an explicit 16 MiB budget per file. Larger files use the streaming CLI or authorized HTTP Range access.

## NNTP

ARTICLE/HEAD/BODY emit standard multipart MIME for locally available native attachments, streaming encrypted-store chunks into base64 lines. The entire attachment is not assembled in RAM. `max_attachment_transfer_bytes` is an optional node budget (default: maximum Content object size); if objects are unavailable or exceed the chosen budget, the article explicitly presents native references/HTTPS links instead of fabricated MIME bytes. A damaged object aborts the multiline response without a success terminator. Large attachments are not automatically fetched from peers merely because a news client reads the article.

Incoming multipart/mixed supports one plain text body and explicit inert MIME attachments, with strict filename and decoder validation. Current incoming inline compatibility budget is 32 KiB decoded/48 KiB total; the separate native upload path supports the configured Content object size. Streaming/configurable larger incoming MIME support remains a follow-up. Original feed MIME retains raw source bytes and peer provenance within its existing bounded source-envelope budget. Failed new MIME staging leases are discarded without releasing another application's retained bytes. Message-ID retries compare attachments as well as text and do not silently replace existing content.

## Streaming HTTP Range download

```sh
python3 -m ziokt.content_client --url https://read.ziokt.com \
  --download-id cf1-OBJECT --output /private/download.bin
```

Add `--token-file /private/application.token` for private access. The client writes owner-only partial/checkpoint files, verifies the persisted prefix before resume, requests bounded HTTP Range segments, fsyncs checkpoints, checks the final SHA-256 and refuses to overwrite a different file. `--max-segments 1` performs bounded work and leaves a resumable checkpoint. Failed or corrupt bytes are never reported as a completed download. URLs and command arguments contain no credentials.
