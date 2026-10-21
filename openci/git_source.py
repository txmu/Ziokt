"""Owner-approved native Git snapshots; repository code is never run on Controller."""
from contextlib import closing
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import tempfile
import time
from ziokt.protocol import secure_read,strict_json
from .state import Error,identifier,encoded

COMMIT=re.compile(r'[0-9a-f]{40}(?:[0-9a-f]{24})?\Z')
MAX_SOURCE=64*1024*1024


def settings(controller,project):
    identifier(project)
    document=strict_json(secure_read(controller.config,65536),65536)
    value=document.get('git_projects',{}).get(project)
    if not isinstance(value,dict) or not {'repository','ref','template','webhook_key'}<=set(value) or set(value)-{'repository','ref','template','webhook_key','interval_seconds'}:raise Error('GIT_NOT_CONFIGURED','Owner-approved Git source required',409)
    path=Path(value['repository'])
    if not path.is_absolute() or not path.is_dir() or path.is_symlink():raise Error('GIT_REPOSITORY','Approved local mirror is unavailable',503)
    if not isinstance(value['ref'],str) or not re.fullmatch(r'refs/heads/[A-Za-z0-9_./-]{1,200}',value['ref']):raise Error('GIT_REF','Explicit branch ref required')
    return value


def command(repository,*args):
    return ['git','--no-replace-objects','-c','core.hooksPath=/dev/null','-c','core.fsmonitor=false','-c','core.attributesFile=/dev/null','-c','protocol.ext.allow=never','-C',str(repository),*args]


def environment():
    # Do not inherit alternate object databases, config injection, SSH commands or credentials.
    return {'PATH':os.defpath,'HOME':'/nonexistent','LANG':'C','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null','GIT_TERMINAL_PROMPT':'0'}


def resolve(repository,revision):
    try:result=subprocess.run(command(repository,'rev-parse','--verify',revision+'^{commit}'),env=environment(),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=10,check=False)
    except (OSError,subprocess.TimeoutExpired):raise Error('GIT_UNAVAILABLE','Native Git or approved mirror is unavailable',503) from None
    commit=result.stdout.decode('ascii',errors='replace').strip()
    if result.returncode or not COMMIT.fullmatch(commit):raise Error('GIT_COMMIT_UNAVAILABLE','Commit is absent from the approved local mirror; synchronize it before retry',409)
    return commit


