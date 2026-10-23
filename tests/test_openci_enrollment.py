"""Real signed enrollment, SQLite transactions and live HTTP; no native builds."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import json
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import unittest
from openci.state import Store,Error
from openci import enrollment
from openci.controller import Controller,Server,handler
from openci.client import Client
from ziokt.security import sign


class EnrollmentTests(unittest.TestCase):
    def setUp(self):
        area=tempfile.TemporaryDirectory();self.addCleanup(area.cleanup);self.root=Path(area.name);self.store=Store(self.root/'state');self.secret=enrollment.setup(self.store)
        self.caps={'arch':'x86_64','pool':'community','cpu':1,'memory_mb':128,'slots':1,'projects':['demo'],'ttl':3600}
        self.invite=enrollment.invite(self.store,'owner',self.caps);self.key=secrets.token_bytes(32)
        self.request={'invite':self.invite['invite'],'proof':sign({'invite_sha256':hashlib.sha256(self.invite['invite'].encode()).hexdigest(),'worker':'my-node','nonce':secrets.token_hex(16)},self.key,enrollment.DOMAIN)}

    def test_concurrent_retry_has_one_worker_and_one_scoped_credential(self):
        with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:enrollment.redeem(self.store,self.secret,self.request),range(4)))
        self.assertTrue(all(result==results[0] for result in results))
        credential=results[0];self.assertFalse(credential['native_reward_authority']);self.assertTrue(credential['build_profile_approval_required'])
        self.assertEqual(enrollment.authenticate(self.store,hashlib.sha256(credential['access_token'].encode()).hexdigest())[1]['role'],'worker')
        with closing(self.store.connect()) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM workers').fetchone()[0],1)
            dumped='\n'.join(db.iterdump());self.assertNotIn(credential['access_token'],dumped);self.assertNotIn(self.invite['invite'],dumped)

    def test_bad_signature_different_worker_expiry_and_revoke_fail(self):
        bad=json.loads(json.dumps(self.request));bad['proof']['payload']['worker']='other'
        with self.assertRaises(Error):enrollment.redeem(self.store,self.secret,bad)
        credential=enrollment.redeem(self.store,self.secret,self.request)
        used={'invite':self.request['invite'],'proof':sign({**self.request['proof']['payload'],'worker':'other'},self.key,enrollment.DOMAIN)}
        with self.assertRaises(Error):enrollment.redeem(self.store,self.secret,used)
        self.store.disable_worker('owner','my-node')
        self.assertIsNone(enrollment.authenticate(self.store,hashlib.sha256(credential['access_token'].encode()).hexdigest()))
        with self.assertRaises(Error):enrollment.redeem(self.store,self.secret,self.request)
        with self.store.transaction() as db:db.execute('UPDATE enrollment_invites SET expires=0')
        with self.assertRaises(Error):enrollment.redeem(self.store,self.secret,self.request)

    def test_live_browser_origin_and_worker_only_cli_enrollment(self):
        config=self.root/'config.json';origin='https://openci.example.test'
        config.write_text(json.dumps({'public_origin':origin,'principals':{'owner':{'role':'admin','projects':[],'token_sha256':hashlib.sha256(b'owner').hexdigest()}}}));config.chmod(0o600)
        controller=Controller(self.root/'http',config);server=Server(('127.0.0.1',0),handler(controller));thread=threading.Thread(target=server.serve_forever);thread.start()
        def close():server.shutdown();server.server_close();thread.join();controller.close()
        self.addCleanup(close);endpoint='http://127.0.0.1:'+str(server.server_port);owner=Client(endpoint,'owner')
        invited=owner.request('POST','/v1/enrollments/invites',self.caps);invited['controller_origin']=endpoint
        invite_file=self.root/'invite.json';invite_file.write_text(json.dumps(invited));invite_file.chmod(0o600)
        key=self.root/'worker.key';token=self.root/'worker.token';area=self.root/'client'
        command=[sys.executable,'-m','openci','--root',str(area),'worker-enroll','--server',endpoint,'--invite-file',str(invite_file),'--worker','cli-node','--signing-key-file',str(key),'--credential-file',str(token)]
        first=subprocess.run(command,capture_output=True,text=True,timeout=10,check=True);second=subprocess.run(command,capture_output=True,text=True,timeout=10,check=True)
        self.assertEqual(first.stdout,second.stdout);self.assertEqual(key.stat().st_mode&0o777,0o600);self.assertEqual(token.stat().st_mode&0o777,0o600)
        self.assertNotIn(token.read_text().strip(),first.stdout+first.stderr)
        worker=Client(endpoint,token.read_text().strip());self.assertEqual(worker.request('GET','/v1/me')['role'],'worker')
        with self.assertRaises(Error) as denied:worker.request('POST','/v1/enrollments/invites',self.caps)
        self.assertEqual(denied.exception.status,403)
        import urllib.request,urllib.error
        for supplied,expected in ((origin,200),('https://evil.example',403)):
            request=urllib.request.Request(endpoint+'/v1/me',headers={'Authorization':'Bearer owner','Origin':supplied})
            try:
                with urllib.request.urlopen(request) as response:status=response.status
            except urllib.error.HTTPError as error:status=error.code;error.close()
            self.assertEqual(status,expected)
        with urllib.request.urlopen(endpoint+'/') as response:
            self.assertIn("script-src 'self'",response.headers['Content-Security-Policy']);self.assertEqual(response.headers['Cache-Control'],'no-store');self.assertIn(b'OpenCI',response.read())

if __name__=='__main__':unittest.main()
