# Copyright metadata and local governance

Library accepts optional `rights` metadata (`ziokt.content-rights.v1`):

```json
{
  "schema": "ziokt.content-rights.v1",
  "attribution": [{"name": "Author", "role": "author"}],
  "source": "Author-published edition",
  "license": {"type": "spdx", "value": "CC0-1.0", "url": ""},
  "public_domain": true,
  "authorization_proofs": [],
  "dispute_status": "none"
}
```

License types include SPDX, Creative Commons, custom, public-domain and unknown.
Proof entries are SHA-256 commitments to independently retained authorization
evidence. Metadata validation checks bounded structure and identifier syntax;
it does not certify license compatibility, copyright ownership, validity of
proofs or real legal standing. Origin signatures authenticate publication of a
claim. Existing `license` strings and books without `rights` remain valid.

## Permissions

| Operation | Required scope | Effect |
| --- | --- | --- |
| `content.rights.report` | `content:write` | Private local complaint about visible content |
| `content.rights.case` | `content:read` and reporter/content-owner match | Read own case and audit history |
| `content.rights.appeal` | `content:write` and reporter/content-owner match | Append appeal; preserve previous decisions |
| `content.rights.review`, `content.rights.decide` | `content:admin` | Local operator review/decision only |
| `content.policy` | `content:admin` | Local deindex/reindex or stop/resume distribution |
| `content.withdraw` | `content:write` and actual local content ownership | Signed owner tombstone |
| `content.object.release` | `content:write` and object ownership | Physical local collection after active references/pins are gone |

A complaint or upheld decision never silently triggers takedown. Enforcement is
an explicit separate operator action with a reason. Complaints, evidence and
contact details remain in local private SQLite; they do not enter the public
catalogue or chain. They are not encrypted database fields. Operators must
protect backups and access to the service root. History is bounded and
append-only through application operations; this is not tamper-proof hardware.

Deindexing hides local search entries but leaves direct authorized reading
available. Stopping distribution denies public/non-owner direct reads and
object downloads, as well as public article listings/statistics. Owners retain
access to their own stored data. A different authorized public reference to
identical bytes can still authorize that object; policy attaches to records.

Ordered signed catalogue export pauses with an explicit error and unchanged
cursor if its next batch contains a distribution-stopped record. It does not
silently skip the event and corrupt predecessor/cursor recovery. Resume local
distribution to continue that history; per-record selective federation feeds
remain unimplemented. Local policies do not transmit commands to erase remote
copies. Already synchronized independent catalogues and downloaded bytes remain
under their independent operator's control.

## Migration, restart and rollback

Migration 6 adds `rights_cases`, `rights_events`, `local_content_policies` and an
entry in the existing migration log in one transaction. Records/object formats,
node keys and existing migrations are preserved. Policies, complaints and appeals
survive restart. Source node signatures also cover optional rights metadata.

Back up the complete content root before upgrading. Downgrading to a binary that
has no policy checks would resume its old distribution behavior: first disable
public serving/export or deploy equivalent local ingress restrictions. Retain
the additive tables and signed event history. Do not drop governance tables to
make a downgrade appear successful or re-sign historical objects.

Local tests exercise actual encrypted object reads, independent signed catalogue
copies, complaint restart/appeal history, and HTTP writer-versus-admin denial.
No remote DRM, global master key, license heartbeat or remote destruction is
introduced. Reader and administration GUI controls still need dedicated coverage.
