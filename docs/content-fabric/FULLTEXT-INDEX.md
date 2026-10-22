# Account-private document index v1

`library.index.start`, `step`, `status`, `cancel` share the same implementation in
application HTTP, MCP, Content Web, GUI and extensions. Existing tool IDs remain.
Index creation is explicit: open the personal reader panel, then Private full text
index. Closing it pauses subsequent work; Build / resume continues the persisted
cursor. Delete removes derived pages, terms and completed-document mapping only.
A failed job must be explicitly deleted and started again.

Each step extracts at most 16,384 characters through the existing Linux document
sandbox. Supported sources: TXT, Markdown, HTML text, EPUB and selectable PDF
text. PDF rendering uses the pinned PDFium runtime. No OCR or CBZ text extraction.
Sources are limited to 16 MiB; documents to 1,024 chapters, 2 Mi characters and
32,768 unique terms. Account budgets are 200,000 terms, 64 MiB encrypted pages and
10,000 persisted jobs. Quota failure rolls back the current page and never exposes
a partial index. Previous original files remain untouched.

SQLite migration 12 is additive and transactional. Pages and boundary word carry
are AES-GCM encrypted with account-vault-derived keys and positional associated
data. Terms are account-keyed HMAC-SHA256 of normalized words. No plaintext body
or vocabulary is stored in the index tables. Equality, size and access patterns
remain observable: this is not oblivious search. Node administrators possessing
vault keys can decrypt local indexes; it is not protection against that operator.

Search combines existing metadata FTS5 with completed, current-file-version
personal indexes. Document queries require all normalized whole words; accent
folding is supported, phrases/prefixes/fuzzy matching apply only to the existing
metadata search. Words longer than 128 characters are omitted. Boundary carry
prevents splitting a word at a reader page boundary. Cross-account, anonymous and
federated catalog readers never receive another account's personal index. Existing
visibility, expiry, withdrawal, deindex and distribution controls still apply.

Revision checks and expiring leases prevent duplicate cursor advancement. Extraction
runs outside the database write transaction; committing rechecks source identity,
lease and revision. A crashed lease can resume after 30 seconds. Cancel invalidates
an in-flight lease. File replacement immediately removes old index matches, while
old derived data is retained until explicit deletion and counts against quotas.
Extractor revision is the `ziokt.library-index.v1` job identity domain; future
incompatible extractor changes must change that domain or explicitly reindex.

Evidence: `tests/test_library_index.py` covers real sandbox extraction including
both PDF pages, encrypted SQLite storage, restart, page-boundary words, scoped MCP,
account denial, quota rollback, tamper rejection, expired leases, replacement and
withdrawal. `tools/content_browser_smoke.cjs` exercises actual PDF index creation
and body-only search through Chromium and the HTTP service. This is local resumable
indexing, not an autonomous cross-node indexing or replica-repair scheduler.
