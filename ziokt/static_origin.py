"""Dedicated static-only origin backed by the original NNS and verified DHT.

No administration routes, signing material, generators or server-side plugins.
The read-only worker listens on loopback behind the operator's TLS proxy.
"""
from contextlib import closing
import argparse
import http.server
import json
import re
import sqlite3
from urllib.parse import urlsplit
from .gateway import Server
from .gateway_store import Store,digest_ok
from .static_site import cs_content,cs_resolve,cs_headers
from .protocol import secure_read


def static_server(config,domain,hostname,*,port=0):
    if not re.fullmatch('[a-z0-9][a-z0-9.-]{0,127}',domain) or not re.fullmatch('[a-z0-9][a-z0-9.-]{0,252}',hostname):raise ValueError('fixed NNS domain and static hostname required')
    if type(port) is not int or not 0<=port<=65535:raise ValueError('bounded static port required')
    store=Store(config['objects'],config.get('dht_db'),peers=config.get('peers',()))
    from pathlib import Path
    forum=Path(config['forum_db']).absolute().as_uri()+'?mode=ro'
    class Handler(http.server.BaseHTTPRequestHandler):
        def setup(self):super().setup();self.connection.settimeout(10)
        def log_message(self,*_):pass
        def do_GET(self):self.serve(False)
        def do_HEAD(self):self.serve(True)
        def serve(self,head):
            # Forwarded host names never choose another site's identity/root.
            host=self.headers.get('Host','').split(':',1)[0]
            if host!=hostname:return self.send_error(421,'Wrong static origin')
            try:
                with closing(sqlite3.connect(forum,uri=True,timeout=3)) as db:
                    row=db.execute('SELECT target_hash FROM nns_records WHERE domain_name=?',(domain,)).fetchone()
                if not row or not digest_ok(row[0]):raise FileNotFoundError('NNS record unavailable')
                manifest=json.loads(cs_content(row[0],store.get))
                path,digest,status=cs_resolve(manifest,urlsplit(self.path).path)
                content=cs_content(digest,store.get)
                headers=cs_headers(path,content,isolated=True,wasm=manifest.get('static_wasm') is True)
                self.send_response(status)
                for key,value in headers.items():self.send_header(key,value)
                self.send_header('Content-Length',str(len(content)));self.end_headers()
                if not head:self.wfile.write(content)
            except FileNotFoundError:self.send_error(404,'Static site or file unavailable')
            except (ValueError,TypeError,KeyError,UnicodeError,sqlite3.Error,OSError):self.send_error(502,'Static integrity or availability failure')
    return Server(('127.0.0.1',port),Handler)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--gateway-config',required=True);parser.add_argument('--domain',required=True);parser.add_argument('--hostname',required=True);parser.add_argument('--port',type=int,default=8187);args=parser.parse_args()
    config=json.loads(secure_read(args.gateway_config))
    server=static_server(config,args.domain,args.hostname,port=args.port)
    try:server.serve_forever()
    finally:server.server_close()


if __name__=='__main__':main()
