"""Real TLS discovery honors public certificate pins and bundle boundaries."""
import importlib.util,tempfile,unittest,ssl,socket,threading,datetime
from pathlib import Path
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec
spec=importlib.util.spec_from_file_location('join_mainnet',Path(__file__).resolve().parents[1]/'tools/join_mainnet.py');join=importlib.util.module_from_spec(spec);spec.loader.exec_module(join)
class EntryTests(unittest.TestCase):
 def certificate(self,root,name):
  key=ec.generate_private_key(ec.SECP256R1());subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,name)])
  now=datetime.datetime.now(datetime.timezone.utc);cert=x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1)).not_valid_after(now+datetime.timedelta(hours=1)).sign(key,hashes.SHA256())
  pem=root/(name+'.crt');pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM));private=root/(name+'.key');private.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));return pem,private
 def test_real_tls_pin_selection_and_wrong_certificate_rejection(self):
  with tempfile.TemporaryDirectory()as temporary:
   root=Path(temporary);cert,key=self.certificate(root,'server');wrong,_=self.certificate(root,'foreign');ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.load_cert_chain(cert,key)
   with socket.socket()as listener:
    listener.bind(('127.0.0.1',0));listener.listen();port=listener.getsockname()[1]
    def server():
     for _ in range(2):
      with listener.accept()[0]as raw:
       try:
        with ctx.wrap_socket(raw,server_side=True):pass
       except ssl.SSLError:pass
    worker=threading.Thread(target=server,daemon=True);worker.start()
    item={'http_port_offset':2,'seeds':[{'host':'127.0.0.1','port':port-2,'identity':'a'*64,'certificate':cert.name}]}
    selected=join.reachable_seeds(item,root,'primary',2,'trial');self.assertEqual(selected[0]['port'],port-2)
    item['seeds'][0]['certificate']=wrong.name
    with self.assertRaisesRegex(ValueError,'no TLS-pinned'):join.reachable_seeds(item,root,'primary',2,'trial')
    worker.join(5);self.assertFalse(worker.is_alive())
 def test_certificate_path_cannot_escape_bundle(self):
  for name in ['../private.key','/etc/passwd']:
   with self.subTest(name=name),self.assertRaisesRegex(ValueError,'relative seed'):
    join.reachable_seeds({'seeds':[{'certificate':name}]},Path('/tmp'),'primary',2,'trial')
