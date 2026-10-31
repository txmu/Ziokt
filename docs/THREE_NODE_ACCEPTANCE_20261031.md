# Three-node closeout — 2026-10-31

Three-node production acceptance is in progress. Earlier two-node results remain valid only for their recorded scope. The [Chinese report](THREE_NODE_ACCEPTANCE_20261031.zh-CN.md) records the evidence index, deployment details and rollback procedures.

A (13.112.54.178) and B (38.175.194.110) retain their existing independent Primary and DNA identities, Genesis and consensus policies. C (94.237.57.186) has generated independent identities and passed full native replay of the Primary H567 and DNA H5008 bootstrap snapshots. C mining stays stopped until live synchronization finishes. Three active validators and three-node application delivery are not yet certified.

The application hub scope error and memory-only remote credential saving defect have been repaired and deployed. Actual public Chromium verification loaded 27 native package tools, authenticated with the saved credential, found no credential in localStorage, and recorded no page errors. The Corium portal now opens the live native explorer rather than an unpublished reserved NNS target; static content integrity checks remain enforced.

Deployment supports configurable advertised hosts, independent chain ports, HTTP/file offsets, custom network bootstrap URLs and pinned bundles. `--port-profile auto` probes certificate-pinned seeds and their standard-port alternatives; `manifest`, `trial` and `standard` select explicit profiles. Discovery never grants consensus authority or changes Genesis. Standard-port fallback uses direct native TLS listeners so signed address announcements see the actual source IP.

UpCloud's documented trial range is 33434–33534. Actual C→A/B connections in that range timed out although A↔B worked. Native TLS 1.3, PING, chain-state retrieval and signed address announcements succeeded from C to B on 443/80. These are TCP observations; UDP and application delivery require their own evidence.

Evidence is stored at `/home/admin/release-validation/three-node-20261031`. Public reports exclude credentials and private keys. Social Federation bilateral binding, native TLS public proof distribution, tamper rejection and durable revocation have now passed on three physical hosts (`social-three-result.json`). This does not certify chat or mail delivery. Remaining work includes common-height state/hash comparison, three-producer blocks, rolling recovery, third-node transport/application coverage, Social Federation deployment and final artifact alignment. Modules must retain their exact tested scope in published status matrices.
