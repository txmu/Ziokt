"""Real verified NNS/DHT static worker for browser CSP/module/storage acceptance."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ziokt.gateway_store import Store
from ziokt.static_origin import static_server

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory);store=Store(root/'objects')
    html=b'''<!doctype html><meta name="viewport" content="width=device-width"><title>Loading</title><button id="search">Search</button><output id="result"></output><script type="module" src="/app.mjs"></script>'''
    assets={'index.html':html,'app.mjs':b'''import {search} from './helper.mjs'; const count=Number(localStorage.getItem('count')||0)+1;localStorage.setItem('count',String(count));document.body.dataset.count=String(count);document.title='Real blog ready';document.querySelector('#search').onclick=async()=>{document.querySelector('#result').textContent=await search();};''',
            'helper.mjs':b'''export async function search(){return (await(await fetch('./search.json')).json()).posts[0].title;}''','search.json':b'{"posts":[{"title":"Actual search result"}]}'}
    manifest=store.put(json.dumps({'files':{key:store.put(value) for key,value in assets.items()},'index':'index.html'}).encode())
    forum=root/'forum.db'
    with sqlite3.connect(forum) as db:db.execute('CREATE TABLE nns_records(domain_name TEXT,target_hash TEXT)');db.execute('INSERT INTO nns_records VALUES (?,?)',('blog',manifest))
    server=static_server({'objects':str(root/'objects'),'forum_db':str(forum)},'blog','127.0.0.1')
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    print(json.dumps({'port':server.server_port}),flush=True)
    try:sys.stdin.read()
    finally:server.shutdown();server.server_close();thread.join(3)
