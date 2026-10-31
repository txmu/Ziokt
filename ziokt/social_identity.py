"""Opt-in, public-proof-only identity links. Links never grant application access."""
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
from .protocol import encoded, ProtocolError
from .security import verify

DOMAIN='Ziokt/social-identity/v1'
APPS={'corium','etp','community','watchat','content-fabric'}

def digest(value):return hashlib.sha256(encoded(value)).hexdigest()

def identity(value):
    if not isinstance(value,dict) or set(value)!={'app','network','algorithm','public_key'}:raise ValueError('exact key-addressed identity required')
    if value['app'] not in APPS or not isinstance(value['network'],str) or not re.fullmatch('[A-Za-z0-9_-]{1,64}',value['network']):raise ValueError('identity application/network')
    public=value['public_key']
    if value['algorithm']=='ed25519':
        if not isinstance(public,str) or not re.fullmatch('[a-f0-9]{64}',public):raise ValueError('canonical Ed25519 public key')
    elif value['algorithm'] in {'secp256k1','p256'}:
        from cryptography.hazmat.primitives.asymmetric import ec
        curve=ec.SECP256K1() if value['algorithm']=='secp256k1' else ec.SECP256R1()
        if not isinstance(public,str) or not re.fullmatch('0[23][a-f0-9]{64}',public):raise ValueError('canonical compressed EC public key')
        ec.EllipticCurvePublicKey.from_encoded_point(curve,bytes.fromhex(public))
    else:raise ValueError('unsupported signing algorithm')
    return digest(value)

def verify_proof(statement,proof):
    if not isinstance(proof,dict) or set(proof)!={'identity','signature'}:raise ValueError('signature proof fields')
    who=proof['identity'];key=identity(who)
    if who['algorithm']=='ed25519':
        verify({'schema':'ziokt.signed.v1','domain':DOMAIN,'public_key':who['public_key'],'payload':statement,'signature':proof['signature']},who['public_key'],DOMAIN)
    else:
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import hashes
        from cryptography.exceptions import InvalidSignature
        curve=ec.SECP256K1() if who['algorithm']=='secp256k1' else ec.SECP256R1()
        try:
            ec.EllipticCurvePublicKey.from_encoded_point(curve,bytes.fromhex(who['public_key'])).verify(bytes.fromhex(proof['signature']),(DOMAIN+'\n').encode()+encoded(statement),ec.ECDSA(hashes.SHA256()))
        except InvalidSignature as exc:
            raise ValueError('bad signature') from exc
    return key

