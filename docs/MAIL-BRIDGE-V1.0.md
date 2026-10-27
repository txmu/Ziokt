# v1.0 Mail / Internet Email operations

Native mail signatures and external mailbox authentication remain separate. Every imported email has `external_origin: true` and `sender_signature_verified: false`. SPF/DKIM/DMARC reports never grant native identity or asset authority.

## Identity, aliases and conversations

A private mail config contains `state` and `internet`. The legacy single-account shape remains supported. For several accounts, use `internet.accounts` (1–8 complete account configurations), `default_account` and `sync_interval` (30–3600 seconds). Each account has an independent database and IMAP cursor. MCP additionally places the entire collection under the authenticated client's own state directory; configured account access is not inferred from sender names.

Each account retains `account`, `from_address`, `local_recipient`, `allowed_senders`, TLS `smtp` / `imap` endpoints and `secret_file`. Optional `identity_bindings` maps each allowed native public key to:

```json
{
  "native_address": "PUBLIC_KEY@node.ziokt",
  "addresses": ["alice@example.org", "a@example.org"],
  "default_address": "alice@example.org",
  "display_name": "Alice",
  "reply_to": "alice@example.org",
  "email_verification": "operator_attested",
  "content_token_file": "/private/alice-content.token"
}
```

The signed native address must match the binding. `From`, SMTP envelope sender and `Reply-To` must use an assigned alias. Disjoint native identities cannot claim the same alias within one account. SMTP providers must actually authorize the aliases; this configuration cannot grant provider-side send-as permission. `operator_attested` is an administrative assertion, not cryptographic email ownership verification; responses retain `email_ownership_verified: false`. Legacy shared accounts continue to report their shared sender without inventing separate addresses.

`mail_send` and signed envelopes support `internet_account`, `internet_from`, `in_reply_to` and `references`. Outbound receipts return `rfc_message_id`; inbox entries retain original Message-ID, In-Reply-To, References, Reply-To, To and Cc. CLI equivalents are `--internet-account`, `--internet-from`, `--in-reply-to` and repeated `--reference`. Use `--attachments-file` for a bounded JSON descriptor list.

## OAuth2 and automatic synchronization

Set account `auth` to `oauth2`. The mode is explicit; it does not fall back to password authentication. The private 0600 `secret_file` contains `username`, `provider` (`google` or `microsoft`), `client_id`, `access_token`, Unix `expires_at`, `refresh_token`, and optional `client_secret` / Microsoft `tenant`. Obtain user consent through the registered provider application first. Tokens refresh only against fixed HTTPS provider endpoints, without redirects, with private atomic refresh-token rotation. SMTP AUTH and IMAP AUTHENTICATE use SASL XOAUTH2.

