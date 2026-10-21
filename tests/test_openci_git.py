"""Real native Git snapshots and signed HTTP webhook submission; no local builds."""
import hashlib,hmac,json,subprocess
from contextlib import closing
from pathlib import Path
import urllib.request,urllib.error
from test_openci_http import HTTPTests
from test_openci_state import pipeline
from openci.state import Error

class GitTests(HTTPTests):
    def test_real_git_webhook_auth_dedup_source_and_branch(self):
        repository=self.root/'repo';repository.mkdir()
        def git(*args):return subprocess.check_output(['git','-C',str(repository),*args],stderr=subprocess.DEVNULL,text=True).strip()
        git('init','-b','main');git('config','user.email','ci@example.invalid');git('config','user.name','OpenCI Test')
        (repository/'input.txt').write_text('real committed source\n');git('add','input.txt');git('commit','-m','source')
        commit=git('rev-parse','HEAD');key=b'local-only-webhook-secret-key-1234567890';keyfile=self.root/'webhook.key';keyfile.write_bytes(key);keyfile.chmod(0o600)
        config=json.loads(self.config.read_text());config['git_projects']={'demo':{'repository':str(repository),'ref':'refs/heads/main','template':pipeline(),'webhook_key':str(keyfile)}};self.config.write_text(json.dumps(config))
        raw=json.dumps({'ref':'refs/heads/main','after':commit,'deleted':False}).encode()
        def webhook(signature):
            request=urllib.request.Request(self.owner.origin+'/v1/webhooks/github/demo',raw,{'Content-Type':'application/json','X-Hub-Signature-256':signature,'X-GitHub-Event':'push','X-GitHub-Delivery':'delivery-1'},method='POST')
            with urllib.request.urlopen(request) as response:return json.load(response)
        with self.assertRaises(urllib.error.HTTPError) as denied:webhook('sha256:'+'0'*64)
        self.assertEqual(denied.exception.code,401);denied.exception.close()
        signature='sha256='+hmac.new(key,raw,hashlib.sha256).hexdigest();first=webhook(signature);second=webhook(signature)
        self.assertTrue(second['duplicate']);self.assertEqual(first['pipeline'],second['pipeline'])
        self.assertFalse(first['build_completed'])
        state=self.owner.request('GET','/v1/pipelines/'+first['pipeline']);self.assertEqual(state['state'],'submitted')
        with closing(self.controller.state.connect()) as db:source=json.loads(db.execute('SELECT body FROM pipelines WHERE id=?',(first['pipeline'],)).fetchone()[0])['source']
        snapshot=self.root/'snapshot.tar';self.owner.download('demo',source,snapshot)
        import tarfile
        with tarfile.open(snapshot) as archive:self.assertEqual(archive.extractfile('input.txt').read(),b'real committed source\n')
        git('checkout','-b','other');(repository/'input.txt').write_text('different');git('commit','-am','other')
        with self.assertRaises(Error) as denied:self.owner.request('POST','/v1/git/trigger',{'project':'demo','commit':git('rev-parse','HEAD'),'delivery':'other'})
        self.assertEqual(denied.exception.code,'GIT_REF_MISMATCH')

        git('checkout','main');(repository/'input.txt').write_text('new main source');git('commit','-am','new main')
        self.assertTrue(webhook(signature)['duplicate'])
        with self.assertRaises(Error) as conflict:self.owner.request('POST','/v1/git/trigger',{'project':'demo','commit':git('rev-parse','HEAD'),'delivery':'delivery-1'})
        self.assertEqual(conflict.exception.code,'GIT_DELIVERY_CONFLICT')
        from openci.git_source import tick
        config['git_projects']['demo']['interval_seconds']=60;self.config.write_text(json.dumps(config))
        self.assertEqual(len(tick(self.controller)['schedule_results']),1)
        self.assertEqual(tick(self.controller)['schedule_results'],[])
        with self.controller.state.transaction() as db:
            db.execute("INSERT INTO git_deliveries VALUES(?,?,?,'preparing',NULL,NULL,?)",('demo','interrupted',git('rev-parse','HEAD'),0))
        recovered=tick(self.controller)['schedule_results'];self.assertEqual(len(recovered),1)
        self.assertTrue(recovered[0]['source_snapshot_verified'])
