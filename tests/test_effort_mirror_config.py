"""Actual HTTP configuration endpoint; never manufactures installer files."""
import http.client
import json
import threading
import unittest
from ziokt.effort_web import effort_server
from ziokt.protocol import ProtocolError

class DownloadMirrorsTests(unittest.TestCase):
    def test_two_origins_and_checksum_are_exposed_without_starting_work(self):
        mirrors={'android':{'github':'https://github.com/example/releases/a.apk','server':'https://downloads.example/a.apk','sha256':'a'*64}}
        server=effort_server(None,'http://127.0.0.1:0',downloads=mirrors)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            conn.request('GET','/api/people/config',headers={'Host':'127.0.0.1:0'})
            response=conn.getresponse();self.assertEqual(response.status,200);self.assertEqual(json.loads(response.read())['downloads'],mirrors);conn.close()
        finally:server.shutdown();server.server_close();thread.join()
    def test_unsafe_mirror_and_missing_digest_are_rejected(self):
        for item in [{'github':'https://example/a','server':'http://example/a','sha256':'a'*64},{'github':'https://example/a','server':'https://secret@example/a','sha256':'a'*64},{'github':'https://example/a','server':'https://example/a'}]:
            with self.assertRaises(ProtocolError):effort_server(None,'http://127.0.0.1:0',downloads={'android':item})
