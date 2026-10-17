"""MCP adapters for the actual signed Corium gateway, including CBB/Phoenix."""
import hashlib,json,time,os
from pathlib import Path
from cryptography.hazmat.primitives import serialization,hashes
from cryptography.hazmat.primitives.asymmetric import ec
from .config import fingerprint
from .protocol import secure_read,ProtocolError
from ._runtime import corium_native_handler

# Directly executes the production message verifier, never a replacement protocol.
READ={'find_nodes':'FIND_NODE','ping':'PING','object_providers':'FIND_VALUE','chain_state':'GET_CHAIN_STATE','block_hash_at_height':'GET_BLOCK_HASH_AT_HEIGHT','block_header':'GET_BLOCK_HEADER','block':'GET_FULL_BLOCK','transaction':'GET_TRANSACTION','cbb_messages':'CBB_SYNC_REQUEST','notarizations':'GET_NOTARIZATIONS'}
WRITE={'block_announce':'ANNOUNCE_BLOCK','phoenix_propose':'ANNOUNCE_SSPO','phoenix_notarize':'ANNOUNCE_SNSO','cbb_relay':'CBB_POST','object_announce':'STORE'}


class CoriumProtocol:
 def __init__(self,provider):
  self.provider=provider;self.root=Path(provider['state_root']);self.network=provider['network_id'];self.source=Path(provider['root'])/'corix_v108.sh'
  if fingerprint(self.source)!=provider['entrypoint_digest']:raise ProtocolError('STALE_PROVIDER','native source changed')
  os.environ['CORIUM_ROOT']=str(self.root)
  self.handler=corium_native_handler(self.source,self.root,self.network)
  self.private=serialization.load_pem_private_key(secure_read(self.root/'etc/corix/networks'/self.network/'identity.key'),password=None)
  if not isinstance(self.private,ec.EllipticCurvePrivateKey) or not isinstance(self.private.curve,ec.SECP256K1):raise ValueError('native secp256k1 identity required')
  public=self.private.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip('\n')
  self.identity=hashlib.sha256(public.encode()).hexdigest()
 def sign(self,message):return self.private.sign(message.encode(),ec.ECDSA(hashes.SHA256())).hex()
 def call(self,kind,payload):
  result=self.handler.handle_dht_message({'type':kind,'payload':payload,'sender_id':self.identity,'signature':self.sign(kind+'|'+payload)})
  if result.get('status')!='success':raise ProtocolError('NATIVE_REJECTED',result.get('message','native protocol rejected'))
  data=result.get('data')
  if isinstance(data,str):
   try:data=json.loads(data)
   except ValueError:pass
  return {'native_verified':True,'method':kind,'data':data}
 def publish_cbb(self,message):
  ts=int(time.time());canonical=f'CORIUM-CBB-V1\n{self.network}\n{self.identity}\n{ts}\n{message}'
  payload={'author_id':self.identity,'timestamp':ts,'message':message,'signature':self.sign(canonical)}
  # Persist through the same verifier/IPC path as an authenticated P2P peer.
  result=self.call('CBB_POST',json.dumps(payload))
  return {**result,'message_hash':hashlib.sha256(canonical.encode()).hexdigest(),'author':self.identity,'expires_at':ts+86400,'consensus_confirmed':False}
