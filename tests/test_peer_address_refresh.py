import pathlib,tempfile,unittest
from tools.refresh_peer_addresses import refresh

class RefreshIsolationTests(unittest.TestCase):
    def test_failed_peer_process_does_not_stop_other_announcements(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);source=root/'native.sh';source.write_text('''P2P_PORT=7234
DHT_DB=owner-db
load_config(){ :; }
get_our_ip(){ printf '192.0.2.1\\n'; }
db_query_static(){ printf '%064d\\n%064d\\n' 1 2; }
_dht_send_message_direct(){ [ "$1" = "$(printf '%064d' 1)" ] && exit 9; printf 'ADDRESS_UPDATED\\n'; }
''')
            self.assertTrue(refresh(source,root,'test')['ok'])
