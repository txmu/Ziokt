"""Durable RNA admission and local OpenCI witnesses.

Ownership comes from an operator provisioned domain/public-key mapping, never
from a key supplied with a message. Local witnesses do not attest worker identity
or imply consensus registration. Writes serialize across processes and restarts.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from contextlib import contextmanager
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from . import dna_protocol as dna
from .protocol import secure_read


class ProtocolState:
    def __init__(self, root, settings=None):
        self.root = Path(root)
        self.settings = settings or {}
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        dna.require(not self.root.is_symlink(), 'regular private state directory required')
        self.root.chmod(0o700)
        self.path = self.root / 'protocol.sqlite'
        dna.require(not self.path.is_symlink(), 'regular protocol database required')
        fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600) if not self.path.exists() else None
        if fd is not None:
            os.close(fd)
        with self.transaction() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS sequences (
                  chain TEXT, policy TEXT, sender TEXT, direction TEXT, value INTEGER,
                  PRIMARY KEY(chain,policy,sender,direction));
                CREATE TABLE IF NOT EXISTS records (
                  domain TEXT PRIMARY KEY, sender TEXT, document TEXT);
                CREATE TABLE IF NOT EXISTS evidence (
                  hash TEXT, owner TEXT, document TEXT, PRIMARY KEY(hash,owner));
            ''')
        self.path.chmod(0o600)

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def owner(self, domain, sender):
        dna.require(type(domain) is str and domain == domain.lower()
                    and 1 <= len(domain) <= 255, 'canonical domain required')
        dna.require(self.settings.get('owners', {}).get(domain) == sender,
                    'domain ownership must be provisioned by trusted configuration')

    def signing_key(self):
        path = self.settings.get('signing_key')
        dna.require(path, 'configured persistent signing key required')
        key = serialization.load_pem_private_key(secure_read(Path(path)), password=None)
        dna.require(isinstance(key, ec.EllipticCurvePrivateKey)
                    and isinstance(key.curve, ec.SECP256K1), 'native owner key required')
        return key

    def announce(self, domain, target, **args):
        key = self.signing_key()
        sender = hashlib.sha256(dna.public_key_pem(key).encode()).hexdigest()
        self.owner(domain, sender)
        chain = args.get('chain_id') or dna.CANONICAL_CHAIN_ID
        policy = args.get('policy_id') or dna.CANONICAL_POLICY_ID
        with self.transaction() as db:
            binding = (chain, policy, sender, 'out')
            row = db.execute('SELECT value FROM sequences WHERE chain=? AND policy=? AND sender=? AND direction=?', binding).fetchone()
            sequence = (row[0] if row else 0) + 1
            if 'sequence' in args:
                dna.require(args['sequence'] == sequence, 'sequence must match durable next sequence')
            doc = dna.zdns_rna_announce(domain, target, key, chain, policy, sequence)
            doc.update(ownership_verified=True, ownership_source='operator-provisioned',
                       broadcast='not_configured', chain_registration='not_registered')
            db.execute('INSERT OR REPLACE INTO sequences VALUES (?,?,?,?,?)', (*binding, sequence))
            db.execute('INSERT OR REPLACE INTO records VALUES (?,?,?)', (domain, sender, json.dumps(doc)))
            return doc

    def verify(self, frame, pem, **args):
        # Caller-provided previous_sequence can only tighten admission, never reset it.
        with self.transaction() as db:
            h = frame['header']
            binding = (h['chain'], h['policy'], h['sender'], 'in')
            row = db.execute('SELECT value FROM sequences WHERE chain=? AND policy=? AND sender=? AND direction=?', binding).fetchone()
            previous = max(row[0] if row else 0, args.pop('previous_sequence', 0))
            doc = dna.zdns_rna_verify(frame, pem, previous_sequence=previous, **args)
            record = doc['record']
            dna.require(type(record) is dict and set(record) == {'schema', 'domain', 'target', 'published_at'}
                        and record['schema'] == 'ziokt.zdns-record.v1', 'exact ZDNS record required')
            self.owner(record['domain'], doc['sender'])
            dna.require(type(record['target']) is str and 1 <= len(record['target']) <= 255
                        and type(record['published_at']) is int
                        and record['published_at'] == h['issued_at'], 'record validity binding')
            db.execute('INSERT OR REPLACE INTO sequences VALUES (?,?,?,?,?)', (*binding, doc['sequence']))
            db.execute('INSERT OR REPLACE INTO records VALUES (?,?,?)', (record['domain'], doc['sender'], json.dumps(doc)))
            return dict(doc, ownership_verified=True, ownership_source='operator-provisioned', replay_state='persisted')

    def commit(self, owner, *args):
        doc = dna.openci_commit_evidence(*args)
        key = self.signing_key()
        witness = {'schema': 'ziokt.openci-local-witness.v1', 'commitment_hash': doc['commitment_hash'],
                   'public_key': dna.public_key_pem(key), 'observed_at': int(time.time())}
        signature = key.sign(b'Ziokt/OpenCI/witness/v1\0' + dna.canonical(witness), ec.ECDSA(hashes.SHA256())).hex()
        doc.update(witness=witness, witness_signature=signature, persisted=True,
                   chain_registration='not_registered', worker_signature_verified=False)
        with self.transaction() as db:
            db.execute('INSERT OR IGNORE INTO evidence VALUES (?,?,?)', (doc['commitment_hash'], owner, json.dumps(doc)))
        return doc

    def evidence(self, owner, digest):
        with self.transaction() as db:
            row = db.execute('SELECT document FROM evidence WHERE hash=? AND owner=?', (digest, owner)).fetchone()
        dna.require(row is not None, 'persisted evidence not found')
        return json.loads(row[0])
