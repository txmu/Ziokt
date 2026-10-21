"""Public worker consent boundary, replay handling and real native submission."""
import hashlib
import http.client
import json
from pathlib import Path
import secrets
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from test_native_integration import C
from ziokt.client import NativeClient
from ziokt.config import fingerprint
from ziokt.effort_web import EffortPool,effort_server
from ziokt.protocol import ProtocolError


def solve(job):
    for number in range(int(job['start']),int(job['start'])+job['limit']):
        if hashlib.sha256((job['network_id']+job['submitter_id']+str(number)+job['problem_id']).encode()).hexdigest().startswith('000'):return str(number)
    raise AssertionError('no proof found in test range')


class FakeChain:
    def __init__(self):self.commits=0;self.unknown=False
    def call(self,method,params):
        if method=='compute.challenge':return {'engine_id':'corium/internal-engine-zero-v1','network_id':'test','submitter_id':'a'*64,'problem_id':'b'*64,'height':1,'difficulty':3,'available':True}
        if method=='operation.prepare':return {'plan_digest':'sha256:'+'f'*64}
        if method=='operation.commit':
            self.commits+=1
            if self.unknown:self.unknown=False;raise ProtocolError('RESULT_UNKNOWN','lost commit acknowledgement')
        return {'state':'committed','result':{'phase':'pending-native-consensus','transaction_hash':'c'*64}}