class IdentityLinks:
    def __init__(self,path,network):
        if not isinstance(network,str) or not re.fullmatch('[A-Za-z0-9_-]{1,64}',network):raise ValueError('explicit federation network required')
        path=Path(path)
        if path.is_symlink():raise ValueError('identity database symlink')
        path.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
        self.db=sqlite3.connect(path,timeout=15,check_same_thread=False);path.chmod(0o600)
        self.db.execute('PRAGMA synchronous=FULL');self.lock=threading.RLock();self.network=network
        self.db.executescript('''CREATE TABLE IF NOT EXISTS social_links(owner TEXT,id TEXT,revision INTEGER,head TEXT,state TEXT,expires INTEGER,statement BLOB,PRIMARY KEY(owner,id));
        CREATE TABLE IF NOT EXISTS social_link_proofs(owner TEXT,id TEXT,revision INTEGER,proof BLOB,PRIMARY KEY(owner,id,revision));''')
    def close(self):self.db.close()
    def apply(self,owner,envelope):
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                result=self._apply(owner,envelope);self.db.commit();return result
            except BaseException:self.db.rollback();raise
    def _apply(self,owner,envelope):
        if not isinstance(owner,str) or not 1<=len(owner)<=256:raise ValueError('authenticated owner required')
        if not isinstance(envelope,dict) or set(envelope)!={'statement','proofs'} or len(encoded(envelope))>65536:raise ValueError('bounded signed statement required')
        s=envelope['statement'];fields={'schema','network','id','revision','previous','action','left','right','recovery','expires','issued'}
        if not isinstance(s,dict) or set(s)!=fields or s['schema']!='ziokt.social-link.v1' or s['network']!=self.network:raise ValueError('link schema/network')
        if not isinstance(s['id'],str) or not re.fullmatch('[a-f0-9]{64}',s['id']) or type(s['revision'])is not int or not 1<=s['revision']<=10000:raise ValueError('link identity/revision')
        now=int(time.time())
        if type(s['issued'])is not int or not 0<=s['issued']<=now+30 or type(s['expires'])is not int or not s['issued']<s['expires']<=s['issued']+366*86400:raise ValueError('bounded link validity')
        sides=[identity(s[k]) for k in ('left','right')]
        if sides[0]==sides[1]:raise ValueError('distinct identities required')
        recovery=s['recovery']
        if not isinstance(recovery,dict) or set(recovery)!={'left','right'}:raise ValueError('explicit recovery policy required')
        for side in recovery:
            policy=recovery[side]
            if not isinstance(policy,dict) or set(policy)!={'threshold','keys'} or not isinstance(policy['keys'],list) or len(policy['keys'])>5 or type(policy['threshold'])is not int or not 0<=policy['threshold']<=len(policy['keys']):raise ValueError('bounded recovery threshold')
            keys=[identity(key) for key in policy['keys']]
            if len(set(keys))!=len(keys) or bool(keys)!=bool(policy['threshold']):raise ValueError('unique explicitly enabled recovery keys required')
        proofs=envelope['proofs']
        if not isinstance(proofs,list) or not 1<=len(proofs)<=14:raise ValueError('bounded proof list required')
        signers={verify_proof(s,p) for p in proofs}
        if len(signers)!=len(proofs):raise ValueError('duplicate signer')
        row=self.db.execute('SELECT revision,head,state,statement FROM social_links WHERE owner=? AND id=?',(owner,s['id'])).fetchone()
        head=digest(envelope)
        if row and row[1]==head:return {'id':s['id'],'head':head,'revision':row[0],'state':row[2],'duplicate':True}
        if row:
            if row[2]=='revoked' or s['revision']!=row[0]+1 or s['previous']!=row[1]:raise ValueError('revoked or stale link head')
            old=json.loads(row[3]);oldkeys={identity(old[k]) for k in ('left','right')}
            if s['action']=='revoke':
                if not oldkeys&signers or any(s[k]!=old[k] for k in ('left','right','recovery')):raise ValueError('unilateral revocation proof required')
            elif s['action']=='rotate':
                if not oldkeys.union(sides)<=signers:raise ValueError('old and new identities must authorize rotation')
            elif s['action'] in {'recover-left','recover-right'}:
                side=s['action'][8:];other='right' if side=='left' else 'left';policy=old['recovery'][side]
                if not policy['threshold'] or len({identity(k) for k in policy['keys']}&signers)<policy['threshold'] or s[other]!=old[other] or identity(old[other]) not in signers or identity(s[side]) not in signers:raise ValueError('pre-authorized recovery quorum, new key and counterpart required')
            else:raise ValueError('existing link requires rotation/recovery/revocation')
        else:
            if s['action']!='bind' or s['revision']!=1 or s['previous']!='' or not set(sides)<=signers:raise ValueError('both identities must sign initial binding')
            if self.db.execute('SELECT count(*) FROM social_links WHERE owner=?',(owner,)).fetchone()[0]>=4096:raise ValueError('identity link quota')
        state='revoked' if s['action']=='revoke' else 'linked'
        self.db.execute('INSERT OR REPLACE INTO social_links VALUES(?,?,?,?,?,?,?)',(owner,s['id'],s['revision'],head,state,s['expires'],encoded(s)))
        self.db.execute('INSERT INTO social_link_proofs VALUES(?,?,?,?)',(owner,s['id'],s['revision'],encoded(envelope)))
        return {'id':s['id'],'head':head,'revision':s['revision'],'state':state,'duplicate':False,'grants_application_access':False}
    def list(self,owner):
        with self.lock:
            return {'items':[{'id':r[0],'revision':r[1],'head':r[2],'state':'expired' if r[3]=='linked' and r[4]<=time.time() else r[3],'expires':r[4],'statement':json.loads(r[5])} for r in self.db.execute('SELECT id,revision,head,state,expires,statement FROM social_links WHERE owner=? ORDER BY id LIMIT 4096',(owner,))]}
    def export(self,owner,id):
        with self.lock:return {'proofs':[json.loads(r[0]) for r in self.db.execute('SELECT proof FROM social_link_proofs WHERE owner=? AND id=? ORDER BY revision',(owner,id))]}

def main():
    """Sign on the device holding the native key; only public proof is printed."""
    import argparse
    from .protocol import secure_read,strict_json
    from cryptography.hazmat.primitives import serialization,hashes
    from cryptography.hazmat.primitives.asymmetric import ed25519,ec
    parser=argparse.ArgumentParser(description='Sign an explicit social statement locally; never uploads a private key')
    parser.add_argument('--statement',required=True);parser.add_argument('--identity',required=True);parser.add_argument('--key-file',required=True)
    args=parser.parse_args();statement=strict_json(Path(args.statement).read_bytes(),65536);who=strict_json(Path(args.identity).read_bytes(),4096);identity(who)
    raw=secure_read(args.key_file,16384)
    key=ed25519.Ed25519PrivateKey.from_private_bytes(raw) if who['algorithm']=='ed25519' and len(raw)==32 else serialization.load_pem_private_key(raw,password=None)
    message=(DOMAIN+'\n').encode()+encoded(statement)
    if who['algorithm']=='ed25519':
        if not isinstance(key,ed25519.Ed25519PrivateKey):raise ValueError('native key algorithm mismatch')
        signature=key.sign(message)
    else:
        if not isinstance(key,ec.EllipticCurvePrivateKey):raise ValueError('native EC signing key required')
        signature=key.sign(message,ec.ECDSA(hashes.SHA256()))
    proof={'identity':who,'signature':signature.hex()};verify_proof(statement,proof)
    print(json.dumps(proof,sort_keys=True))

if __name__=='__main__':main()
