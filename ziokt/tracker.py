"""Optional leased peer rendezvous layered on the existing signed directory.

Transport is the existing TLS 1.3 mutual-authenticated /zfcp endpoint with scoped,
replay-protected grants. Tracker addresses are never inferred from remote IPs.
DHT/gossip records are not implicitly published in the tracker lease directory.
"""
import hashlib
import time
from types import SimpleNamespace
from .community import exact
from .protocol import ProtocolError,encoded,strict_json
from .security import verify

METHODS={'tracker.register','tracker.query','tracker.revoke','tracker.status'}
RELAY_DOMAIN='Ziokt/tracker-relay-authorization/v1'


class Tracker:
    def __init__(self,directory,*,anonymous_only=False,relay_authorities=()):
        self.directory=directory;self.policy=directory.policy
        self.community=SimpleNamespace(community_id=self.policy['community_id'])
        if type(anonymous_only) is not bool or len(relay_authorities)>16:
            raise ValueError('explicit bounded tracker privacy policy required')
        self.anonymous_only=anonymous_only or self.policy['privacy']=='restricted';self.relay_authorities=set(relay_authorities)
        if any(key not in self.policy['members'] for key in self.relay_authorities):raise ValueError('relay authorizers must be configured members')
        with directory.lock,directory.db:
            directory.db.execute('CREATE TABLE IF NOT EXISTS tracker_leases(public TEXT PRIMARY KEY,expires INTEGER,sequence INTEGER,document BLOB)')
            directory.db.execute('CREATE TABLE IF NOT EXISTS tracker_revocations(public TEXT PRIMARY KEY,sequence INTEGER)')

    def call(self,method,params,principal):
        if method not in METHODS or 'discover' not in self.policy['members'].get(principal,[]):
            raise ProtocolError('POLICY_DENIED','current discovery membership required')
        directory=self.directory
        with directory.lock,directory.db:
            directory._current();now=int(time.time())
            directory.db.execute('DELETE FROM tracker_leases WHERE expires<=?',(now,))
            if method=='tracker.status':
                exact(params,set())
                return {'schema':'ziokt.tracker.v1','community_id':self.community.community_id,
                        'optional':True,'dht_replacement':False,'anonymous_only':self.anonymous_only,
                        'maximum_lease_seconds':600,'registered':directory.db.execute('SELECT COUNT(*) FROM tracker_leases').fetchone()[0]}
            if method=='tracker.query':
                exact(params,{'limit'})
                if type(params['limit']) is not int or not 1<=params['limit']<=8:raise ProtocolError('INVALID_DISCOVERY','bounded tracker result required')
                # Rotation avoids an always-first set monopolizing bootstrapping.
                records=directory.db.execute('SELECT document FROM tracker_leases ORDER BY public LIMIT 64').fetchall()
                offset=directory.cursor%max(1,len(records));directory.cursor+=params['limit']
                records=records[offset:]+records[:offset]
                return {'schema':'ziokt.tracker-results.v1','community_id':self.community.community_id,
                        'policy':directory.policy_id,'records':[strict_json(row[0]) for row in records[:params['limit']]]}
            if method=='tracker.revoke':
                exact(params,{'sequence'})
                sequence=params['sequence']
                if type(sequence) is not int or not 0<=sequence<=2**53-1:raise ProtocolError('INVALID_DISCOVERY','bounded revocation sequence required')
                old=directory.db.execute('SELECT sequence FROM water WHERE public=?',(principal,)).fetchone()
                revoked=directory.db.execute('SELECT sequence FROM tracker_revocations WHERE public=?',(principal,)).fetchone()
                if any(row and sequence<row[0] for row in (old,revoked)):raise ProtocolError('REPLAY_REJECTED','revocation sequence cannot decrease')
                directory.db.execute('DELETE FROM tracker_leases WHERE public=?',(principal,))
                directory.db.execute('INSERT OR REPLACE INTO tracker_revocations VALUES (?,?)',(principal,sequence))
                return {'revoked':True,'sequence':sequence}
            exact(params,{'envelope','publish','anonymous','relay_authorization'})
            if params['publish'] is not True or type(params['anonymous']) is not bool:
                raise ProtocolError('POLICY_DENIED','explicit opt-in publication required')
            public,value=directory.validate(params['envelope'])
            if public!=principal:raise ProtocolError('POLICY_DENIED','cannot publish another identity')
            revoked=directory.db.execute('SELECT sequence FROM tracker_revocations WHERE public=?',(principal,)).fetchone()
            if revoked and value['sequence']<=revoked[0]:raise ProtocolError('REPLAY_REJECTED','revoked advertisement cannot be re-registered')
            if self.anonymous_only or params['anonymous']:
                clear=[endpoint for endpoint in value['endpoints'] if not endpoint['host'].endswith(('.onion','.i2p'))]
                if clear:
                    envelope=params['relay_authorization'];issuer=envelope.get('public_key') if isinstance(envelope,dict) else None
                    if issuer not in self.relay_authorities:raise ProtocolError('POLICY_DENIED','anonymous registration requires an explicitly authorized relay')
                    auth=verify(envelope,issuer,RELAY_DOMAIN)
                    expected={'community_id':self.community.community_id,'policy':directory.policy_id,'node':principal,
                              'endpoints_digest':'sha256:'+hashlib.sha256(encoded(clear)).hexdigest(),'expires':value['expires']}
                    if auth!=expected:raise ProtocolError('POLICY_DENIED','relay authorization scope or expiry differs')
            elif params['relay_authorization'] is not None:
                raise ProtocolError('INVALID_DISCOVERY','relay authorization is only used for anonymous registration')
            directory.ingest([params['envelope']])
            directory.db.execute('INSERT OR REPLACE INTO tracker_leases VALUES (?,?,?,?)',(public,value['expires'],value['sequence'],encoded(params['envelope'])))
            return {'registered':True,'expires':value['expires'],'sequence':value['sequence']}


class TrackerClient:
    def __init__(self,directory,private,endpoint,context):
        from .routes import resolve_endpoint
        resolve_endpoint(directory.policy['privacy'],endpoint)
        self.directory,self.private,self.endpoint,self.context=directory,private,endpoint,context

    def call(self,method,params,*,cancellation=None):
        if method not in METHODS:raise ValueError('tracker method required')
        from .security import grant
        from .community import content_id
        from .resilient_transport import request_resilient
        request={'provider_id':self.directory.policy['community_id'],'method':method,'params':params}
        token=lambda:grant(self.private,audience=request['provider_id'],action=method,resource='tracker:directory',
                           federation=request['provider_id'],request_digest=content_id(encoded(request)))
        result=request_resilient(self.directory.policy['privacy'],self.endpoint,self.context,request,token,cancellation=cancellation,total_timeout=15)
        if method=='tracker.query':
            exact(result,{'schema','community_id','policy','records'})
            if result['schema']!='ziokt.tracker-results.v1' or result['community_id']!=request['provider_id'] or result['policy']!=self.directory.policy_id:
                raise ProtocolError('SCOPE_MISMATCH','tracker replied for another federation')
            self.directory.ingest(result['records'],ignore_stale=True)
        return result
