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
        outgoing_a=a.authorize('alice','author','content-native-bridge','news.bridge',expires=expires,allow=True)['id']
        outgoing_b=b.authorize('bob','author','content-native-bridge','news.bridge',expires=expires,allow=True)['id']
        offer_a=a.offer_authorization('bob','author','content-native-bridge','news.bridge',target=second.public,expires=expires,allow=True)
        offer_b=b.offer_authorization('alice','author','content-native-bridge','news.bridge',target=first.public,expires=expires,allow=True)
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
        # A native inventory snapshot detects new old-timestamp arrivals; it never
        # advances a timestamp cursor past delayed signed content.
        initial=b.sync('bob',incoming_a,limit=1);assert not initial['scan_complete']
        late=workers[0].call('etp.forum.publish',{'topic':'content-native-bridge','author':'author','content':'late-arriving native text','parent_id':None,'timestamp':int(time.time())-3600})
        await_post(workers[1],late['id'])
        assert b.sync('bob',incoming_a,limit=1)['state']=='restarting_snapshot'
        parent_native=workers[0].call('etp.forum.publish',{'topic':'content-native-bridge','author':'author','content':'native parent for mapping','parent_id':None})
        child_native=workers[0].call('etp.forum.publish',{'topic':'content-native-bridge','author':'author','content':'native child for mapping','parent_id':parent_native['id']})
        await_post(workers[1],child_native['id']);await_post(workers[1],parent_native['id'])
        try:b.ingest('bob',incoming_a,child_native['id'])
        except ProtocolError as error:assert error.code=='ETP_PARENT_PENDING'
        else:raise AssertionError('unmapped native parent was silently discarded')
        for _ in range(64):
            synchronized=b.sync('bob',incoming_a,limit=2)
            if synchronized['content_complete']:break
        else:raise AssertionError('durable native inventory/parent queue did not converge: '+json.dumps(synchronized))
        assert second._get('bob','<etp-'+late['id']+'@etp.invalid>')['body']=='late-arriving native text'
        assert second._get('bob','<etp-'+child_native['id']+'@etp.invalid>')['references']==['<etp-'+parent_native['id']+'@etp.invalid>']
        b.revoke('bob',incoming_a)
        try:b.ingest('bob',incoming_a,observed[0])
        except PermissionError:pass
        else:raise AssertionError('revoked native identity retained import permission')
        # Application HTTP binding uses the very same already pinned real native process.
        # No mock transport or replacement Forum is introduced by the binding test.
        import threading,urllib.request,urllib.error
        from ziokt.content_server import server
        route=json.loads((root/'forum-application-router.json').read_text())['components']['etp']
        remote_author=workers[1].call('etp.forum.identity',{'name':'author'})['author_id']
        native_config={'gateway':{key:route[key] for key in ('binary','digest','config')},'accounts':{'alice':{'aliases':['author'],'topics':['content-native-bridge'],'groups':['news.bridge'],'remote_authors':[remote_author]}}}
        http=server(first,{'port':0,'native_etp':native_config,'tokens':[{'account':'alice','token':'native-api-test-token','scopes':['content:read','content:write','netnews:write']}]})
        first.native_etp.instance=workers[0]
        thread=threading.Thread(target=http.serve_forever);thread.start()
        def api(operation,arguments):
            request=urllib.request.Request('http://127.0.0.1:'+str(http.server_port)+'/api',json.dumps({'operation':operation,'arguments':arguments}).encode(),{'Content-Type':'application/json','Authorization':'Bearer native-api-test-token'})
            with urllib.request.urlopen(request) as response:return json.load(response)
        try:
            assert api('content.etp.status',{})['grants']
            article=api('netnews.post',{'groups':['news.bridge'],'subject':'Native API article','body':'real application adapter content'})
            sent=api('content.etp.export',{'grant':outgoing_a,'record':article['id']})
            assert sent['state']=='native_stored' and not sent['remote_delivery_confirmed']
            observed_api=await_post(workers[1],sent['native_id'])
            assert b'real application adapter content' in b''.join(__import__('base64').b64decode(part) for part in observed_api['content_base64'])
            assert api('content.etp.revoke',{'grant':outgoing_a})['revoked']
            try:api('content.etp.export',{'grant':outgoing_a,'record':article['id']})
            except urllib.error.HTTPError as denied:assert denied.code==403;denied.close()
            else:raise AssertionError('application API bypassed grant revocation')
        finally:http.shutdown();http.server_close();thread.join()
        print(json.dumps({'schema':'ziokt.etp-content-e2e.v1','state':'verified','real_native_nodes':2,'independent_fabric_databases':2,'native_inventory_cursor':True,'late_arrival_recovered':True,'authenticated_application_api':True,'mutual_signed_grants':True,'reply_mapping':True,'withdrawal_mapping':True,'native_retry_idempotence':True,'loop_suppression':True,'revocation_enforced':True,'attachments_transferred':False,'all_native_adapters_complete':False}))
    finally:first.close();second.close()
