# Optional optimization profiles

Engineering mapping from the local expression model revision 2.1, SHA-256 `af29e90ef15463343decef3392c50eef28aec1cb6979c01f0a23fc6041c65304`.

The original local manuscript is not copied into the public repository. Profiles are disabled by default, account scoped, revision checked and audited. Administrators may set node/application defaults; ordinary users cannot change those defaults. Disabling a profile restores baseline settings. Permissions, signature checks, encryption and replication guarantees are not optional optimization flags.

Actual consumers include search prefix/fuzzy matching, work aggregation, page bounds, SQLite cache sizing, bounded parallel chunk downloads, verified-source preference, damaged-source quarantine, retry budgets, expired incomplete-upload cleanup, and NNTP range bounds. These currently apply to Content Fabric and its application services; native components elsewhere are not yet universally integrated.

MCP/HTTP operations: `optimization.get`, `optimization.configure`, `optimization.configure_defaults` (administrator), and `optimization.evaluate`. Supply the returned revision when updating a profile. Profiles and changes survive restart in SQLite.

The finite-model evaluator reports conditional mutual information and conditional entropy in bits separately from zero-one optimal risk. Actual and excess risk require an explicit decoder; missing measurements remain unknown. Duplicate replicas do not become independent evidence. It does not infer intention or causality, assume a Markov chain, or combine unlike units into a quality score. Search transformations preserve original stored content and provenance.

The authorized Content web interface exposes a normal settings form with load, save and disable controls. A revision conflict requires reloading settings; it is never silently overwritten.
