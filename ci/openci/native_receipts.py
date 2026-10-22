"""CI-only actual OCI receipts for native Corium governance/settlement replay.

Both containers run on the CI host; distinct approved logical failure domains
are not proof of hardware independence. No production credentials are used.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import tarfile
import tempfile
import threading
from openci.client import Client
from openci.controller import Controller,Server,handler
from openci.runner import Runner
from openci import _consensus as consensus
from ziokt.security import sign
from test_openci_bootstrap import configuration,task


def execute(genesis,beneficiary,activation):
    if os.environ.get('GITHUB_ACTIONS')!='true':raise RuntimeError('OCI acceptance is CI only')
    image=json.loads((Path(__file__).with_name('runner-image.lock.json')).read_text())['image']
    with tempfile.TemporaryDirectory(prefix='openci-native-') as directory:
        root=Path(directory);config=configuration(root)
        controller=Controller(root/'controller',config)
        server=Server(('127.0.0.1',0),handler(controller));thread=threading.Thread(target=server.serve_forever);thread.start()
        try:
            origin='http://127.0.0.1:'+str(server.server_port);owner=Client(origin,'owner-integration-token')
            source=root/'source.tar'
            code=b"import pathlib\nassert pathlib.Path('/src/input.txt').read_text()=='13 21 34'\npathlib.Path('/out/result.json').write_text('{\"sum\":68}')\n"
            with tarfile.open(source,'w') as archive:
                for name,data in [('build.py',code),('input.txt',b'13 21 34')]:
                    member=tarfile.TarInfo(name);member.size=len(data);archive.addfile(member,io.BytesIO(data))
            reference=owner.upload('demo',source);workers=[];keys={}
            for name,pool in [('builder','community'),('verifier','trusted')]:
                owner.request('POST','/v1/workers/approve',{'worker':name,'arch':'x86_64','pool':pool,'cpu':1,'memory_mb':128,'slots':1,'projects':['demo']})
                key=root/(name+'.key');key.write_bytes(secrets.token_bytes(32));key.chmod(0o600);keys[name]=key
                public=sign({},key.read_bytes(),'key')['public_key'];evidence='sha256:'+hashlib.sha256(public.encode()).hexdigest()
                owner.request('POST','/v1/workers/signing-key',{'worker':name,'public':public,'evidence':evidence})
                owner.request('POST','/v1/workers/build-profile',{'worker':name,'domain':name,'approved_images':[image],'evidence':evidence})
                workers.append({'id':name,'public_key':public,'pool':pool,'failure_domain':name})
            primary=task('build',image,'community');second=task('verify',image,'trusted');second['needs']=['build']
            program={k:primary[k] for k in ('image','argv','arch','outputs','cpu','memory_mb','timeout')}
            bounty={'name':'build-release','beneficiary':beneficiary,'anchor':genesis,'source':reference,'program':program}
            policy={'schema':consensus.SCHEMA,'network':'test-openci-settlement','genesis':genesis,'activation_height':activation,'expiry_height':1000,'threshold':2,'workers':workers,'bounties':[bounty]}
            program['argv'].append(consensus.claim_token(policy,bounty));second['argv']=list(program['argv'])
            pid=owner.request('POST','/v1/pipelines',{'schema':'openci.pipeline.v1','project':'demo','nonce':'native-oci-chain','source':reference,'tasks':[primary,second]})['pipeline']
            for name in ('builder','verifier'):
                runner=Runner(Client(origin,name+'-integration-token'),root/name,[image],signing_key=keys[name]);runner.recover()
                result=runner.run_once()
                if result['state']!='completed':raise AssertionError('Actual OCI worker failed: '+json.dumps(result))
            owner.request('POST','/v1/verify',{'pipeline':pid,'task':'build','independent_task':'verify'})
            plan=owner.request('POST','/v1/contributions/prepare',{'pipeline':pid,'task':'build','policy':policy,'engine':'0'*64,'bounty':'build-release'})
            assert not plan['corium_settled'] and not plan['ledger_modified']
            output=root/'result.json';owner.download_artifact_file('demo',plan['payload']['proof_data']['receipts'][0]['attestation']['payload']['result']['artifact'],'result.json',output)
            assert json.loads(output.read_text())=={'sum':68}
            print('REAL_OCI_NATIVE_RECEIPTS '+json.dumps({'pipeline':pid,'plan_sha256':plan['plan_sha256'],'workers':plan['verification']['workers'],'hardware_independence_verified':False}),flush=True)
            return policy,plan['payload']
        finally:
            server.shutdown();server.server_close();thread.join();controller.close()
