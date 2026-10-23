"""Cross-verify real ring proofs in the canonical coordinator and native module."""
import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
import test_shielded_ownership as fixture
from ziokt import _runtime as r

native=Path(__file__).resolve().parents[2]/'Corium/shielded_ownership.py'
spec=importlib.util.spec_from_file_location('corium_standalone_shielded',native);s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)


class NativeCopyTests(unittest.TestCase):
    # Reuse only the real 16-note fixture, not the existing parent test suite.
    setUp=fixture.ShieldedTests.setUp
    def test_cross_verification_and_mainnet_gate_remain_identical(self):
        ring=[self.notes[i] for i in self.value['ring']];message={k:v for k,v in self.value.items() if k!='proof'}
        actual=s.zs_ring_verify(self.network,message,ring,self.output['commitment'],self.value['proof'])
        self.assertEqual(actual,self.value['proof']['image'])
        index=self.value['ring'].index(self.identifier)
        proof=s.zs_ring_sign(self.network,message,ring,self.output['commitment'],index,s.zs_scalar(self.private['spend_key']),s.zs_ssub(s.zs_scalar(self.input['blind']),s.zs_scalar(self.output_witness['blind'])))
        self.assertEqual(r.zs_ring_verify(self.network,message,ring,self.output['commitment'],proof),actual)
        forged=copy.deepcopy(proof);forged['responses'][0][0]='ff'*32
        with self.assertRaises(ValueError):s.zs_ring_verify(self.network,message,ring,self.output['commitment'],forged)
        self.assertFalse(s.ZS_AUDITED)
        self.assertEqual(s.ZS_MAINNET_ENABLED,r.ZS_MAINNET_ENABLED)
        for enabled in (False,True):
            with patch.object(s,'ZS_MAINNET_ENABLED',enabled),patch.object(r,'ZS_MAINNET_ENABLED',enabled):
                for module in (s,r):
                    if enabled:module.zs_testnet('ziokt-main')
                    else:
                        with self.assertRaises(ValueError):module.zs_testnet('ziokt-main')
                self.assertEqual(s.zs_query(None,'ziokt-main','privacy.status',{}),r.zs_query(None,'ziokt-main','privacy.status',{}))
    def test_native_standalone_is_exact_canonical_source(self):
        canonical=Path(__file__).resolve().parents[1]/'spec/shielded_runtime.py'
        self.assertEqual(native.read_bytes(),canonical.read_bytes())
