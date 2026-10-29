"""Optional F2F chunks; Fabric still verifies Merkle proofs and final digest."""
import base64,hashlib,json,threading
from .protocol import encoded,ProtocolError
from .retroshare import RetroShare
from .retroshare_transport import FileCarrier

class Pending(ValueError):pass

def carrier(fabric):
    config=getattr(fabric,'retroshare_config',None)
    if not isinstance(config,dict) or config.get('enabled') is not True:raise PermissionError('RetroShare content transport disabled')
    return FileCarrier(RetroShare(config))

def offer(fabric,owner,oid,position):
    with fabric.lock:
        data=fabric.read_chunk(owner,oid,position);proof=fabric.chunk_proof(owner,oid,position)
    c=carrier(fabric);digest=hashlib.sha256(data).hexdigest()
    c.offer(data)
    result=c.offer_status(digest)
    return {'schema':'ziokt.retroshare-chunk.v1','object':oid,'position':position,'proof':proof,'offer':result,'fabric_verified':False}

def fetch(fabric,owner,alias,peer,oid,position):
    from .content_server import remote
    transport=peer.get('retroshare')
    if not isinstance(transport,dict) or set(transport)!={'peer','fallback'} or type(transport['fallback'])is not bool:raise ValueError('explicit RetroShare peer and fallback policy required')
    c=carrier(fabric)
    # Durable per-account/per-source request state survives process restarts.
    with fabric.transaction():fabric.db.execute('CREATE TABLE IF NOT EXISTS cf_rs_chunks(owner TEXT,source TEXT,object TEXT,position INTEGER,descriptor BLOB,updated INTEGER,PRIMARY KEY(owner,source,object,position))')
    with fabric.lock:row=fabric.db.execute('SELECT descriptor FROM cf_rs_chunks WHERE owner=? AND source=? AND object=? AND position=?',(owner,alias,oid,position)).fetchone()
    if row:descriptor=json.loads(row[0])
    else:
        descriptor=remote(peer,{'operation':'content.retroshare.offer','arguments':{'id':oid,'position':position}})
        if descriptor.get('schema')!='ziokt.retroshare-chunk.v1' or descriptor.get('object')!=oid or descriptor.get('position')!=position:raise ValueError('RetroShare descriptor binding mismatch')
        state=descriptor.get('offer',{})
        if state.get('state')!='offered':raise Pending('native hashing pending')
        if not isinstance(descriptor.get('proof'),list) or len(descriptor['proof'])>32:raise ValueError('bounded Merkle proof required')
        c.request(state['hash'],state['sha256'],state['size'],transport['peer'])
        with fabric.transaction():
            if fabric.db.execute('SELECT count(*) FROM cf_rs_chunks WHERE owner=?',(owner,)).fetchone()[0]>=128:raise ValueError('RetroShare active chunk quota')
            fabric.db.execute('INSERT OR IGNORE INTO cf_rs_chunks VALUES(?,?,?,?,?,unixepoch())',(owner,alias,oid,position,encoded(descriptor)))
    result=c.collect(descriptor['offer']['sha256'])
    if result.get('state')!='verified':raise Pending('native transfer pending')
    # The caller applies merkle_verify against its pinned object metadata.
    return {'data':result['data'],'proof':descriptor['proof']}

def accepted(fabric,owner,alias,oid,position):
    with fabric.transaction():fabric.db.execute('DELETE FROM cf_rs_chunks WHERE owner=? AND source=? AND object=? AND position=?',(owner,alias,oid,position))
