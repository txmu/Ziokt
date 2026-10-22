"""CI-only real OCI task execution, native storage and independent re-execution."""
import io
import json
import os
import subprocess
from pathlib import Path
import sys
import tarfile
import tempfile
import threading
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from openci.client import Client
from openci.controller import Controller, Server, handler
from openci.runner import Runner
from test_openci_bootstrap import configuration, task


def main():
    if os.environ.get('GITHUB_ACTIONS')!='true':raise RuntimeError('OCI verification runs only in CI')
    image=json.loads(Path('ci/openci/runner-image.lock.json').read_text())['image']
    with tempfile.TemporaryDirectory(prefix='openci-e2e-') as temporary:
        root=Path(temporary);config=configuration(root)
        from openci.release import configure,ReleaseService
        native_config=root/'controller.json';native_config.write_bytes(config.read_bytes());native_config.chmod(0o600)
        configure(root,Path('companions/ufsdcpm/src'))
        config.write_bytes(native_config.read_bytes())
        controller=Controller(root/'controller',config)
        server=Server(('127.0.0.1',0),handler(controller));thread=threading.Thread(target=server.serve_forever);thread.start()
        try:
            origin='http://127.0.0.1:'+str(server.server_port)
            owner=Client(origin,'owner-integration-token')
            sentinel=root/'host-secret';sentinel.write_text('not-a-production-secret-but-must-not-be-mounted')
            code="""import json,os,pathlib,socket
assert os.getuid()==65532
assert not pathlib.Path(HOST_PATH).exists()
try: pathlib.Path('/src/input.txt').write_text('tampered')
except OSError: pass
else: raise RuntimeError('source was writable')
try: pathlib.Path('/etc/openci-root-write').write_text('bad')
except OSError: pass
else: raise RuntimeError('root filesystem was writable')
s=socket.socket();s.settimeout(.5)
assert s.connect_ex(('1.1.1.1',443))!=0
s.close()
numbers=[int(v) for v in pathlib.Path('/src/input.txt').read_text().split()]
pathlib.Path('/out/result.json').write_text(json.dumps({'sum':sum(numbers),'isolated':True},sort_keys=True))
print('Native isolated task completed',flush=True)
""".replace('HOST_PATH',repr(str(sentinel)))
            source=root/'snapshot.tar'
            with tarfile.open(source,'w') as archive:
                for name,payload in [('build.py',code.encode()),('input.txt',b'13 21 34')]:
                    member=tarfile.TarInfo(name);member.size=len(payload);archive.addfile(member,io.BytesIO(payload))
            primary=task('build',image,'community');second=task('verify',image,'trusted');second['needs']=['build']
            value={'schema':'openci.pipeline.v1','project':'demo','nonce':'real-oci-e2e','source':None,'tasks':[primary,second]}
            repository=root/'git-source';repository.mkdir()
            (repository/'build.py').write_text(code);(repository/'input.txt').write_bytes(b'13 21 34')
            def git(*args):return subprocess.check_output(['git','-C',str(repository),*args],text=True).strip()
            git('init','-b','main');git('add','build.py','input.txt');git('-c','user.name=OpenCI CI','-c','user.email=ci@example.invalid','commit','-m','Real pipeline source')
            commit=git('rev-parse','HEAD')
            settings=json.loads(config.read_text());webhook_key=root/'webhook.key';webhook_key.write_bytes(__import__('secrets').token_urlsafe(32).encode());webhook_key.chmod(0o600)
            settings['git_projects']={'demo':{'repository':str(repository),'ref':'refs/heads/main','template':value,'webhook_key':str(webhook_key)}}
            config.write_text(json.dumps(settings))
            import hashlib,hmac,urllib.request
            raw=json.dumps({'ref':'refs/heads/main','after':commit,'deleted':False}).encode()
            request=urllib.request.Request(origin+'/v1/webhooks/github/demo',raw,{'Content-Type':'application/json','X-Hub-Signature-256':'sha256='+hmac.new(webhook_key.read_bytes(),raw,hashlib.sha256).hexdigest(),'X-GitHub-Event':'push','X-GitHub-Delivery':'real-oci-source-commit'},method='POST')
            with urllib.request.urlopen(request) as response:pid=json.load(response)['pipeline']
            for worker,pool in [('builder','community'),('verifier','trusted')]:
                owner.request('POST','/v1/workers/approve',{'worker':worker,'arch':'x86_64','pool':pool,'cpu':1,'memory_mb':128,'slots':1,'projects':['demo']})
                runner=Runner(Client(origin,worker+'-integration-token'),root/worker,[image]);runner.recover()
                result=runner.run_once()
                if result['state']!='completed':
                    state=owner.request('GET','/v1/pipelines/'+pid)
                    for entry in state['tasks']:
                        if entry['receipt']:
                            log=root/(entry['id']+'.log');owner.download('demo',entry['receipt']['logs'],log);print(log.read_text(),file=sys.stderr)
                    raise RuntimeError('Real OCI task failed: '+json.dumps(result))
            state=owner.request('GET','/v1/pipelines/'+pid)
            assert state['state']=='completed' and state['release']=='unpublished'
            verification=owner.request('POST','/v1/verify',{'pipeline':pid,'task':'build','independent_task':'verify'})
            assert verification['status']=='matched'
            output=root/'result.json';owner.download_artifact_file('demo',state['tasks'][0]['receipt']['artifact'],'result.json',output)
            result=json.loads(output.read_text())
            assert result=={'isolated':True,'sum':68}
            # Actual OCI outputs must lose release authority when a producer is revoked.
            from openci.state import Error
            owner.request('POST','/v1/workers/disable',{'worker':'builder'})
            try:owner.request('POST','/v1/releases',{'pipeline':pid,'task':'build','name':'oci-ci-result','version':'1'})
            except Error as error:assert error.code=='RELEASE_VERIFIER'
            else:raise AssertionError('Revoked producer still authorized a native release')
            owner.request('POST','/v1/workers/approve',{'worker':'builder','arch':'x86_64','pool':'community','cpu':1,'memory_mb':128,'slots':1,'projects':['demo']})
            owner.request('POST','/v1/verify',{'pipeline':pid,'task':'build','independent_task':'verify'})
            release=owner.request('POST','/v1/releases',{'pipeline':pid,'task':'build','name':'oci-ci-result','version':'1'})
            assert release['state']=='published' and release['publication']['release_signed']
            installed=ReleaseService(controller).install(release['id'],root/'installed',activate=True)
            assert not installed['execution_authorized']
            assert json.loads((Path(installed['directory'])/'result.json').read_text())==result
            events=owner.request('GET','/v1/audit?pipeline='+pid)['events']
            assert any(event['action']=='task.verified' for event in events)
            logs=owner.request('GET','/v1/logs?pipeline='+pid+'&task=build&attempt=1')['chunks']
            assert logs, 'Real-time log stream was not persisted'
            print(json.dumps({'schema':'openci.oci-e2e.v1','state':'passed','pipeline':pid,'image':image,
                'git_webhook_trigger':True,'git_commit':commit,'native_content_storage':True,'real_oci_execution':True,'independent_reexecution':True,
                'distinct_hosts':False,'producer_revocation_blocks_release':True,'release_signed':True,'native_file_installed':True,'corium_settled':False}))
        finally:server.shutdown();server.server_close();thread.join();controller.close()


if __name__=='__main__':main()
