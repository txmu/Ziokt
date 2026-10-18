import hashlib
import http.client
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
import zipfile
from ziokt.static_site import cs_content,cs_resolve,cs_headers,cs_path
from ziokt.static_origin import static_server
from ziokt.gateway_store import Store
from tools.prepare_static_blog import prepare


class StaticBlogTests(unittest.TestCase):
    def test_generator_paths_modules_inline_hashes_and_missing_assets(self):
        manifest={'files':{'index.html':'a','posts/hello/index.html':'b','about.html':'c','404.html':'d'}}
        self.assertEqual(cs_resolve(manifest,'posts/hello')[0],'posts/hello/index.html')
        self.assertEqual(cs_resolve(manifest,'about')[0],'about.html')
        self.assertEqual(cs_resolve(manifest,'missing.js')[2],404)
        for path in ('../secret','%2e%2e/key','%2fadmin','a\\b'):
            with self.assertRaises(ValueError):cs_path(path)
        html=b'<script>window.blogLoaded=true;</script><script type="module" src="./app.mjs"></script>'
        shared=cs_headers('index.html',html)['Content-Security-Policy'];isolated=cs_headers('index.html',html,isolated=True)['Content-Security-Policy']
        self.assertIn("script-src 'self' 'sha256-",shared);self.assertNotIn('allow-same-origin',shared)
        self.assertIn('allow-same-origin',isolated);self.assertNotIn("'unsafe-eval'",isolated)
        self.assertIn('form-action \'none\'',isolated)

    def test_corrupt_or_missing_chunks_never_become_successful_pages(self):
        blobs={}
        def put(data):key=hashlib.sha256(data).hexdigest();blobs[key]=data;return key
        a=put(b'first');b=put(b'second');root=put(json.dumps({'size':11,'chunks':[a,b]}).encode())
        self.assertEqual(cs_content(root,blobs.get),b'firstsecond')
        blobs[b]=b'corrupt'
        with self.assertRaisesRegex(ValueError,'corrupt'):cs_content(root,blobs.get)
        del blobs[b]
        with self.assertRaises(ValueError):cs_content(root,blobs.get)

    def test_export_packages_real_assets_but_never_executes_generator_or_php(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'public';root.mkdir();(root/'index.html').write_text('<script src="app.js"></script>');(root/'app.js').write_text('document.body.dataset.real="yes"')
            output=Path(temporary)/'blog.zip';report=prepare(root,output,generator='hugo')
            self.assertFalse(report['published'])
            with zipfile.ZipFile(output) as z:self.assertEqual(z.read('app.js'),(root/'app.js').read_bytes())
            (root/'secret.php').write_text('<?php readfile("/secret");')
            with self.assertRaises(ValueError):prepare(root,output,generator='generic')

    def test_static_only_http_never_exposes_gateway_administration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);store=Store(root/'objects');page=store.put(b'<script>document.title="real";</script>')
            manifest=store.put(json.dumps({'files':{'index.html':page},'index':'index.html'}).encode());forum=root/'forum.db'
            with sqlite3.connect(forum) as db:db.execute('CREATE TABLE nns_records(domain_name TEXT,target_hash TEXT)');db.execute('INSERT INTO nns_records VALUES (?,?)',('blog',manifest))
            server=static_server({'objects':str(root/'objects'),'forum_db':str(forum)},'blog','127.0.0.1');self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
            threading.Thread(target=server.serve_forever,daemon=True).start()
            c=http.client.HTTPConnection('127.0.0.1',server.server_port);c.request('GET','/');r=c.getresponse();self.assertEqual(r.status,200);self.assertIn('allow-same-origin',r.headers['Content-Security-Policy']);r.read();c.close()
            for method,path in [('GET','/api/gateway/tools'),('POST','/api/gateway/tools/call')]:
                c=http.client.HTTPConnection('127.0.0.1',server.server_port);c.request(method,path);r=c.getresponse();self.assertIn(r.status,(404,501));r.read();c.close()


if __name__=='__main__':unittest.main()
