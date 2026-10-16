'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),crypto=require('node:crypto'),net=require('node:net');
const {spawn}=require('node:child_process');const {WebSocket}=require('ws');
const {subscription,PushDispatcher}=require('../backend/push');
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function freePort(){const server=net.createServer();await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const port=server.address().port;await new Promise(resolve=>server.close(resolve));return port}
test('push rejects SSRF and only sends generic wakeups',async()=>{
 const good={endpoint:'https://fcm.googleapis.com/fcm/send/test',keys:{p256dh:Buffer.concat([Buffer.from([4]),crypto.randomBytes(64)]).toString('base64url'),auth:crypto.randomBytes(16).toString('base64url')}};
 for(const endpoint of ['http://fcm.googleapis.com/a','https://127.0.0.1/a','https://fcm.googleapis.com.attacker.test/a','https://user@fcm.googleapis.com/a','https://fcm.googleapis.com:444/a'])assert.throws(()=>subscription({...good,endpoint}));
 const calls=[],store={},mock={setVapidDetails(){},async sendNotification(...args){calls.push(args)}};const push=new PushDispatcher({subject:'mailto:test@example.invalid',publicKey:'test',privateKey:'test'},store,()=>{},mock);
 push.register('recipient',good);push.enqueue('recipient');push.enqueue('recipient');await push.flush();push.close();assert.equal(calls.length,1);assert.deepEqual(JSON.parse(calls[0][1]),{schema:'ziokt.watchat-wakeup.v1'});
});
test('real gateway sessions, ciphertext dedup, media ACL and encrypted storage',async t=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'watchat-test-')),port=await freePort(),base=`http://127.0.0.1:${port}`;
 const child=spawn(process.execPath,[path.resolve(__dirname,'../backend/server.js')],{env:{...process.env,PORT:String(port),DATA_DIR:dir,ADMIN_PASSWORD:'test-password-very-strong',ZIOKT_STANDALONE:'1'},stdio:['ignore','pipe','pipe']});let error='';child.stderr.on('data',x=>error+=x);t.after(async()=>{child.kill();await delay(50);fs.rmSync(dir,{recursive:true,force:true})});
 let ready=false;for(let i=0;i<100;i++){try{if((await fetch(base)).ok){ready=true;break}}catch(_){}await delay(20)}assert.ok(ready,error);
 async function request(url,{cookie,data,method=data?'POST':'GET',origin=base}={}){const headers={Origin:origin};if(cookie)headers.Cookie=cookie;if(data)headers['Content-Type']='application/json';return fetch(base+url,{method,headers,body:data?JSON.stringify(data):undefined})}
 async function login(username,password){const r=await request('/api/login',{data:{username,password}});assert.equal(r.status,200);return {cookie:r.headers.get('set-cookie').split(';')[0],user:(await r.json()).user}}
 const admin=await login('admin','test-password-very-strong');assert.equal((await request('/api/me')).status,401);
 assert.equal((await request('/api/users',{cookie:admin.cookie,data:{username:'bob',name:'Bob',password:'1234'}})).status,400);
 for(const name of ['bob','carol'])assert.equal((await request('/api/users',{cookie:admin.cookie,data:{username:name,name,password:'test-password-'+name+'-strong'}})).status,201);
 const bob=await login('bob','test-password-bob-strong'),carol=await login('carol','test-password-carol-strong');
 assert.equal((await request('/api/contacts',{cookie:admin.cookie,data:{id:bob.user.id},origin:'https://attacker.invalid'})).status,403);
 assert.equal((await request('/api/contacts',{cookie:admin.cookie,data:{id:bob.user.id}})).status,200);
 const upload=await fetch(base+'/api/upload',{method:'POST',headers:{Cookie:admin.cookie,Origin:base},body:crypto.randomBytes(256)});assert.equal(upload.status,201);const media=(await upload.json()).url;
 assert.equal((await request(media,{cookie:carol.cookie})).status,404);assert.equal((await request(media,{cookie:bob.cookie})).status,404);
 const socket=new WebSocket(base.replace('http:','ws:')+'/ws',{headers:{Cookie:admin.cookie,Origin:base}});const events=[];socket.on('message',x=>events.push(JSON.parse(x)));await new Promise((resolve,reject)=>{socket.once('open',resolve);socket.once('error',reject)});t.after(()=>socket.close());
 const frame={action:'send',id:crypto.randomUUID(),to:bob.user.id,kind:'sealed',ciphertext:crypto.randomBytes(2048).toString('base64'),attachments:[media]};socket.send(JSON.stringify(frame));await delay(100);assert.equal(events.filter(x=>x.type==='ack').length,1);socket.send(JSON.stringify(frame));await delay(100);assert.equal(events.filter(x=>x.type==='ack').length,2);
 socket.send(JSON.stringify({...frame,ciphertext:crypto.randomBytes(2048).toString('base64')}));await delay(50);assert.ok(events.some(x=>x.error==='IDEMPOTENCY_CONFLICT'));
 socket.send(JSON.stringify({action:'history',peerId:bob.user.id}));await delay(50);assert.equal(events.find(x=>x.type==='history').messages.length,1);
 assert.equal((await request(media,{cookie:bob.cookie})).status,200);assert.equal((await request(media,{cookie:carol.cookie})).status,404);
 // Force a real filesystem failure after validation; retries must not acknowledge memory-only data.
 const retry={...frame,id:crypto.randomUUID(),attachments:[]},moved=dir+'.unavailable';
 fs.renameSync(dir,moved);
 try{socket.send(JSON.stringify(retry));await delay(100);assert.equal(events.filter(x=>x.type==='ack'&&x.id===retry.id).length,0)}finally{fs.renameSync(moved,dir)}
 socket.send(JSON.stringify({action:'history',peerId:bob.user.id}));await delay(50);
 assert.equal(events.filter(x=>x.type==='history').at(-1).messages.some(x=>x.id===retry.id),false);
 socket.send(JSON.stringify(retry));await delay(100);assert.equal(events.filter(x=>x.type==='ack'&&x.id===retry.id).length,1);
 const encrypted=fs.readFileSync(path.join(dir,'store.aead')),decipher=crypto.createDecipheriv('aes-256-gcm',fs.readFileSync(path.join(dir,'store.key')),encrypted.subarray(0,12));
 decipher.setAAD(Buffer.from('Ziokt/WATChat/v2/store'));decipher.setAuthTag(encrypted.subarray(-16));
 const recovered=JSON.parse(Buffer.concat([decipher.update(encrypted.subarray(12,-16)),decipher.final()]));
 assert.equal(recovered.messages.filter(x=>x.id===retry.id).length,1);
 const disk=fs.readFileSync(path.join(dir,'store.aead'));assert.ok(!disk.includes(Buffer.from(frame.ciphertext)));assert.equal(fs.statSync(path.join(dir,'store.aead')).mode&0o777,0o600);
 const manifest=await(await request('/manifest.webmanifest')).json();assert.equal(manifest.display,'standalone');for(const icon of manifest.icons)assert.equal((await request(icon.src)).status,200);
 assert.ok((await(await request('/sw.js')).text()).includes("addEventListener('push'"));socket.close();
 const bad=new WebSocket(base.replace('http:','ws:')+'/ws?token=secret',{headers:{Cookie:admin.cookie,Origin:base}});await new Promise(resolve=>{bad.once('unexpected-response',(_,r)=>{assert.equal(r.statusCode,403);r.resume();resolve()});bad.once('error',resolve)});
 // Re-open the actual encrypted database in a fresh server process.
 const exited=new Promise(resolve=>child.once('exit',resolve));child.kill();await exited;
 const restarted=spawn(process.execPath,[path.resolve(__dirname,'../backend/server.js')],{env:{...process.env,PORT:String(port),DATA_DIR:dir,ZIOKT_STANDALONE:'1'},stdio:['ignore','pipe','pipe']});restarted.stderr.resume();
 t.after(async()=>{restarted.kill();await delay(50)});
 let recoveredReady=false;for(let i=0;i<100;i++){try{if((await fetch(base)).ok){recoveredReady=true;break}}catch(_){}await delay(20)}assert.ok(recoveredReady);
 const resumed=await login('admin','test-password-very-strong');
 const resumedSocket=new WebSocket(base.replace('http:','ws:')+'/ws',{headers:{Cookie:resumed.cookie,Origin:base}});t.after(()=>resumedSocket.close());
 const history=new Promise((resolve,reject)=>{resumedSocket.on('message',raw=>{const item=JSON.parse(raw);if(item.type==='ready')resumedSocket.send(JSON.stringify({action:'history',peerId:bob.user.id}));if(item.type==='history')resolve(item.messages)});resumedSocket.once('error',reject)});
 assert.deepEqual((await history).map(x=>x.id).sort(),[frame.id,retry.id].sort());resumedSocket.close();
});
test('durable reminders retry failed delivery and reject private payload fields',async()=>{
 const {ReminderScheduler}=require('../backend/reminders'),store={},calls=[];let failing=true;
 const scheduler=new ReminderScheduler(store,()=>{},async(user,item)=>{calls.push({user,item});if(failing)throw Error('drop')});const now=100000;
 scheduler.replace('owner',[{id:'a'.repeat(64),due:now,webhook:false}],now);await scheduler.tick(now);assert.equal(store.reminders.owner['a'.repeat(64)].sent,false);failing=false;await scheduler.tick(now);await scheduler.tick(now);assert.equal(calls.length,2);assert.equal(store.reminders.owner['a'.repeat(64)].sent,true);
 assert.throws(()=>scheduler.replace('owner',[{id:'b'.repeat(64),due:now,webhook:false,phoneNumber:'secret'}],now));
 const {publicAddress}=require('../backend/webhook');for(const address of ['127.0.0.1','10.0.0.1','169.254.169.254','::1','::ffff:127.0.0.1','fc00::1','2001:db8::1'])assert.equal(publicAddress(address),false);assert.equal(publicAddress('8.8.8.8'),true);
});
test('fixed Ziokt bridge worker opens the scoped Python companion and correlates replies',async t=>{
 const {BridgeWorker}=require('../backend/bridge'),dir=fs.mkdtempSync(path.join(os.tmpdir(),'watchat-bridge-')),root=path.resolve(__dirname,'../../../..');
 const setup=`import secrets,sys\nfrom pathlib import Path\nfrom ziokt.community import create_policy,RIGHTS\nfrom ziokt.security import sign\nfrom ziokt.cli import write_exclusive,write_binary_exclusive\nr=Path(sys.argv[1]);k=secrets.token_bytes(32);p=sign({},k,'test')['public_key'];write_exclusive(r/'policy.json',create_policy(k,'bridge-test',{p:sorted(RIGHTS)}))\nfor n,v in [('signing',k),('encryption',secrets.token_bytes(32)),('application',secrets.token_bytes(32))]:write_binary_exclusive(r/(n+'.key'),v)\nwrite_exclusive(r/'bridge.json',{'schema':'ziokt.companion-bridge.v1','community_root':str(r/'community'),'policy':str(r/'policy.json'),'owner':p,'encryption_key':str(r/'encryption.key'),'signing_key':str(r/'signing.key'),'application':'watchat','application_key':str(r/'application.key')})`;
 const prepared=spawnSyncPython(setup,dir,root);assert.equal(prepared,0,'private bridge fixture creation failed');
 const worker=new BridgeWorker(path.join(dir,'bridge.json'),'python3',root);t.after(()=>{worker.close();fs.rmSync(dir,{recursive:true,force:true})});
 const result=await worker.call('ano.evaluate',{circuit:{op:'and',args:['正','正']}});
 assert.equal(result.schema,'ziokt.ano-result.v1');assert.equal(result.result,'positive');
});
function spawnSyncPython(source,directory,root){return require('node:child_process').spawnSync('python3',['-c',source,directory],{env:{PATH:process.env.PATH||'',PYTHONPATH:root,PYTHONDONTWRITEBYTECODE:'1'},stdio:'ignore'}).status}
