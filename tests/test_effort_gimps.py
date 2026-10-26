import json
from pathlib import Path
import secrets
import sqlite3
import sys
import tempfile
import unittest

from test_native_integration import C
from ziokt.client import NativeClient
from ziokt.config import fingerprint
from ziokt.effort_gimps import GimpsPool
from ziokt.protocol import ProtocolError


class GimpsEffortTests(unittest.TestCase):
    def test_real_corium_independent_task_and_native_transaction(self):
        sys.path.insert(0,str(C));from test_core import Fixture
        fixture=Fixture();fixture.setUp();self.addCleanup(fixture.doCleanups)
        for path in fixture.root.rglob('*'):
            if path.is_dir():path.chmod(0o700)
        (fixture.etc/'identity.key').chmod(0o600)
        config=fixture.etc/'corix.conf';config.write_text('[ziokt]\nenabled=TRUE\nfederation_id=effort\nprovider_id=corium-local\nallow_mutations=TRUE\nallowed_operations=compute.submit\nallowed_resources=compute:gimps-effort\n');config.chmod(0o600)
        with sqlite3.connect(fixture.chain) as db:
            head,height=db.execute('SELECT hash,height FROM blocks ORDER BY height DESC LIMIT 1').fetchone()
            db.execute("INSERT OR REPLACE INTO chain_state VALUES ('chain_info',?)",(head+'|'+str(height),))
            db.execute("INSERT INTO compute_engines(engine_id,pkg_id,description,compute_program_hash,verifier_script_hash,is_active) VALUES ('gimps-effort','corium/built-in-gimps','native','BUILT_IN','BUILT_IN',1)")
            db.execute("INSERT INTO problem_sets(set_id,engine_id,metadata,activation_height) VALUES ('effort-set','gimps-effort',?,0)",(json.dumps({'start_exponent':5,'end_exponent':7}),))
        client=NativeClient('effort',{'native_project':'corium','provider_id':'corium-local','root':str(C),'native_config':str(config),'entrypoint_digest':fingerprint(C/'corix_v108.sh'),'network_id':'default','state_root':str(fixture.root)})
        pool=GimpsPool(client,fixture.identity,fixture.root/'effort-gimps',expected_network='default');self.addCleanup(pool.close)
        job=pool.issue();self.assertEqual(job['engine_id'],'gimps-effort');self.assertEqual(job['exponent'],5)
        proof={'schema':'corium.gimps-proof.v2','exponent':5,'method':'lucas-lehmer','residue':'0','is_prime':True,'iterations':3}
        with self.assertRaises(ProtocolError):pool.submit(job['token'],dict(proof,residue='1'))
        receipt=pool.submit(job['token'],proof);self.assertTrue(receipt['accepted']);self.assertFalse(receipt['confirmed'])
        self.assertTrue(pool.submit(job['token'],proof)['duplicate'])
        with sqlite3.connect(fixture.chain) as db:
            rows=db.execute("SELECT data FROM transactions WHERE type='submit_math_proof'").fetchall()
            self.assertEqual(len(rows),1);payload=json.loads(rows[0][0]);self.assertEqual(payload['engine_id'],'gimps-effort');self.assertEqual(payload['proof_data'],proof)
        self.assertEqual(pool.issue()['exponent'],7)

    def test_no_engine_zero_fallback_when_gimps_has_no_tasks(self):
        class Chain:
            def call(self,method,args):
                self_args=(method,args)
                if self_args!=('compute.challenge',{'engine':'gimps'}):raise AssertionError(self_args)
                return {'schema':'corium.gimps-challenge.v1','available':False,'submitter_id':'a'*64,'network_id':'default','reason':'no-active-gimps-engine'}
        with tempfile.TemporaryDirectory() as directory:
            pool=GimpsPool(Chain(),'a'*64,Path(directory),expected_network='default')
            try:self.assertFalse(pool.issue()['available']);self.assertFalse(pool.jobs)
            finally:pool.close()
