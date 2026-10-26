"""Adversarial GIMPS protocol, arithmetic, and durable ownership regressions."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ziokt._runtime import _native_gimps as G
from ziokt.effort_gimps import GimpsPool, PrimeNetAdapter, ResourceGovernor, parse_official_gimps_proof_file
from ziokt.gimps_files import verify_proof
from ziokt.protocol import ProtocolError

FIXTURES = Path(__file__).parent / 'fixtures/gimps'


class Boundaries(unittest.TestCase):
    def test_real_official_proof_rejects_every_corrupt_residue(self):
        for exponent in (127, 521):
            raw = base64.b64decode((FIXTURES / f'p{exponent:07d}.proof.b64').read_text())
            proof = parse_official_gimps_proof_file(raw)
            offset = raw.index(b'NUMBER=')
            offset = raw.index(b'\n', offset) + 1
            for i in range(proof['power'] + 1):
                bad = bytearray(raw)
                bad[offset + i * proof['residue_bytes']] ^= 1
                with self.subTest(exponent=exponent, residue=i), self.assertRaises(ValueError):
                    verify_proof(bytes(bad))
            for invalid in (raw[:-1], raw + b'\x00', b'[GIMPS PRP PROOF]\nExponent=127\n',
                            raw.replace(b'NUMBER=M' + str(exponent).encode(), b'NUMBER=M2000000000')):
                with self.assertRaises(ValueError):
                    verify_proof(invalid)

    def test_rehashed_false_checkpoint_is_rejected(self):
        proof = G.generate_prp_proof(127)
        bad = copy.deepcopy(proof)
        checkpoint = bad['gerbicz_checkpoints'][1]
        state = int(checkpoint['state'], 16) + 1
        checkpoint.update(state=hex(state), state_hash=hashlib.sha256(f"127:{checkpoint['iteration']}:{state:x}".encode()).hexdigest(),
                          res64=f'{state & ((1 << 64) - 1):016X}', math_residue_q=state % G.GERBICZ_MODULUS_Q)
        previous = bad['gerbicz_checkpoints'][0]['hash']
        for chk in bad['gerbicz_checkpoints'][1:]:
            chk['hash'] = hashlib.sha256(f"{previous}:{chk['iteration']}:{chk['state_hash']}:{chk['res64']}:{chk['math_residue_q']}".encode()).hexdigest()
            previous = chk['hash']
        with self.assertRaisesRegex(ValueError, 'recurrence'):
            G.verify_prp_proof(127, bad)
        bad = copy.deepcopy(proof)
        bad['gerbicz_check']['product'] = '0x1'
        with self.assertRaisesRegex(ValueError, 'Gerbicz'):
            G.verify_prp_proof(127, bad)
        for engine in ('prime95', 'mprime', None):
            with self.assertRaisesRegex(ValueError, 'CAPACITY'):
                G.verify_prp_proof(127, dict(proof, engine=engine), max_native_exponent=64)
        self.assertFalse(ResourceGovernor(max_native_exponent=64).check_exponent_capacity(127, True))
        bad = copy.deepcopy(proof)
        bad['proof_steps'][0]['odd'] = not bad['proof_steps'][0]['odd']
        with self.assertRaisesRegex(ValueError, 'parity'):
            G.verify_prp_proof(127, bad)

    def test_generic_success_and_untrusted_endpoints_never_acknowledge(self):
        for body in ('{"status":"accepted"}', '<html>success: result accepted</html>',
                     '{"pnErrorResult":false,"pnErrorDetail":"ok"}', 'pnErrorResult=0\npnErrorResult=1\npnErrorDetail=ok'):
            self.assertFalse(PrimeNetAdapter.parse_primenet_response(body)[0])
        self.assertTrue(PrimeNetAdapter.parse_primenet_response('pnErrorResult=0\npnErrorDetail=SUCCESS')[0])
        for url in ('https://example.com/', 'http://v5.mersenne.org/v5server/', 'https://v5.mersenne.org.evil/v5server/'):
            with patch('urllib.request.build_opener', side_effect=AssertionError('untrusted network request')):
                self.assertFalse(PrimeNetAdapter().transmit_v5_result(127, '{}', primenet_url=url)['acknowledged'])

    def test_official_transport_binds_request_and_receipt(self):
        import io
        import sqlite3
        from urllib.parse import parse_qs, urlsplit
        result = (FIXTURES / 'mprime-results.jsonl').read_text().splitlines()[0]
        with sqlite3.connect(':memory:') as db:
            adapter = PrimeNetAdapter(db, 'https://v5.mersenne.org/v5server/', computer_id='a' * 32)
            adapter.record_assignment(127, 'b' * 32)
            response = io.BytesIO(b'pnErrorResult=0\npnErrorDetail=SUCCESS')
            response.status = 200
            with patch('urllib.request.build_opener') as factory:
                factory.return_value.open.return_value = response
                receipt = adapter.transmit_v5_result(127, result)
                query = parse_qs(urlsplit(factory.return_value.open.call_args.args[0].full_url).query)
                self.assertEqual(query['t'], ['ar'])
                self.assertEqual(query['k'], ['b' * 32])
                self.assertEqual(query['g'], ['a' * 32])
                self.assertEqual(query['n'], ['127'])
            self.assertTrue(receipt['acknowledged'])
            adapter.record_acceptance(127, receipt['receipt'])
            self.assertEqual(adapter.get_attestation(127)['status'], 'accepted')
            self.assertFalse(adapter.transmit_v5_result(521, result)['acknowledged'])

    def test_browser_worker_outputs_validate_in_native_verifier(self):
        import shutil
        import subprocess
        if not shutil.which('node'):
            self.skipTest('Node required for actual worker execution')
        root = Path(__file__).resolve().parents[1]
        source = (root / 'ziokt/effort/worker.js').read_text()
        import re
        known = json.loads(re.search(r'const KNOWN=(\[[^;]+\])', source).group(1))
        self.assertEqual(set(known), G.KNOWN_MERSENNE_PRIMES)
        script = r"""
