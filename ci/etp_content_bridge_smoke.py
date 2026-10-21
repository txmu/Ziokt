"""Real two-node native ETP mesh <-> two independent Content Fabric databases."""
import json,time
from ziokt.content_fabric import Fabric
from ziokt.content_etp import EtpNews
from ziokt.protocol import ProtocolError


def run(root,workers,await_post):
    first=Fabric(root/'content-first');second=Fabric(root/'content-second',peers={first.public:{'groups':['news.bridge']}})
    first.peers[second.public]={'groups':['news.bridge']}
    try:
        first.create_group('alice','news.bridge');second.create_group('bob','news.bridge')
        a=EtpNews(first,workers[0]);b=EtpNews(second,workers[1]);expires=int(time.time())+3600
        outgoing_a=a.authorize('alice','author','native-forum','news.bridge',expires=expires,allow=True)['id']
        outgoing_b=b.authorize('bob','author','native-forum','news.bridge',expires=expires,allow=True)['id']
        offer_a=a.offer_authorization('bob','author','native-forum','news.bridge',target=second.public,expires=expires,allow=True)
        offer_b=b.offer_authorization('alice','author','native-forum','news.bridge',target=first.public,expires=expires,allow=True)
        await_post(workers[1],offer_a['native_proof']);await_post(workers[0],offer_b['native_proof'])
        incoming_a=b.accept_authorization('bob',offer_a['native_proof'],allow=True)['id']
        incoming_b=a.accept_authorization('alice',offer_b['native_proof'],allow=True)['id']
        original=first.post('alice',['news.bridge'],'Native linked article','original actual content',message_id='<bridge-original@example.invalid>')
        exported=a.export('alice',outgoing_a,original['id']);assert exported['state']=='native_stored' and not exported['remote_delivery_confirmed']
        await_post(workers[1],exported['native_id'])
        received=b.ingest('bob',incoming_a,exported['native_id'])
        assert second._get('bob',received['record'])['body']=='original actual content'
        assert b.ingest('bob',incoming_a,exported['native_id'])['duplicate']
        assert b.export('bob',outgoing_b,received['record'])['state']=='loop_suppressed'
        reply=second.post('bob',['news.bridge'],'Re: Native linked article','actual native reply',message_id='<bridge-reply@example.invalid>',references=[original['id']])
        returned=b.export('bob',outgoing_b,reply['id']);await_post(workers[0],returned['native_id'])
        linked=a.ingest('alice',incoming_b,returned['native_id'])
        assert first._get('alice',linked['record'])['references']==[original['id']]
        # Native publication occurs, readback is deliberately interrupted, then real retry
        # must find the same native ID because timestamp + signed bytes were journaled.
        recovery=first.post('alice',['news.bridge'],'Recovery','native recovery content',message_id='<bridge-recovery@example.invalid>')
        native=a.native;observed=[]
        def interrupted(identifier):
            post,content=native(identifier)
            try:payload=json.loads(content)
            except ValueError:payload={}
            if payload.get('subject')=='Recovery' and not observed:
                observed.append(identifier);raise ProtocolError('INJECTED_READBACK_INTERRUPTION','controlled recovery test')
            return post,content
        a.native=interrupted
        try:a.export('alice',outgoing_a,recovery['id'])
        except ProtocolError as error:assert error.code=='INJECTED_READBACK_INTERRUPTION'
        else:raise AssertionError('injected interruption was hidden')
        a.native=native
        reconciled=a.recover('alice',outgoing_a);assert reconciled['all_recovered'] and reconciled['results'][0]['native_id']==observed[0]
        first.withdraw('alice',original['id'])
        tombstone=a.export('alice',outgoing_a,original['id']);assert not tombstone['native_original_deleted']
        await_post(workers[1],tombstone['native_id']);b.ingest('bob',incoming_a,tombstone['native_id'])
        try:second._get('bob',original['id'])
        except PermissionError:pass
        else:raise AssertionError('withdrawn article remained visible')
        b.revoke('bob',incoming_a)
        try:b.ingest('bob',incoming_a,observed[0])
        except PermissionError:pass
        else:raise AssertionError('revoked native identity retained import permission')
        print(json.dumps({'schema':'ziokt.etp-content-e2e.v1','state':'verified','real_native_nodes':2,'independent_fabric_databases':2,'mutual_signed_grants':True,'reply_mapping':True,'withdrawal_mapping':True,'native_retry_idempotence':True,'loop_suppression':True,'revocation_enforced':True,'attachments_transferred':False,'all_native_adapters_complete':False}))
    finally:first.close();second.close()
