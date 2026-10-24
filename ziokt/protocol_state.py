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
        try:
            fd=os.open(self.path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,'O_NOFOLLOW',0),0o600)
        except FileExistsError:pass
        else:os.close(fd)
        import stat
        info=self.path.lstat()
        dna.require(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and info.st_nlink==1 and not info.st_mode&0o077,'private owner-controlled database required')
        with self.transaction() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS sequences (
                  chain TEXT, policy TEXT, sender TEXT, direction TEXT, value INTEGER,
                  PRIMARY KEY(chain,policy,sender,direction));
                CREATE TABLE IF NOT EXISTS records (
                  domain TEXT PRIMARY KEY, sender TEXT, document TEXT);
                CREATE TABLE IF NOT EXISTS evidence (
                  hash TEXT, owner TEXT, document TEXT, PRIMARY KEY(hash,owner));
                CREATE TABLE IF NOT EXISTS publications (
                  id TEXT PRIMARY KEY, kind TEXT, owner TEXT, document TEXT,
                  expires INTEGER, receipt TEXT, attempts INTEGER DEFAULT 0,
                  retry_at INTEGER DEFAULT 0);
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
        if self.settings.get('ownership_db'):
            db=sqlite3.connect(Path(self.settings['ownership_db']).resolve().as_uri()+'?mode=ro',uri=True,timeout=3)
            try:row=db.execute('SELECT owner_id,expires_at,registration_type FROM nns_records WHERE domain_name=?',(domain,)).fetchone()
            finally:db.close()
            dna.require(row is not None and row[0]==sender and type(row[1]) is int and (row[1]>int(time.time()) or row[1]==0 and row[2]=='genesis'),'current unexpired native domain ownership required')
        else:
            dna.require(self.settings.get('owners', {}).get(domain) == sender,
                        'domain ownership must be provisioned by trusted configuration')

    def signing_key(self):
        path = self.settings.get('signing_key')
        dna.require(path, 'configured persistent signing key required')
        key = serialization.load_pem_private_key(secure_read(Path(path)), password=None)
        dna.require(isinstance(key, ec.EllipticCurvePrivateKey)
                    and isinstance(key.curve, ec.SECP256K1), 'native owner key required')
        return key

    def announce(self, domain, target, owner='local', **args):
        key = self.signing_key()
        sender = hashlib.sha256(dna.public_key_pem(key).encode()).hexdigest()
        self.owner(domain, sender)
        chain = self.settings.get('chain_id',dna.CANONICAL_CHAIN_ID)
        policy = self.settings.get('policy_id',dna.CANONICAL_POLICY_ID)
        dna.require(args.get('chain_id',chain)==chain and args.get('policy_id',policy)==policy,'configured chain and policy required')
        with self.transaction() as db:
            binding = (chain, policy, sender, 'out')
            row = db.execute('SELECT value FROM sequences WHERE chain=? AND policy=? AND sender=? AND direction=?', binding).fetchone()
            sequence = (row[0] if row else 0) + 1
            if 'sequence' in args:
                dna.require(args['sequence'] == sequence, 'sequence must match durable next sequence')
            doc = dna.zdns_rna_announce(domain, target, key, chain, policy, sequence)
            doc.update(ownership_verified=True, ownership_source='native-nns' if self.settings.get('ownership_db') else 'operator-provisioned',
                       broadcast='not_configured', chain_registration='not_registered')
            db.execute('INSERT OR REPLACE INTO sequences VALUES (?,?,?,?,?)', (*binding, sequence))
            if self.settings.get('publish') is True:
                public={name:doc[name] for name in ('frame','pem','sender','chain_id','policy_id','record')}
                publication=hashlib.sha256(dna.canonical(public)).hexdigest()
                db.execute('INSERT INTO publications(id,kind,owner,document,expires) VALUES (?,?,?,?,?)',
                           (publication,'zdns',owner,json.dumps(public),doc['frame']['header']['expires_at']))
                doc.update(publication_id=publication,broadcast='queued',chain_registration='queued')
            db.execute('INSERT OR REPLACE INTO records VALUES (?,?,?)', (domain, sender, json.dumps(doc)))
            return doc

    def verify(self, frame, pem, **args):
        # Caller-provided previous_sequence can only tighten admission, never reset it.
        with self.transaction() as db:
            h = frame['header']
            for field in ('chain','policy'):
                expected=self.settings.get(field+'_id',getattr(dna,'CANONICAL_'+field.upper()+'_ID'))
                dna.require(h[field]==expected and args.get(field+'_id',expected)==expected,'configured RNA domain required')
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
            return dict(doc, ownership_verified=True, ownership_source='native-nns' if self.settings.get('ownership_db') else 'operator-provisioned', replay_state='persisted')

    def commit(self, owner, *args, publish=False):
        doc = dna.openci_commit_evidence(*args)
        key = self.signing_key()
        witness = {'schema': 'ziokt.openci-local-witness.v1', 'commitment_hash': doc['commitment_hash'],
                   'public_key': dna.public_key_pem(key), 'observed_at': int(time.time())}
        signature = key.sign(b'Ziokt/OpenCI/witness/v1\0' + dna.canonical(witness), ec.ECDSA(hashes.SHA256())).hex()
        doc.update(witness=witness, witness_signature=signature, persisted=True,
                   chain_registration='not_registered', worker_signature_verified=False)
        with self.transaction() as db:
            db.execute('INSERT OR IGNORE INTO evidence VALUES (?,?,?)', (doc['commitment_hash'], owner, json.dumps(doc)))
            if publish:
                dna.require(self.settings.get('publish') is True,'native publication must be configured')
                public={name:doc[name] for name in ('commitment_hash','witness','witness_signature')}
                public['schema']='ziokt.openci-evidence-anchor.v1'
                publication=hashlib.sha256(dna.canonical(public)).hexdigest()
                db.execute('INSERT OR IGNORE INTO publications(id,kind,owner,document,expires) VALUES (?,?,?,?,?)',
                           (publication,'evidence',owner,json.dumps(public),0))
                doc.update(publication_id=publication,chain_registration='queued')
                db.execute('UPDATE evidence SET document=? WHERE hash=? AND owner=?',(json.dumps(doc),doc['commitment_hash'],owner))
        return doc

    def evidence(self, owner, digest):
        with self.transaction() as db:
            row = db.execute('SELECT document FROM evidence WHERE hash=? AND owner=?', (digest, owner)).fetchone()
        dna.require(row is not None, 'persisted evidence not found')
        return json.loads(row[0])

    def publication(self,owner,publication):
        with self.transaction() as db:
            row=db.execute('SELECT kind,receipt,attempts FROM publications WHERE id=? AND owner=?',(publication,owner)).fetchone()
        dna.require(row is not None,'publication not found')
        return {'publication_id':publication,'kind':row[0],'attempts':row[2],
                **(json.loads(row[1]) if row[1] else {'broadcast':'queued','chain_registration':'queued'})}

    def flush(self,publisher,authorized=lambda owner,kind:True):
        now=int(time.time())
        with self.transaction() as db:
            # Claim a short lease; STORE and native operation IDs are retry-safe.
            rows=db.execute('SELECT id,kind,owner,document,expires,receipt FROM publications WHERE retry_at<=? ORDER BY retry_at,id LIMIT 8',(now,)).fetchall()
            for row in rows:db.execute('UPDATE publications SET retry_at=?,attempts=attempts+1 WHERE id=?',(now+120,row[0]))
        for publication,kind,owner,raw,expires,prior_raw in rows:
            if not authorized(owner,kind):continue
            try:
                doc=json.loads(raw)
                if kind=='zdns':self.owner(doc['record']['domain'],doc['sender'])
                prior=json.loads(prior_raw) if prior_raw else {}
                if expires and expires<now and prior.get('native_transaction'):
                    receipt={**prior,**publisher.inclusion(prior['native_transaction'])}
                else:receipt=publisher.publish(publication,kind,doc,expired=bool(expires and expires<now))
            except Exception:
                receipt={'broadcast':'pending','chain_registration':'pending','error':'NATIVE_PUBLICATION_UNCONFIRMED'}
            with self.transaction() as db:
                db.execute('UPDATE publications SET receipt=?,retry_at=? WHERE id=?',
                           (json.dumps(receipt),2**63-1 if receipt.get('broadcast')=='expired' or receipt.get('chain_registration')=='confirmed' and receipt.get('broadcast')=='acknowledged_by_known_peers' else now+30,publication))