const vm=require('vm'),fs=require('fs');
const p=Number(process.argv[1]),root=process.argv[2];
const context={self:{crypto:require('crypto').webcrypto},crypto:require('crypto').webcrypto,TextEncoder,BigInt,performance,setTimeout,
 postMessage:msg=>{if(msg.proof)process.stdout.write(JSON.stringify(msg.proof));if(msg.error)throw Error(msg.error)},close:()=>{},importScripts:()=>{}};
context.EFFORT_PROFILES=Array.from({length:5},()=>({batch:256,pause:0}));
vm.createContext(context);vm.runInContext(fs.readFileSync(root+'/ziokt/effort/worker.js','utf8'),context);
context.self.onmessage({data:{engine:'gimps',exponent:p,problem_id:String(p),proof_schema:'corium.gimps-prp-proof.v1',method:'prp-fiat-shamir',level:5,expires:Date.now()/1000+120}}).catch(e=>{process.stderr.write(e.stack);process.exitCode=1});
"""
        for exponent in (2, 3, 7, 67, 127, 521):
            with self.subTest(exponent=exponent):
                proof = json.loads(subprocess.check_output(['node', '-e', script, str(exponent), str(root)], timeout=12))
                if exponent == 2:
                    self.assertTrue(G.lucas_lehmer_verify(2, int(proof['residue']))[0])
                else:
                    self.assertTrue(G.verify_prp_proof(exponent, proof))

    def test_durable_leases_bind_owner_network_and_database_state(self):
        class Chain:
            def call(self, method, arguments):
                return {'schema': 'corium.gimps-challenge.v1', 'available': True, 'submitter_id': 'a' * 64,
                        'network_id': 'alpha', 'engine_id': 'engine', 'problem_id': '127', 'exponent': 127,
                        'proof_schema': 'corium.gimps-prp-proof.v1', 'method': 'prp-fiat-shamir', 'max_exponent': 100000}
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            owner = GimpsPool(Chain(), 'a' * 64, state, expected_network='alpha')
            self.addCleanup(owner.close)
            job = owner.issue()
            self.assertEqual(owner.issue()['token'], job['token'])
            owner.save_checkpoint(job['token'], {'iteration': 5, 's': '3'})
            owner.heartbeat(job['token'])
            restart = GimpsPool(Chain(), 'a' * 64, state, expected_network='alpha')
            self.addCleanup(restart.close)
            self.assertEqual(restart._get_active_job(job['token'])['checkpoint']['iteration'], 5)
            for address, network in (('b' * 64, 'alpha'), ('a' * 64, 'beta')):
                other = GimpsPool(Chain(), address, state, expected_network=network)
                try:
                    self.assertIsNone(other._get_active_job(job['token']))
                    with self.assertRaises(ProtocolError):
                        other.heartbeat(job['token'])
                finally:
                    other.close()
            with restart.db:
                restart.db.execute('DELETE FROM gimps_leases WHERE token=?', (job['token'],))
            self.assertIsNone(owner._get_active_job(job['token']))


if __name__ == '__main__':
    unittest.main()