Provider consent, tenant permissions, IMAP enablement, SMTP AUTH policies and send-as aliases must be configured by the mailbox owner. Implementation references: [Google XOAUTH2](https://developers.google.com/workspace/gmail/imap/xoauth2-protocol), [Microsoft OAuth for IMAP/SMTP](https://learn.microsoft.com/en-us/exchange/client-developer/legacy-protocols/how-to-authenticate-an-imap-pop-smtp-application-by-using-oauth).

MCP starts configured clients' mail workers on startup and stops them at shutdown. Revoked clients/scopes stop background access, and global write disablement prevents background submission. Durable SMTP claims preserve existing uncertain-DATA handling: uncertain delivery is never automatically resubmitted. Account errors are isolated and retried at the configured interval; no secrets appear in worker status.

Standalone nodes can run `python -m ziokt.mail_worker --config /private/mail.json` as a supervised service, or `--once` for one bounded cycle. No interactive flush call is required. This worker does not provision provider accounts or change DNS.

## Bidirectional MIME and Content Fabric

References remain the default. To export actual files set account `attachment_export` to:

```json
{
  "mode": "mime",
  "content_url": "https://content.example.org",
  "scanner": ["/usr/bin/clamscan", "--no-summary"],
  "max_file_bytes": 262144,
  "max_total_bytes": 524288
}
```

The Content Fabric token belongs to the specific native identity, not a node-wide administrator. The authenticated object endpoint checks that account's permissions on each export. Redirects are refused; HTTPS (or explicit loopback HTTP) is required. The bridge enforces descriptor size/digest and total size, then runs the configured scanner with a private temporary file, bounded timeout and no shell. Any authorization, digest, size or scanner failure stops queueing; it never silently falls back to downloading inaccessible data. Final MIME messages remain bounded to 1 MiB including base64 overhead.

Inbound MIME attachments enter the account's private SQLite quarantine (at most four, 256 KiB each, 512 KiB aggregate). They are never executed or publicly published. `inbound_content: {"root": "/private/content-root", "owner": "alice"}` explicitly enables scanned import into that private local Fabric account. The same configured scanner is mandatory; unavailable/rejecting scanners leave attachments quarantined. `mail_attachment_import` allows an authorized client to retry a named attachment from its own account. Interrupted automatic imports retry from quarantine. Scanner configuration is an operator trust boundary: a successful test fixture allowlist is not an antivirus certification.

HTML-only mail is returned as inert `text/plain`; scripts, style, frames and objects are removed, remote images are not fetched. Clients must render text as text. Authentication-Results are untrusted by default. `trusted_authserv_ids` can pin the actual receiving MTA only when it strips forged matching headers; duplicate headers remain untrusted. The bridge does not claim to independently perform DKIM DNS validation.

## Optional public gateway and remaining operational prerequisites

An account's public aliases plus `identity_bindings.native_address` and `local_recipient` form the explicit outbound/inbound gateway mapping for a ZDNS identity. Use a dedicated provider account or authorized alias for each intended public identity. A ZDNS domain is not automatically a public DNS email domain: an operator must own a public domain, provision its mailbox/MX and SPF/DKIM/DMARC, authorize the aliases, and bind the native inbox explicitly. No unauthenticated SMTP relay or automatic address issuance is enabled.

The production node currently has no SMTP/IMAP credentials configured. Live provider OAuth2 and inbound provider delivery are therefore not marked accepted. An explicitly authorized test to the explicitly authorized test recipient exports an actual harmless Fabric object and submits its MIME parts through the connected the connected authorized mailbox Gmail API account; this tests Gmail API submission, not the production SMTP/OAuth2 path. Gmail inbox delivery and reply collection remain separate observations.

## ALFS serial acceptance correction

The prior full ALFS build completed and booted its own system. Saved serial output contained `OPENCI_ALFS_ROOTFS` immediately after an ANSI sequence and a bare carriage return. The old LF-only anchored matcher missed the successful assertion and timed out. The matcher now handles serial CR boundaries and records an explicit command exit code, failing immediately on an unsuccessful assertion. Rootfs/compiler/network checks remain mandatory. Full rebuild and actual boot rerun are remote-only; the saved-byte regression is lightweight.

## Reading receipts and resistance to tracking

`mail_send.request_read_receipt` is a signed, opt-in boolean. It adds standard `Disposition-Notification-To` using the selected assigned sender address; callers cannot redirect it to an arbitrary address. Imported requests are exposed as `read_receipt_requested` only. Viewing an inbox never sends a receipt or fetches remote images.

Account `read_receipts` defaults to `deny`. `mail_receipt_policy(account, policy)` accepts `deny` or `manual` and persists the choice privately. `mail_read_receipt(account, inbox_id, decision)` requires an explicit `send` or `block`. Blocking persists for that message. Sending requires manual policy, a matching request returning to the original sender, the assigned native signing identity, and the regular durable SMTP outbox. It generates a standards-shaped multipart/report MDN with Original-Message-ID and a manual displayed disposition. Duplicate decisions reuse the same queue entry; simultaneous decisions are claimed atomically. No automatic acknowledgement mode is enabled.

Incoming MDNs are exposed as untrusted `receipt_reports`. Their existence is a sender assertion, not proof that a human read the message; they do not change native signature verification or automatically mark delivery/read state as authenticated. Plain-text rendering, no remote image fetch, default-denied MDNs and per-message blocking provide the anti-reading-receipt interface without pretending to control a recipient's external Gmail tracking behavior.
