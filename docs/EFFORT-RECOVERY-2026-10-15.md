# Effort submission recovery

The existing private SQLite journal maps a challenge to one native operation and
nonce. Previously a crash after persisting that mapping, but before claiming the
native commit, left a prepared operation permanently unrecoverable: reconcile
correctly reported `prepared`, but the website never completed its commit.

Recovery now follows the actual native state:

- `prepared`: commit the same reviewed plan and original nonce;
- stale prepared plan: abort it using its exact plan digest, then remove only
  that unexecuted web mapping; a fresh operation may be prepared;
- `unknown`: native reconciliation determines the outcome. Never blindly issue
  another transaction for that intent;
- `committed`: persist the native receipt and return a duplicate receipt on retry;
- `aborted`: release the mapping without claiming a successful proof.

Operation IDs have a random suffix for a new attempt after an explicit abort.
The challenge primary key and native durable operation journal retain idempotence.
Existing stored IDs are accepted without migration. Live browser job tokens are
short-lived and intentionally do not survive restart.

Executed: `python3 -m unittest discover -s tests -p test_effort_web.py -v`
Result: **4 passed, 0 failed, 0 skipped**, 4.000 seconds. The native test uses a
real Corium temporary database, real challenge and proof, real prepare/abort/
commit journals, process-loss injection immediately before commit, expiry and
reopening the web database. A separate unit test covers lost commit acknowledgement.
No Rust compilation, external miners, private browser keys or new economic rules.

Production deployment additionally verified public trusted HTTPS, a secure
browser context, explicit start/stop, real proof admission, native block-1
inclusion and service restart with state retained. The private deployment receipt
and `/home/admin/fendou.txt` record actual node and access information. Inclusion
is not completion of the ten-block proof challenge window, and a single-validator
fresh chain is not evidence of remote replication or global fault tolerance.
