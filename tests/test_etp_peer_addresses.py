import json,socket,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tools.refresh_etp_peers import refresh

class PeerAddressTests(unittest.TestCase):
    def test_dns_change_keeps_keys_storage_and_unmanaged_peers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);node=root/'node.json';node.write_text(json.dumps({'private_key':'secret','peers':{'192.0.2.1:9280':'a'*64,'127.0.0.1:9281':'b'*64},'mailbox':{'database':str(root/'mail'),'replication':{'copies':3,'signing_key':'secret-signing','peers':{'192.0.2.1:9280':'c'*64}}}}));node.chmod(0o600)
            config=root/'peers.json';config.write_text(json.dumps({'schema':'ziokt.etp-peer-addresses.v1','service':'ziokt-mcp','nodes':[{'config':str(node),'peers':[{'host':'peer.example','port':9280,'transport_key':'a'*64,'mailbox_key':'c'*64}]}]}));config.chmod(0o600)
            with patch('socket.getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('192.0.2.2',9280))]):
                self.assertEqual(refresh(config)['changed'],1);self.assertEqual(refresh(config)['changed'],0)
            value=json.loads(node.read_bytes());self.assertEqual(value['private_key'],'secret');self.assertEqual(value['mailbox']['replication']['signing_key'],'secret-signing');self.assertNotIn('192.0.2.1:9280',value['peers']);self.assertEqual(value['peers']['127.0.0.1:9281'],'b'*64);self.assertEqual(value['mailbox']['replication']['peers']['192.0.2.2:9280'],'c'*64)
            before=node.read_bytes()
            with patch('socket.getaddrinfo',side_effect=socket.gaierror('temporary DNS failure')):
                with self.assertRaises(socket.gaierror):refresh(config)
            self.assertEqual(before,node.read_bytes())