class EffortWebTests(unittest.TestCase):
    def test_packaged_inventory_and_assets_remain_available(self):
        from ziokt.ecosystem import inventory
        from importlib.resources import files
        with tempfile.TemporaryDirectory() as temporary:
            result=inventory(Path(temporary))
        self.assertEqual(len(result['components']),11)
        self.assertIn('一键人民助力',files('ziokt').joinpath('effort/index.html').read_text())
        self.assertEqual(files('ziokt').joinpath('ecosystem.json').read_bytes(),(Path(__file__).resolve().parents[1]/'companions/ecosystem.json').read_bytes())

    def test_proofs_ranges_replay_and_restart_reconciliation(self):
        with tempfile.TemporaryDirectory() as temporary:
            chain=FakeChain();pool=EffortPool(chain,'a'*64,Path(temporary));self.addCleanup(pool.close)
            job=pool.issue();nonce=solve(job)
            for token,value in [('unknown',nonce),(job['token'],'-1'),(job['token'],'0')]:
                with self.assertRaises(ProtocolError):pool.submit(token,value)
            chain.unknown=True
            with self.assertRaises(ProtocolError):pool.submit(job['token'],nonce)
            pool.close();self._cleanups.pop()
            restarted=EffortPool(chain,'a'*64,Path(temporary));self.addCleanup(restarted.close);again=restarted.issue()
            receipt=restarted.submit(again['token'],solve(again));self.assertTrue(receipt['duplicate']);self.assertEqual(chain.commits,1)
            self.assertFalse(receipt['confirmed'])
            wrong=EffortPool(chain,'f'*64,Path(temporary)/'wrong');self.addCleanup(wrong.close)
            with self.assertRaises(ProtocolError):wrong.issue()

    def test_expected_mainnet_mismatch_fails_before_issuing_worker_job(self):
        with tempfile.TemporaryDirectory() as temporary:
            pool=EffortPool(FakeChain(),'a'*64,Path(temporary),expected_network='ziokt-main');self.addCleanup(pool.close)
            with self.assertRaises(ProtocolError) as error:pool.issue()
            self.assertEqual(error.exception.code,'NETWORK_MISMATCH');self.assertFalse(pool.jobs)

    def test_http_origin_limits_and_one_explicit_start_button(self):
        with tempfile.TemporaryDirectory() as temporary:
            pool=EffortPool(FakeChain(),'a'*64,Path(temporary));self.addCleanup(pool.close)
            server=effort_server(pool,'http://127.0.0.1:0');self.addCleanup(server.server_close)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();self.addCleanup(thread.join,2);self.addCleanup(server.shutdown)
            def request(method,path,data=None,origin='http://127.0.0.1:0'):
                conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
                conn.request(method,path,data,{'Host':'127.0.0.1:0','Origin':origin,'Content-Type':'application/json'});response=conn.getresponse();body=response.read();conn.close();return response.status,body
            status,body=request('GET','/');self.assertEqual(status,200);self.assertEqual(body.count(b'<button'),1);self.assertIn('一键人民助力'.encode(),body)
            self.assertEqual(len(pool.jobs),0)
            self.assertEqual(request('POST','/api/job','{}',origin='https://evil.invalid')[0],409)
            self.assertEqual(request('POST','/api/job','{}',origin='https://unconfigured.ziokt.com')[0],409)
            status,body=request('POST','/api/job','{}');self.assertEqual(status,200);job=json.loads(body)
            proof=json.dumps({'token':job['token'],'nonce':solve(job)})
            self.assertEqual(request('POST','/api/proof',proof)[0],200)
            self.assertEqual(request('POST','/api/proof',json.dumps({'token':job['token'],'nonce':solve(job),'address':'attacker'}))[0],409)
            self.assertEqual(request('GET','/not-a-file')[0],404)
            self.assertEqual(request('POST','/api/job',' '*2049)[0],409)

    def test_real_corium_challenge_browser_nonce_and_native_transaction(self):
        sys.path.insert(0,str(C));from test_core import Fixture
        fixture=Fixture();fixture.setUp();self.addCleanup(fixture.doCleanups)
        for path in fixture.root.rglob('*'):
            if path.is_dir():path.chmod(0o700)
        (fixture.etc/'identity.key').chmod(0o600)
        config=fixture.etc/'corix.conf';config.write_text('[ziokt]\nenabled=TRUE\nfederation_id=effort\nprovider_id=corium-local\nallow_mutations=TRUE\nallowed_operations=compute.submit\nallowed_resources=compute:corium/internal-engine-zero-v1\n');config.chmod(0o600)
        client=NativeClient('effort',{'native_project':'corium','provider_id':'corium-local','root':str(C),'native_config':str(config),'entrypoint_digest':fingerprint(C/'corix_v108.sh'),'network_id':'default','state_root':str(fixture.root)})
        pool=EffortPool(client,fixture.identity,fixture.root/'effort');self.addCleanup(pool.close)
        job=pool.issue();self.assertEqual(job['submitter_id'],fixture.identity);nonce=solve(job)
        native_call=client.call
        def expires_before_commit(method,params):
            if method=='operation.prepare':return native_call(method,{**params,'lease_ms':250})
            if method=='operation.commit':raise ProtocolError('RESULT_UNKNOWN','process stopped before native commit')
            return native_call(method,params)
        client.call=expires_before_commit
        with self.assertRaises(ProtocolError):pool.submit(job['token'],nonce)
        client.call=native_call
        time.sleep(.3)
        job=pool.issue();nonce=solve(job)
        self.assertEqual(pool.db.execute('SELECT count(*) FROM submissions').fetchone()[0],0)
        with sqlite3.connect(fixture.chain) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM transactions WHERE type='submit_math_proof'").fetchone()[0],0)
        # Crash at the actual prepare/commit boundary, leaving a genuine native
        # prepared journal row and the durable web intent, then restart both clients.
        native_call=client.call
        def interrupted(method,params):
            if method=='operation.commit':raise ProtocolError('RESULT_UNKNOWN','simulated process loss before commit')
            return native_call(method,params)
        client.call=interrupted
        with self.assertRaises(ProtocolError):pool.submit(job['token'],nonce)
        client.call=native_call
        pool.close();self._cleanups.pop()
        pool=EffortPool(client,fixture.identity,fixture.root/'effort');self.addCleanup(pool.close)
        pool.issue()
        row=pool.db.execute('SELECT result FROM submissions').fetchone()
        receipt=json.loads(row[0]);self.assertTrue(receipt['accepted']);self.assertFalse(receipt['confirmed'])
        # The original job token is intentionally lost across restart.
        with self.assertRaises(ProtocolError):pool.submit(job['token'],nonce)
        with sqlite3.connect(fixture.chain) as db:
            tx=db.execute("SELECT data FROM transactions WHERE type='submit_math_proof'").fetchall();self.assertEqual(len(tx),1);self.assertEqual(json.loads(tx[0][0])['proof_data']['nonce'],nonce)
        self.assertFalse(pool.issue()['available'])