def snapshot(repository,commit,destination):
    process=subprocess.Popen(command(repository,'archive','--format=tar',commit),env=environment(),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    count=0;deadline=time.monotonic()+30;digest=hashlib.sha256()
    try:
        with selectors.DefaultSelector() as selector,open(destination,'xb') as output:
            selector.register(process.stdout,selectors.EVENT_READ)
            while True:
                if time.monotonic()>deadline:raise Error('GIT_TIMEOUT','Git snapshot deadline exceeded',503)
                if not selector.select(min(1,max(0,deadline-time.monotonic()))):continue
                data=os.read(process.stdout.fileno(),65536)
                if not data:break
                count+=len(data)
                if count>MAX_SOURCE:raise Error('GIT_SOURCE_LIMIT','Source snapshot exceeds 64 MiB',413)
                output.write(data);digest.update(data)
            if process.wait(timeout=5)!=0:raise Error('GIT_ARCHIVE','Native Git failed to produce snapshot',409)
            output.flush();os.fsync(output.fileno())
        # Validate the exact archive using the same confined extractor as Workers.
        # Submodule links do not contain source bytes: reject instead of silently omitting them.
        tree=subprocess.Popen(command(repository,'ls-tree','-r','--format=%(objectmode)',commit),env=environment(),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        try:
            listing=bytearray();tree_deadline=time.monotonic()+10
            with selectors.DefaultSelector() as selector:
                selector.register(tree.stdout,selectors.EVENT_READ)
                while True:
                    if time.monotonic()>tree_deadline:raise Error('GIT_TIMEOUT','Native Git tree deadline exceeded',503)
                    if not selector.select(.5):continue
                    data=os.read(tree.stdout.fileno(),65536)
                    if not data:break
                    listing.extend(data)
                    if len(listing)>4096*7:raise Error('GIT_SOURCE_LIMIT','Source tree exceeds 4096 entries',413)
            if tree.wait(timeout=2)!=0:raise Error('GIT_TREE','Native Git tree unavailable',409)
            if b'160000' in listing.splitlines():raise Error('GIT_SUBMODULE_UNPINNED','Submodule snapshots require a separate pinned source dependency',409)
        finally:
            if tree.poll() is None:tree.kill()
            tree.wait();tree.stdout.close()
        from .runner import unpack_source
        with tempfile.TemporaryDirectory(prefix='openci-source-check-') as area:unpack_source(destination,Path(area)/'source')
        return count,'sha256:'+digest.hexdigest()
    finally:
        if process.poll() is None:process.kill()
        process.wait();process.stdout.close()


def _trigger(controller,actor,project,commit,delivery):
    config=settings(controller,project)
    if not isinstance(commit,str) or not COMMIT.fullmatch(commit):raise Error('GIT_COMMIT','Full lowercase commit ID required')
    if not isinstance(delivery,str) or not 1<=len(delivery)<=128 or any(ord(c)<33 or ord(c)>126 for c in delivery):raise Error('GIT_DELIVERY','Bounded delivery identity required')
    with controller.state.transaction() as db:
        prior=db.execute('SELECT * FROM git_deliveries WHERE project=? AND delivery=?',(project,delivery)).fetchone()
        if prior:
            if prior['commit_id']!=commit:raise Error('GIT_DELIVERY_CONFLICT','Delivery identity already belongs to another commit',409)
            if prior['state']=='submitted':return {'pipeline':prior['pipeline'],'duplicate':True,'git_commit':commit,'git_ref':config['ref'],'source_snapshot_verified':True,'build_completed':False}
        else:
            if db.execute('SELECT count(*) FROM git_deliveries').fetchone()[0]>=10000:raise Error('GIT_DELIVERY_QUOTA','Archive old Git delivery records before accepting more',429)
            db.execute("INSERT INTO git_deliveries VALUES(?,?,?,'preparing',NULL,NULL,?)",(project,delivery,commit,int(time.time())))
    actual=resolve(config['repository'],commit)
    head=resolve(config['repository'],config['ref'])
    # This initial policy builds only the current approved branch head.
    if actual!=commit or head!=commit:raise Error('GIT_REF_MISMATCH','Commit is not current approved branch head',409)
    with tempfile.TemporaryDirectory(prefix='openci-git-') as area:
        path=Path(area)/'source.tar';size,digest=snapshot(config['repository'],commit,path)
        owner='openci-'+project;upload='git-'+os.urandom(16).hex();controller.fabric.begin(owner,upload,size,digest,'application/x-tar')
        with path.open('rb') as source:
            position=0
            while data:=source.read(16384):controller.fabric.put(owner,upload,position,data);position+=1
        obj=controller.fabric.finish(owner,upload)
    template=json.loads(encoded(config['template']))
    template.update(schema='openci.pipeline.v1',project=project,source={'object':obj['id'],'digest':digest},nonce='git-'+hashlib.sha256((project+'\0'+delivery).encode()).hexdigest()[:56])
    result=controller.state.submit(actor,template)
    with controller.state.transaction() as db:
        db.execute("UPDATE git_deliveries SET state='submitted',pipeline=?,error=NULL,updated=? WHERE project=? AND delivery=?",(result['pipeline'],int(time.time()),project,delivery))
        controller.state.event(db,actor,'git.submitted',result['pipeline'],detail={'commit':commit,'ref':config['ref'],'delivery':delivery})
    return {**result,'git_commit':commit,'git_ref':config['ref'],'source_snapshot_verified':True,'build_completed':False}


def webhook(controller,project,raw,headers):
    config=settings(controller,project)
    key=secure_read(config['webhook_key'],4096)
    if not 32<=len(key)<=4096:raise Error('WEBHOOK_CONFIG','Owner webhook key must contain at least 32 bytes',503)
    signature=headers.get('X-Hub-Signature-256','')
    expected='sha256='+hmac.new(key,raw,hashlib.sha256).hexdigest()
    if not isinstance(signature,str) or not hmac.compare_digest(signature,expected):raise Error('WEBHOOK_AUTH','Webhook signature rejected',401)
    if headers.get('X-GitHub-Event')!='push':raise Error('WEBHOOK_EVENT','Only branch push events are enabled',400)
    value=strict_json(raw,1024*1024)
    if value.get('ref')!=config['ref'] or value.get('deleted') is True:raise Error('WEBHOOK_REF','Webhook does not target the approved live branch',409)
    return trigger(controller,'git-webhook:'+project,project,value.get('after'),headers.get('X-GitHub-Delivery'))


def trigger(controller,actor,project,commit,delivery):
    if not controller.git_slot.acquire(blocking=False):raise Error('GIT_BUSY','Another snapshot is in progress; retry this delivery',503)
    try:
        return _trigger(controller,actor,project,commit,delivery)
    except Error as error:
        if isinstance(project,str) and isinstance(delivery,str):
            with controller.state.transaction() as db:
                db.execute("UPDATE git_deliveries SET state='failed',error=?,updated=? WHERE project=? AND delivery=? AND commit_id=? AND state!='submitted'",(error.code,int(time.time()),project,delivery,commit))
        raise
    finally:controller.git_slot.release()


def tick(controller):
    """Persist schedule slots before execution; recover interrupted submission slots."""
    results=[]
    with closing(controller.state.connect()) as db:
        pending=[dict(row) for row in db.execute("SELECT * FROM git_deliveries WHERE state='preparing' ORDER BY updated LIMIT 16")]
    for entry in pending:
        try:results.append(trigger(controller,'git-recovery',entry['project'],entry['commit_id'],entry['delivery']))
        except Error as error:results.append({'state':'failed','project':entry['project'],'error':error.code})
    document=strict_json(secure_read(controller.config,65536),65536)
    for project,config in document.get('git_projects',{}).items():
        interval=config.get('interval_seconds')
        if interval is None:continue
        if type(interval) is not int or not 60<=interval<=2592000:
            results.append({'state':'failed','project':project,'error':'GIT_SCHEDULE_INTERVAL'});continue
        now=int(time.time())
        with closing(controller.state.connect()) as db:
            row=db.execute('SELECT next_due FROM git_schedules WHERE project=?',(project,)).fetchone()
            due=row['next_due'] if row else now
        if due>now:continue
        try:commit=resolve(config['repository'],config['ref'])
        except Error as error:
            with controller.state.transaction() as db:
                db.execute('INSERT INTO git_schedules VALUES(?,?) ON CONFLICT(project) DO UPDATE SET next_due=excluded.next_due',(project,now+60))
                controller.state.event(db,'git-schedule','git.schedule_failed',detail={'project':project,'error':error.code,'due':due})
            results.append({'state':'failed','project':project,'error':error.code});continue
        delivery='schedule-'+str(due)
        with controller.state.transaction() as db:
            current=db.execute('SELECT next_due FROM git_schedules WHERE project=?',(project,)).fetchone()
            if current and current['next_due']>now:continue
            if db.execute('SELECT count(*) FROM git_deliveries').fetchone()[0]>=10000:
                results.append({'state':'failed','project':project,'error':'GIT_DELIVERY_QUOTA'});continue
            # Persist both the due slot and its recoverable intent atomically.
            db.execute("INSERT OR IGNORE INTO git_deliveries VALUES(?,?,?,'preparing',NULL,NULL,?)",(project,delivery,commit,now))
            db.execute('INSERT INTO git_schedules VALUES(?,?) ON CONFLICT(project) DO UPDATE SET next_due=excluded.next_due',(project,now+interval))
        try:results.append(trigger(controller,'git-schedule',project,commit,delivery))
        except Error as error:results.append({'state':'failed','project':project,'error':error.code})
    return {'schedule_results':results}
