"""Real HTTP signup plus native naming admission and ownership rejection."""
import hashlib,json,os,pathlib,sqlite3,subprocess,sys,tempfile,threading,time,unittest
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec
from ziokt.content_fabric import Fabric
from ziokt.content_server import server
from ziokt.protocol import encoded
from ziokt.public_accounts import Accounts
from ziokt.public_transactions import signing_bytes,transaction_bytes,validate

class PublicAccountTests(unittest.TestCase):
    def test_real_signup_login_restart_scopes_and_private_owner_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            fabric=Fabric(pathlib.Path(directory)/'content');self.addCleanup(fabric.close)
            http=server(fabric,{'port':0,'tokens':[],'public_read':True});self.addCleanup(http.server_close);self.addCleanup(http.shutdown)
            threading.Thread(target=http.serve_forever,daemon=True).start();base='http://127.0.0.1:'+str(http.server_address[1])
            def call(path,body,token=None):
                headers={'Content-Type':'application/json'}
                if token:headers['Authorization']='Bearer '+token
                with urlopen(Request(base+path,data=encoded(body),headers=headers),timeout=10) as r:return json.load(r)
            credentials={'username':'alice','password':'correct-private-password'}
            alice=call('/api/accounts/register',credentials);bob=call('/api/accounts/register',{'username':'bob','password':'different-private-password'})
            self.assertNotIn('content:admin',alice['scopes']);self.assertNotIn('content:replicate',alice['scopes'])
            with self.assertRaises(HTTPError):call('/api/accounts/register',credentials)
            with self.assertRaises(HTTPError):call('/api/accounts/login',dict(credentials,password='wrong-private-password'))
            login=call('/api/accounts/login',credentials);self.assertEqual(login['account'],'user_alice')
            self.assertEqual(Accounts(fabric.root).principal('Bearer '+login['token'])['account'],'user_alice')
            body={'operation':'library.collection.manage','arguments':{'id':'secret','action':'create','revision':0,'name':'Private collection'}}
            result=call('/api',body,alice['token'])
            mine=call('/api',{'operation':'library.collection.list','arguments':{'limit':10,'offset':0}},alice['token'])
            other=call('/api',{'operation':'library.collection.list','arguments':{'limit':10,'offset':0}},bob['token'])
            self.assertTrue(mine['items']);self.assertFalse(other['items'])
            with self.assertRaises(HTTPError):call('/api',{'operation':'content.maintenance','arguments':{}},alice['token'])

# The sibling repository supplies its actual native schema and cryptographic fixture.
CORE=pathlib.Path(__file__).resolve().parents[2]/'Corium'
if CORE.is_dir():
    sys.path.insert(0,str(CORE))
    from test_core import Fixture
    class PublicNamingTests(Fixture):
        def signed(self,key,kind,data,network='default'):
            pem=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode().rstrip('\n')
            tx={'type':kind,'data':data,'timestamp':int(time.time()),'public_key':pem,'signature':''}
            tx['signature']=key.sign(transaction_bytes(network,tx),ec.ECDSA(hashes.SHA256())).hex()
            return {'schema':'ziokt.public-transaction.v1','network':network,'transaction':tx,'authorization':key.sign(signing_bytes(network,tx),ec.ECDSA(hashes.SHA256())).hex()}
        def admit(self,value,ok=True):
            command=pathlib.Path(__file__).resolve().parents[1]/'gateway/native.sh'
            result=subprocess.run([str(command),str(CORE/'corix_v108.sh'),str(self.root),'default','public-transaction',encoded(value).decode()],env=dict(self.env,PYTHONPATH=str(command.parent.parent)),capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode==0,ok,result.stdout+result.stderr)
            return json.loads(result.stdout) if ok else None
        def test_zero_balance_new_identity_registers_and_cannot_overwrite_other_owner(self):
            owner=ec.generate_private_key(ec.SECP256K1());intruder=ec.generate_private_key(ec.SECP256K1())
            data={'domain_name':'public-alice','target_hash':'a'*64,'proof_of_genesis_contribution':{'burned_amount':0},'proof_of_contribution':{'burned_amount':0}}
            request=self.signed(owner,'nns_register',data);receipt=self.admit(request)
            self.assertEqual(self.admit(request)['transaction'],receipt['transaction'])
            self.run_core('blockchain_mine_block')
            expected=hashlib.sha256(request['transaction']['public_key'].encode()).hexdigest()
            with sqlite3.connect(self.forum) as db:self.assertEqual(db.execute("SELECT owner_id FROM nns_records WHERE domain_name='public-alice'").fetchone()[0],expected)
            self.admit(self.signed(intruder,'nns_update',{'records':[{'domain_name':'public-alice','target_hash':'b'*64}]}),False)
            self.admit(self.signed(intruder,'nns_register',data),False)
            with sqlite3.connect(self.chain) as db:self.assertEqual(db.execute('SELECT count(*) FROM transactions').fetchone()[0],1)
            request['network']='another-chain'
            with self.assertRaises(ValueError):validate(request,'default')
