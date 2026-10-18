"""Local Corium-node adapter: suffix-free NNS + signed canonical transaction.

Trusts the operator's fully validating node for consensus. Does not advertise a
standalone light-client/finality proof. Optimistic gateway-only NNS rows fail.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
from . import _runtime
from .protocol import ProtocolError,strict_json
from .gateway_store import Store,digest_ok
from .static_site import cs_content


def readonly(path):
    return sqlite3.connect(Path(path).absolute().as_uri()+'?mode=ro',uri=True,timeout=3)


class CoriumNames:
    component='corium'
    def __init__(self,*,forum_db,chain_db,objects,network_id,namespace=None,dht_db=None,peers=()):
        self.forum_db,self.chain_db,self.network_id=forum_db,chain_db,network_id
        self.namespace=network_id if namespace is None else namespace
        self.store=Store(objects,dht_db,peers=peers)

    def __call__(self,root):
        from .naming import LABEL
        if not isinstance(root,str) or not LABEL.fullmatch(root):
            raise ProtocolError('NAME_REJECTED','suffix-free NNS key required')
        with closing(readonly(self.forum_db)) as db:
            row=db.execute('SELECT owner_id,target_hash,last_update_height,expires_at FROM nns_records WHERE domain_name=?',(root,)).fetchone()
        if row is None:raise ProtocolError('NAME_NOT_FOUND','NNS name not registered')
        owner,target,height,expiry=row
        if not digest_ok(target) or type(height) is not int or height<1:
            raise ProtocolError('NAME_REJECTED','invalid native NNS state')
        with closing(readonly(self.chain_db)) as db:
            block=db.execute('SELECT hash,transactions FROM blocks WHERE height=?',(height,)).fetchone()
            if not block:raise ProtocolError('NAME_REJECTED','NNS block unavailable')
            hashes=strict_json(block[1].encode())
            rows=db.execute("SELECT hash,type,data,signature,public_key,timestamp FROM transactions WHERE block_height=? AND type IN ('nns_register','nns_update') LIMIT 4097",(height,)).fetchall()
            if len(rows)>4096:raise ProtocolError('NAME_REJECTED','native proof budget exceeded')
            matched=None
            for txhash,kind,data,signature,public,timestamp in rows:
                if txhash not in hashes:continue
                if hashlib.sha256(public.rstrip('\n').encode()).hexdigest()!=owner:continue
                payload=strict_json(data.encode())
                records=payload.get('records',[]) if kind=='nns_update' else [payload]
                if not any(isinstance(record,dict) and record.get('domain_name')==root and record.get('target_hash')==target for record in records):continue
                raw=('{"type":'+json.dumps(kind)+',"data":'+data+',"timestamp":'+str(timestamp)+'}').encode()
                if hashlib.sha256(raw).hexdigest()!=txhash:continue
                _runtime.native_ec_verify(public,signature,raw)
                matched=txhash
            if matched is None:
                raise ProtocolError('NAME_REJECTED','NNS target is not bound by current native owner in canonical block; rebind after transfer')
        manifest=strict_json(cs_content(target,self.store.get))
        naming=manifest.get('ziokt_naming') if isinstance(manifest,dict) else None
        if not isinstance(naming,dict) or set(naming)!={'network_id','owner','revision','expires_at','delegations','published_suffixes'}:
            raise ProtocolError('NAME_NOT_FOUND','NNS target has no explicit Ziokt naming publication')
        if naming['network_id'] != self.namespace:
            raise ProtocolError('NAME_REJECTED','publication belongs to another chain')
        if type(naming['expires_at']) is not int:
            raise ProtocolError('NAME_REJECTED','explicit publication expiry required')
        return {'network_id':self.namespace,'owner':naming['owner'],'revision':naming['revision'],'expires_at':min(expiry,naming['expires_at']),
                'delegations':naming['delegations'],'published_suffixes':naming['published_suffixes'],
                'proof':{'kind':'local-validating-corium-node','network_registry':'NNS','nns_key':root,
                         'native_network_id':self.network_id,'native_owner':owner,'target_hash':target,'height':height,
                         'transaction_hash':matched,'block_hash':block[0]}}
