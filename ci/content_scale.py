#!/usr/bin/env python3
"""Opt-in real SQLite/filesystem workload. Never runs in ordinary CI jobs."""
import argparse,hashlib,json,resource,sys,tempfile,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ziokt.content_fabric import Fabric

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--articles',type=int,default=100000);parser.add_argument('--books',type=int,default=10000);parser.add_argument('--queries',type=int,default=100)
 args=parser.parse_args()
 if not 1<=args.articles<=100000 or not 1<=args.books<=100000 or not 1<=args.queries<=1000:parser.error('workload bounds')
 report={'schema':'ziokt.content-scale.v1','articles':args.articles,'books':args.books,'storage':'real SQLite WAL and encrypted filesystem','mock_network':False,'network_exercised':False}
 with tempfile.TemporaryDirectory(prefix='ziokt-scale-') as directory:
  root=Path(directory);fabric=Fabric(root);fabric.create_group('operator','bench.original');start=time.monotonic()
  try:
   # Distinct authenticated test publishers preserve production per-account rate limits.
   for index in range(args.articles):fabric.post('writer'+str(index//50),['bench.original'],'Original benchmark article '+str(index),'Original CC0 synthetic text token'+str(index%100),message_id='<bench'+str(index)+'@scale.invalid>')
   report['article_write_seconds']=time.monotonic()-start;start=time.monotonic();obj=None
   for index in range(args.books):
    owner='author'+str(index//100)
    if index%100==0:
     data=('Original CC0 synthetic book '+owner).encode();upload='source'+str(index//100);fabric.begin(owner,upload,len(data),'sha256:'+hashlib.sha256(data).hexdigest(),'text/plain');fabric.put(owner,upload,0,data);obj=fabric.finish(owner,upload)
    fabric.create_book(owner,{'id':'book'+str(index),'work_id':'work'+str(index//2),'edition_id':'edition'+str(index),'file_id':obj['id'],'title':'Synthetic catalogue '+str(index),'authors':[owner],'license':'CC0-1.0','visibility':'public','text':'Original benchmark catalogue token'+str(index%100)})
   report['book_write_seconds']=time.monotonic()-start
   samples=[]
   for index in range(args.queries):
    start=time.monotonic();result=fabric.search('reader','token'+str(index%100),kind='article',limit=30);samples.append(time.monotonic()-start)
    if not result['items']:raise AssertionError('article FTS query empty')
   report['query_p50_seconds']=sorted(samples)[len(samples)//2];report['query_p95_seconds']=sorted(samples)[min(len(samples)-1,int(len(samples)*.95))]
   if not fabric.search('reader','Synthetic',kind='book')['items']:raise AssertionError('book FTS query empty')
   counts={row[0]:row[1] for row in fabric.db.execute('SELECT kind,count(*) FROM records GROUP BY kind')}
   if counts!={'article':args.articles,'book':args.books}:raise AssertionError('record count mismatch')
   if fabric.db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise AssertionError('SQLite integrity')
  finally:fabric.close()
  # Reopen from disk rather than reuse the previous connection.
  fabric=Fabric(root)
  try:
   if not fabric.search('reader','token0',kind='article')['items']:raise AssertionError('restart index recovery')
   report['restart_recovery']=True
  finally:fabric.close()
  report['disk_bytes']=sum(path.stat().st_size for path in root.rglob('*') if path.is_file());report['peak_rss_kib']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss;report['status']='passed'
 print(json.dumps(report,sort_keys=True))

if __name__=='__main__':main()
