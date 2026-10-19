#!/usr/bin/env python3
"""Real, disposable FreshRSS/Miniflux consumers. Run on CI, not the live node."""
import base64,json,secrets,sqlite3,subprocess,sys,tempfile,threading,time
from pathlib import Path
from urllib.request import Request,urlopen
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ziokt.content_fabric import Fabric
from ziokt.content_server import server

def command(*args):
 result=subprocess.run(args,check=True,capture_output=True,text=True,timeout=180)
 return result.stdout.strip()

def main():
 names=[];report={'schema':'ziokt.feed-clients.v1','network':'actual HTTP and independent Docker processes','clients':{}}
 with tempfile.TemporaryDirectory(prefix='ziokt-feed-clients-') as directory:
  root=Path(directory);fabric=Fabric(root/'state');fabric.create_group('author','books.open')
  fabric.post('author',['books.open'],'Ziokt feed interoperability','Original CC0 test article',message_id='<feed-ci@ziokt.test>')
  fabric.create_group('author','books.private',visibility='private');fabric.post('author',['books.private'],'Private never exported','Private never exported')
  http=server(fabric,{'port':18085,'public_read':True,'tokens':[]});thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
  base='http://127.0.0.1:18085';password=secrets.token_hex(24)
  def docker(name,image,*args):
   names.append(name);return command('docker','run','-d','--name',name,'--network','host','--memory','512m',*args,image)
  def api(path,data=None):
   request=Request('http://127.0.0.1:18086/v1/'+path,data=json.dumps(data).encode() if data is not None else None,headers={'Authorization':'Basic '+base64.b64encode(('reader:'+password).encode()).decode(),'Content-Type':'application/json'})
   with urlopen(request,timeout=20) as response:return json.load(response)
  try:
   docker('ziokt-feed-db','postgres:18-alpine','-e','POSTGRES_USER=reader','-e','POSTGRES_DB=feeds','-e','POSTGRES_PASSWORD='+password)
   for _ in range(60):
    if subprocess.run(['docker','exec','ziokt-feed-db','pg_isready','-U','reader'],capture_output=True).returncode==0:break
    time.sleep(1)
   else:raise RuntimeError('PostgreSQL readiness timeout')
   docker('ziokt-miniflux','miniflux/miniflux:2.3.3','-e','DATABASE_URL=postgres://reader:'+password+'@127.0.0.1/feeds?sslmode=disable','-e','RUN_MIGRATIONS=1','-e','CREATE_ADMIN=1','-e','ADMIN_USERNAME=reader','-e','ADMIN_PASSWORD='+password,'-e','FETCHER_ALLOW_PRIVATE_NETWORKS=1','-e','LISTEN_ADDR=127.0.0.1:18086')
   for _ in range(60):
    try:api('me');break
    except OSError:time.sleep(1)
   else:raise RuntimeError('Miniflux readiness timeout')
   formats={}
   for fmt in ('rss','atom','json'):
    feed=api('feeds',{'feed_url':base+'/feeds/netnews.'+fmt})
    entries=api('feeds/'+str(feed['feed_id'])+'/entries')['entries']
    assert any(item['title']=='Ziokt feed interoperability' for item in entries),(fmt,'missing public article')
    assert all('Private never exported' not in json.dumps(item) for item in entries)
    formats[fmt]={'public_article_received':True,'private_article_absent':True,'entries':len(entries)}
   report['clients']['miniflux']={'version':'2.3.3','formats':formats}
   docker('ziokt-freshrss','freshrss/freshrss:1.30.2')
   def cli(*args):return command('docker','exec','--user','www-data','--workdir','/var/www/FreshRSS','ziokt-freshrss',*args)
   # Exact host override is CI-only; do not disable SSRF protection generally.
   config="<?php return ['internal_host_allowlist'=>['127.0.0.1:18085']];"
   command('docker','exec','ziokt-freshrss','php','-r',"file_put_contents('/var/www/FreshRSS/data/config.custom.php',"+json.dumps(config)+");")
   cli('php','cli/do-install.php','--default-user','reader','--db-type','sqlite','--base-url','http://127.0.0.1')
   cli('php','cli/create-user.php','--user','reader','--password',password,'--no-default-feeds')
   formats={}
   for fmt in ('rss','atom','json'):
    opml='<opml version="2.0"><head><title>CI</title></head><body><outline text="'+fmt+'" type="rss" xmlUrl="'+base+'/feeds/netnews.'+fmt+'"/></body></opml>'
    path=root/(fmt+'.opml');path.write_text(opml);command('docker','cp',str(path),'ziokt-freshrss:/tmp/'+path.name)
    cli('php','cli/import-for-user.php','--user','reader','--filename','/tmp/'+path.name)
   cli('php','cli/actualize-user.php','--user','reader')
   cli('php','cli/export-sqlite-for-user.php','--user','reader','--filename','/tmp/feed-evidence.sqlite')
   command('docker','cp','ziokt-freshrss:/tmp/feed-evidence.sqlite',str(root/'entries.sqlite'))
   with sqlite3.connect(root/'entries.sqlite') as db:
    tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    feed_table=next((t for t in tables if 'feed' in t),'feed')
    entry_table=next((t for t in tables if 'entry' in t),'entry')
    rows=db.execute(f'SELECT f.url,e.title FROM {feed_table} f LEFT JOIN {entry_table} e ON e.id_feed=f.id').fetchall()
    for fmt in ('rss','atom','json'):
     titles=[title for url,title in rows if url==base+'/feeds/netnews.'+fmt]
     assert 'Ziokt feed interoperability' in titles,(fmt,'FreshRSS did not store public article')
     assert 'Private never exported' not in titles
     formats[fmt]={'public_article_received':True,'private_article_absent':True,'entries':len(titles)}
   report['clients']['freshrss']={'version':'1.30.2','formats':formats}
   Path('feed-client-results.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
  finally:
   for name in reversed(names):subprocess.run(['docker','rm','-f',name],capture_output=True,timeout=30)
   http.shutdown();http.server_close();thread.join();fabric.close()

if __name__=='__main__':main()
