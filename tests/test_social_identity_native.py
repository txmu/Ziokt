"""Native curve proofs stay native; wrong curves and altered payloads fail."""
import secrets,tempfile,time,unittest
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization,hashes
from ziokt.protocol import encoded
from ziokt.social_identity import IdentityLinks,DOMAIN,verify_proof

class NativeCurveProofTests(unittest.TestCase):
 def test_secp256k1_and_p256_bilateral_proofs(self):
  keys=[ec.generate_private_key(ec.SECP256K1()),ec.generate_private_key(ec.SECP256R1())]
  identities=[{'app':app,'network':'test','algorithm':algorithm,'public_key':key.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.CompressedPoint).hex()} for key,app,algorithm in zip(keys,['corium','watchat'],['secp256k1','p256'])]
  statement={'schema':'ziokt.social-link.v1','network':'test','id':secrets.token_hex(32),'revision':1,'previous':'','action':'bind','left':identities[0],'right':identities[1],'recovery':{s:{'threshold':0,'keys':[]} for s in ['left','right']},'issued':int(time.time()),'expires':int(time.time())+1000}
  proofs=[{'identity':identity,'signature':key.sign((DOMAIN+'\n').encode()+encoded(statement),ec.ECDSA(hashes.SHA256())).hex()} for key,identity in zip(keys,identities)]
  with tempfile.TemporaryDirectory() as tmp:
   links=IdentityLinks(Path(tmp)/'state.sqlite','test')
   try:self.assertEqual(links.apply('owner',{'statement':statement,'proofs':proofs})['state'],'linked')
   finally:links.close()
  with self.assertRaises(Exception):verify_proof(dict(statement,expires=statement['expires']+1),proofs[0])
  with self.assertRaises(ValueError):verify_proof(statement,{'identity':dict(identities[0],algorithm='p256'),'signature':proofs[0]['signature']})
