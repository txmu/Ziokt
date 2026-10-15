"""Explicit pairwise component exchange using existing SafeFS and private mail.

Only pinned application identities can exchange opaque artifacts. Receiving an
artifact never runs code, changes a Profile, installs a package or sends a notice.
"""
import hashlib
import hmac
from pathlib import Path
import re

from .ano import defence
from .community import hash_id
from .community_privacy import mailbox_public, seal_mail, open_mail
from .protocol import ProtocolError, encoded, identifier, strict_json
from .safefs import Vault, MAX_FILE
from .security import sign

COMPONENTS=frozenset({'shadow6','corium','watchat','safefs','zda','ufs','dcpm','tc16','etp','sim-manager','tri'})
KINDS=frozenset({'file','package','compute-result','simulation','chat-attachment','notification','profile','extension','ledger-proof'})
PUBLIC=re.compile('[a-f0-9]{64}\\Z')

class ComponentLinks:
    def __init__(self,community,component,signing_key,mailbox_key,peers,workspace):
        if component not in COMPONENTS or not isinstance(mailbox_key,bytes) or len(mailbox_key)!=32 or not isinstance(peers,dict) or len(peers)>len(COMPONENTS)-1:
            raise ProtocolError('INVALID_LINK','bounded component identity and pinned peers required')
        checked={}
        for name,peer in peers.items():
            if (name not in COMPONENTS or name==component or not isinstance(peer,dict) or set(peer)!={'signing_public','mailbox_public','kinds'} or
                any(not isinstance(peer[k],str) or not PUBLIC.fullmatch(peer[k]) for k in ('signing_public','mailbox_public')) or
                not isinstance(peer['kinds'],list) or not peer['kinds'] or len(peer['kinds'])>len(KINDS) or any(not isinstance(k,str) or k not in KINDS for k in peer['kinds']) or len(set(peer['kinds']))!=len(peer['kinds'])):
                raise ProtocolError('INVALID_LINK','exact pinned peer capabilities required')
            checked[name]={**peer,'kinds':frozenset(peer['kinds'])}
        self.community=community;self.component=component;self.signing_key=signing_key;self.mailbox_key=mailbox_key;self.peers=checked;self.workspace=Path(workspace)
        self.public=sign({},signing_key,'test')['public_key']
        self.community._member(self.public,'files');self.community._member(self.public,'mail')
        with self.community.db:self.community.db.execute('CREATE TABLE IF NOT EXISTS component_deliveries (scope TEXT NOT NULL,source TEXT NOT NULL,operation TEXT NOT NULL,commitment TEXT NOT NULL,event TEXT NOT NULL,PRIMARY KEY(scope,source,operation))')

    def _peer(self,name,kind):
        peer=self.peers.get(name) if isinstance(name,str) else None
        decision=defence({'known_component':isinstance(name,str) and name in COMPONENTS,'pinned_identity':peer is not None,'allowed_kind':peer is not None and isinstance(kind,str) and kind in peer['kinds']},('known_component','pinned_identity','allowed_kind'))
        if decision['decision']!='allow':raise ProtocolError('POLICY_DENIED','explicit component capability required')
        return peer

    def send(self,target,kind,name,data,operation):
        peer=self._peer(target,kind);identifier(operation,'component operation')
        if not isinstance(data,bytes) or len(data)>MAX_FILE:raise ProtocolError('LINK_LIMIT','bounded component bytes required')
        from .safefs import virtual_name
        virtual_name(name)
        context=encoded({'source':self.component,'target':target,'source_public':self.public,'target_public':peer['signing_public'],'mailbox_public':peer['mailbox_public'],'operation':operation})
        namespace='link-'+hashlib.sha256(context).hexdigest()[:48]
        commitment=hmac.new(self.signing_key,b'Ziokt/link/commit/v1\0'+context+encoded({'kind':kind,'name':name})+data,hashlib.sha256).hexdigest()
        object_key=hmac.new(self.signing_key,b'Ziokt/link/object/v1\0'+context+commitment.encode(),hashlib.sha256).digest()
        with self.community.lock:
            prior=self.community.view('files',namespace)['events']
            if prior:
                if len(prior)!=1 or prior[0]['author']!=self.public or prior[0]['deleted'] or prior[0]['body']['name']!='Opaque component object '+commitment:
                    raise ProtocolError('IDEMPOTENCY_CONFLICT','component operation already has different content')
                file_event=prior[0]['id']
            else:
                blob=Vault(self.workspace,'component-link',object_key).seal(name,data)
                manifest=self.community.put_file(blob)
                file_event=self.community.publish(self.signing_key,'files',namespace,{'name':'Opaque component object '+commitment,**manifest})
            offers=self.community.view('mail',namespace)['events']
            if offers:
                if len(offers)!=1 or offers[0]['author']!=self.public or offers[0]['deleted']:raise ProtocolError('IDEMPOTENCY_CONFLICT','conflicting component delivery')
                return {'schema':'ziokt.component-offer.v1','event':offers[0]['id'],'duplicate':True,'plaintext_disclosed':False}
            reference={'schema':'ziokt.component-reference.v1','source':self.component,'target':target,'kind':kind,'operation':operation,'file_event':file_event,'commitment':commitment,'key':object_key.hex()}
            sealed=seal_mail(peer['signing_public'],peer['mailbox_public'],'Ziokt component artifact v1',encoded(reference).decode())
            event=self.community.publish(self.signing_key,'mail',namespace,sealed)
            return {'schema':'ziokt.component-offer.v1','event':event,'duplicate':False,'plaintext_disclosed':False}

    def receive(self,event_id,*,expected_source):
        hash_id(event_id)
        events={e['id']:e for e in self.community.view('mail')['events']}
        event=events.get(event_id)
        if not event or event['deleted']:raise ProtocolError('INVALID_LINK','live signed component offer required')
        peer=self.peers.get(expected_source) if isinstance(expected_source,str) else None
        if peer is None or event['author']!=peer['signing_public']:raise ProtocolError('POLICY_DENIED','pinned source signature required')
        letter=open_mail(self.mailbox_key,self.public,event['body'])
        if letter['subject']!='Ziokt component artifact v1':raise ProtocolError('INVALID_LINK','component message domain required')
        ref=strict_json(letter['text'].encode(),2048)
        if (not isinstance(ref,dict) or set(ref)!={'schema','source','target','kind','operation','file_event','commitment','key'} or
            ref['schema']!='ziokt.component-reference.v1' or ref['target']!=self.component or ref['source']!=expected_source or
            any(not isinstance(ref[k],str) or not PUBLIC.fullmatch(ref[k]) for k in ('commitment','key'))):
            raise ProtocolError('SCOPE_MISMATCH','component recipient or reference scope rejected')
        self._peer(expected_source,ref['kind']);identifier(ref['operation'],'component operation');hash_id(ref['file_event'])
        files={e['id']:e for e in self.community.view('files')['events']};file=files.get(ref['file_event'])
        if not file or file['deleted'] or file['author']!=event['author'] or file['key']!=event['key'] or file['body']['name']!='Opaque component object '+ref['commitment']:
            raise ProtocolError('INVALID_LINK','matching signed component object required')
        name,data=Vault(self.workspace,'component-link',bytes.fromhex(ref['key'])).open(self.community.get_file(file['body']))
        scope=self.component+'/'+self.public+'/'+mailbox_public(self.mailbox_key)
        with self.community.lock,self.community.db:
            prior=self.community.db.execute('SELECT commitment,event FROM component_deliveries WHERE scope=? AND source=? AND operation=?',(scope,expected_source,ref['operation'])).fetchone()
            if prior is not None and prior!=(ref['commitment'],event_id):raise ProtocolError('IDEMPOTENCY_CONFLICT','component delivery conflicts with admitted operation')
            self.community.db.execute('INSERT OR IGNORE INTO component_deliveries VALUES (?,?,?,?,?)',(scope,expected_source,ref['operation'],ref['commitment'],event_id))
        return {'schema':'ziokt.component-delivery.v1','source':expected_source,'target':self.component,'kind':ref['kind'],'operation':ref['operation'],'name':name,'data':data,'duplicate':prior is not None,'auto_executed':False}
