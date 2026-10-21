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
