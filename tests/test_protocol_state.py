import concurrent.futures
import hashlib
import tempfile
import unittest
from pathlib import Path
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from ziokt import dna_protocol as dna
from ziokt.protocol_state import ProtocolState


class DurableTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.key=ec.generate_private_key(ec.SECP256K1())
        key_path=self.root/'key.pem'
        key_path.write_bytes(self.key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        key_path.chmod(0o600)
        self.sender=hashlib.sha256(dna.public_key_pem(self.key).encode()).hexdigest()
        self.settings={'signing_key':str(key_path),'owners':{'example.ziokt':self.sender}}
        self.state=ProtocolState(self.root/'state',self.settings)

    def test_restart_rejects_reset_sequence_and_accepts_next(self):
        doc=self.state.announce('example.ziokt','root:one')
        self.state.verify(doc['frame'],doc['pem'])
        restarted=ProtocolState(self.root/'state',self.settings)
        with self.assertRaises(ValueError):restarted.verify(doc['frame'],doc['pem'],previous_sequence=0)
        second=restarted.announce('example.ziokt','root:two')
        self.assertEqual(second['frame']['header']['sequence'],2)
        self.assertTrue(restarted.verify(second['frame'],second['pem'])['ownership_verified'])

    def test_concurrent_admission_has_one_winner(self):
        doc=self.state.announce('example.ziokt','root:one')
        def admit(_):
            try:
                ProtocolState(self.root/'state',self.settings).verify(doc['frame'],doc['pem'])
                return True
            except ValueError:return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(sum(pool.map(admit,range(4))),1)

    def test_unprovisioned_and_forged_owner_cannot_consume_sequence(self):
        with self.assertRaises(ValueError):self.state.announce('unknown.ziokt','root:one')
        other=ec.generate_private_key(ec.SECP256K1())
        doc=dna.zdns_rna_announce('example.ziokt','root:forged',other)
        with self.assertRaises(ValueError):self.state.verify(doc['frame'],doc['pem'])
        valid=self.state.announce('example.ziokt','root:valid')
        self.assertTrue(self.state.verify(valid['frame'],valid['pem'])['valid'])
        with self.assertRaises(ValueError):dna.zdns_rna_announce('example.ziokt','root:one')

    def test_evidence_survives_restart_is_owner_scoped_and_signed(self):
        doc=self.state.commit('alice','pipeline','task','worker','a'*64,{'passed':True})
        restarted=ProtocolState(self.root/'state',self.settings)
        stored=restarted.evidence('alice',doc['commitment_hash'])
        self.assertEqual(stored,doc)
        self.key.public_key().verify(bytes.fromhex(doc['witness_signature']),b'Ziokt/OpenCI/witness/v1\0'+dna.canonical(doc['witness']),ec.ECDSA(hashes.SHA256()))
        with self.assertRaises(ValueError):restarted.evidence('bob',doc['commitment_hash'])
        self.assertEqual(stored['chain_registration'],'not_registered')
        self.assertFalse(stored['worker_signature_verified'])


if __name__=='__main__':unittest.main()
