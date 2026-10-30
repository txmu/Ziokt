"""Independent clients share only a gateway, never each other's state."""
import concurrent.futures
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from test_effort_web import FakeChain,solve
from ziokt.effort_web import EffortPool
from ziokt.effort_gimps import GimpsPool
from ziokt.protocol import ProtocolError

class Tasks(FakeChain):
    def call(self,method,params):
        if method=='compute.challenge' and params.get('engine')=='gimps':
            remaining=[p for p in (5,7,13,17,19,31) if p not in params.get('exclude_exponents',[])]
            if not remaining:return {'schema':'corium.gimps-challenge.v1','network_id':'test','submitter_id':'a'*64,'available':False}
            p=remaining[0]
            return {'schema':'corium.gimps-challenge.v1','network_id':'test','submitter_id':'a'*64,'available':True,'engine_id':'gimps','problem_id':str(p),'exponent':p,'proof_schema':'corium.gimps-proof.v2','method':'lucas-lehmer','max_exponent':4096}
        return super().call(method,params)

class CoordinationTests(unittest.TestCase):
    def test_zero_ranges_across_threads_instances_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            chain=FakeChain();root=Path(directory)
            pools=[EffortPool(chain,'a'*64,root) for _ in range(2)]
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
                    jobs=list(executor.map(lambda n:pools[n%2].issue(),range(64)))
                spans=sorted((int(j['start']),int(j['start'])+j['limit']) for j in jobs)
                self.assertTrue(all(b<=c for (_,b),(c,_) in zip(spans,spans[1:])))
                self.assertEqual(len({j['token'] for j in jobs}),64)
                pools[1].close();pools[1]=EffortPool(chain,'a'*64,root)
                self.assertGreaterEqual(int(pools[1].issue()['start']),spans[-1][1])
                winner=jobs[0];pools[0].submit(winner['token'],solve(winner))
                self.assertFalse(pools[0].job_status(jobs[2]['token'])['active'])
                self.assertFalse(pools[1].issue()['available']);self.assertEqual(chain.commits,1)
            finally:
                for pool in pools:pool.close()

    def test_gimps_exclusive_durable_leases_and_expiry_takeover(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);chain=Tasks();pools=[GimpsPool(chain,'a'*64,root,expected_network='test') for _ in range(2)]
            try:
                owners=[format(n,'048x') for n in range(1,7)]
                with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
                    jobs=list(executor.map(lambda n:pools[n%2].issue(owners[n]),range(6)))
                self.assertEqual({j['exponent'] for j in jobs},{5,7,13,17,19,31})
                self.assertEqual(len({j['token'] for j in jobs}),6)
                self.assertFalse(pools[0].issue('f'*48)['available'])
                self.assertEqual(pools[1].issue(owners[0])['token'],jobs[0]['token'])
                pools[1].close();pools[1]=GimpsPool(chain,'a'*64,root,expected_network='test')
                self.assertEqual(pools[1].issue(owners[0])['token'],jobs[0]['token'])
                pools[0].save_checkpoint(jobs[0]['token'],{'iteration':1,'s':'16'})
                with pools[0].db:pools[0].db.execute('UPDATE gimps_leases SET expires=? WHERE token=?',(int(time.time())-1,jobs[0]['token']))
                replacement=pools[1].issue('f'*48)
                self.assertEqual(replacement['exponent'],jobs[0]['exponent']);self.assertNotEqual(replacement['token'],jobs[0]['token'])
                self.assertEqual(replacement['checkpoint'],{'iteration':1,'s':'16'})
                with self.assertRaises(ProtocolError):pools[0].heartbeat(jobs[0]['token'])
            finally:
                for pool in pools:pool.close()
