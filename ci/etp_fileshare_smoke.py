"""Actual native FileShare flavor over two authenticated ETP engines, CI only."""
import base64
import hashlib
import json
import time
from ziokt.protocol import ProtocolError


def run(workers,addresses,expected):
    listed=workers[0].call('etp.fileshare.list',{})
    assert len(listed['exports'])==1 and listed['exports'][0]['name']=='library-source'
    root=listed['exports'][0]['hash']
    assert workers[1].call('etp.fileshare.status',{'hash':root})['state']=='absent'
    request=workers[1].call('etp.fileshare.request',{'hash':root,'peer':addresses[0]})
    assert request['state'] in {'requested','downloading','locally_indexed'} and request['content_verified'] is False
    deadline=time.monotonic()+75
    while time.monotonic()<deadline:
        status=workers[1].call('etp.fileshare.status',{'hash':root})
        if status['state']=='locally_indexed':break
        if status['state'] in {'absent','timed_out'}:
            workers[1].call('etp.fileshare.request',{'hash':root,'peer':addresses[0]})
        time.sleep(.05)
    else:raise AssertionError('native FileShare did not complete: '+json.dumps(status))
    manifest=workers[1].call('etp.fileshare.manifest',{'hash':root})
    assert manifest['size']==len(expected) and manifest['content_verified'] is False
    content=[]
    for index in range(len(manifest['chunks'])):
        part=workers[1].call('etp.fileshare.chunk',{'hash':root,'index':index})
        assert part['native_chunk_verified'] is True
        content.append(b''.join(base64.b64decode(v,validate=True) for v in part['data_base64']))
    actual=b''.join(content);assert actual==expected
    try:workers[1].call('etp.fileshare.request',{'hash':root,'peer':'127.0.0.1:1'})
    except ProtocolError:pass
    else:raise AssertionError('unapproved FileShare peer accepted')
    print(json.dumps({'schema':'ziokt.native-fileshare-evidence.v1','native_etp_transport':True,
        'native_fileshare_flavor':True,'native_root':root,'bytes':len(actual),'sha256':hashlib.sha256(actual).hexdigest(),
        'library_import_verified':False,'dht_discovery_verified':False}))


def library_run(root,workers,addresses,expected,await_post):
    """Real signed Forum source -> native FileShare -> persistent Fabric book."""
    from ziokt.content_etp_library import EtpLibrary,SCHEMA
    from ziokt.content_fabric import Fabric
    native_root=workers[0].call('etp.fileshare.list',{})['exports'][0]['hash']
    author=workers[0].call('etp.forum.identity',{'name':'author'})['author_id']
    topic='native-library'
    workers[1].call('etp.forum.subscribe',{'topic':topic})
    source={'schema':SCHEMA,'topic':topic,'hash':native_root,
        'digest':'sha256:'+hashlib.sha256(expected).hexdigest(),'size':len(expected),
        'mime':'text/plain','public':True,'book':{'work_id':'etp-native-source','edition_id':'first',
        'title':'Native FileShare source','authors':['Native ETP author'],'license':'CC0-1.0'}}
    proof=workers[0].call('etp.forum.publish',{'topic':topic,'content':json.dumps(source),
        'author':'author','parent_id':None})['id']
    post=await_post(workers[1],proof)
    assert post['author_id']==author and post['signature_base64']
    policy={'authors':[author],'topics':[topic],'peers':[addresses[0]]}
    area=root/'native-library-fabric'
    fabric=Fabric(area)
    try:
        intake=EtpLibrary(fabric,workers[1],lambda owner:policy if owner=='native-reader' else None)
        job=intake.begin('native-reader',proof,addresses[0],'etp-library-book','public','native-ci')['job']
        deadline=time.monotonic()+75
        partial=intake.step('native-reader',job,1)
        while partial['state']=='waiting_native' and time.monotonic()<deadline:
            time.sleep(.1)
            partial=intake.step('native-reader',job,1)
        assert partial['state']=='receiving' and partial['native_delivery_verified'] is False, json.dumps(partial, sort_keys=True)
        fabric.close();fabric=Fabric(area)
        intake=EtpLibrary(fabric,workers[1],lambda owner:policy if owner=='native-reader' else None)
        result=intake.step('native-reader',job,32)
        assert result['state']=='complete' and result['native_delivery_verified'] is True
        assert fabric.verify_object('native-reader',result['object'])['size']==len(expected)
        actual=b''.join(fabric.read_chunk('native-reader',result['object'],i) for i in range((len(expected)+16383)//16384))
        assert actual==expected
        assert fabric._get('native-reader','etp-library-book','book')['file_id']==result['object']
        print(json.dumps({'schema':'ziokt.native-etp-library-evidence.v1','native_forum_signature':True,
            'native_fileshare_transfer':True,'durable_partial_resume':True,'library_import_verified':True,
            'object':result['object'],'source_proof':proof,'sha256':hashlib.sha256(actual).hexdigest(),
            'dht_discovery_verified':False}))
    finally:fabric.close()
