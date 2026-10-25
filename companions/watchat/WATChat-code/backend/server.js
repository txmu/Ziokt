if(['1','true','yes'].includes((process.env.ZIOKT_AIRGAP||'').toLowerCase())){console.error('AIRGAP_DENIED: WATChat network service disabled');process.exit(1)}
'use strict';
// Loopback application gateway. Browser ciphertext is never decrypted here.
const http=require('node:http'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {promisify}=require('node:util');
const {WebSocketServer,WebSocket}=require('ws');
const {spawn}=require('node:child_process');
const scrypt=promisify(crypto.scrypt),ROOT=path.resolve(__dirname,'..'),FRONTEND=path.join(ROOT,'frontend');
const DATA=path.resolve(process.env.DATA_DIR||path.join(ROOT,'data')),PORT=Number(process.env.PORT||8080),MAX_UPLOAD=12*1024*1024;
if(!Number.isInteger(PORT)||PORT<1||PORT>65535)throw Error('INVALID_PORT');
fs.mkdirSync(DATA,{recursive:true,mode:0o700});if(fs.lstatSync(DATA).isSymbolicLink())throw Error('UNSAFE_DATA');fs.chmodSync(DATA,0o700);
function privateRead(file){const fd=fs.openSync(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW);try{const st=fs.fstatSync(fd);if(!st.isFile()||(st.mode&0o077)||st.size>32*1024*1024)throw Error('UNSAFE_FILE');return fs.readFileSync(fd)}finally{fs.closeSync(fd)}}
function exclusive(file,data){const fd=fs.openSync(file,fs.constants.O_WRONLY|fs.constants.O_CREAT|fs.constants.O_EXCL|fs.constants.O_NOFOLLOW,0o600);try{fs.writeFileSync(fd,data);fs.fsyncSync(fd)}finally{fs.closeSync(fd)}}
const keyFile=path.join(DATA,'store.key');if(!fs.existsSync(keyFile))exclusive(keyFile,crypto.randomBytes(32));const key=privateRead(keyFile);if(key.length!==32)throw Error('INVALID_KEY');
function seal(data,purpose){const nonce=crypto.randomBytes(12),c=crypto.createCipheriv('aes-256-gcm',key,nonce);c.setAAD(Buffer.from('Ziokt/WATChat/v2/'+purpose));return Buffer.concat([nonce,c.update(data),c.final(),c.getAuthTag()])}
function open(data,purpose){const c=crypto.createDecipheriv('aes-256-gcm',key,data.subarray(0,12));c.setAAD(Buffer.from('Ziokt/WATChat/v2/'+purpose));c.setAuthTag(data.subarray(-16));return Buffer.concat([c.update(data.subarray(12,-16)),c.final()])}
let store;const file=path.join(DATA,'store.aead');
if(fs.existsSync(file))store=JSON.parse(open(privateRead(file),'store'));
else store={users:[],messages:[],uploads:{},pending:[]};
const publicOrigin=process.env.WATCHAT_ORIGIN;
if(publicOrigin&&new URL(publicOrigin).protocol!=='https:')throw Error('HTTPS_ORIGIN_REQUIRED');
let notifier=null;
if(process.env.WATCHAT_PUSH_CONFIG){const config=JSON.parse(privateRead(path.resolve(process.env.WATCHAT_PUSH_CONFIG)));if(!publicOrigin)throw Error('HTTPS_ORIGIN_REQUIRED');notifier=new(require('./push').PushDispatcher)(config,store,()=>save())}
let webhook=null;if(process.env.WATCHAT_WEBHOOK_CONFIG)webhook=new(require('./webhook').Webhook)(JSON.parse(privateRead(path.resolve(process.env.WATCHAT_WEBHOOK_CONFIG))));
const reminderScheduler=new(require('./reminders').ReminderScheduler)(store,()=>save(),async(user,item)=>{if(item.webhook){if(!webhook)throw Error('WEBHOOK_NOT_CONFIGURED');await webhook.send(item.id)}else{if(!notifier)throw Error('PUSH_NOT_CONFIGURED');await notifier.deliver(user)}});
let bridgeInbox=null;
if(process.env.ZIOKT_BRIDGE_CONFIG){
 const cfg=JSON.parse(privateRead(path.resolve(process.env.ZIOKT_BRIDGE_CONFIG)));
 if(cfg.inbox){bridgeInbox=path.resolve(cfg.inbox);if(bridgeInbox!==path.join(DATA,'inbox'))throw Error('BRIDGE_INBOX_SCOPE');fs.mkdirSync(bridgeInbox,{recursive:true,mode:0o700});if(fs.lstatSync(bridgeInbox).isSymbolicLink())throw Error('UNSAFE_INBOX');fs.chmodSync(bridgeInbox,0o700)}
}
store.filePending??=[];
const { TransportManager } = require('./transports/TransportManager');
const transportManager = new TransportManager({
 server: { sendFn: (recipientId, envelope) => push([recipientId], { type: 'message', message: envelope, transport: envelope.transport || 'watchat-server', hops: envelope.hops || 1, bridged: envelope.bridged }) }
});
const simBridge=process.env.SIM_BRIDGE_CONFIG?new(require('./bridge').BridgeWorker)(path.resolve(process.env.SIM_BRIDGE_CONFIG),process.env.ZIOKT_PYTHON||'python3',path.resolve(process.env.ZIOKT_PROJECT_ROOT||path.join(ROOT,'../../..'))):null;
const simFederation=simBridge?new(require('./sim_bridge').SimFederation)(simBridge,store,()=>save(),reminderScheduler):null;
const sessions=new Map(),attempts=new Map();let hashing=0;
async function passwordHash(password,salt){if(typeof password!=='string'||password.length<12||password.length>128)throw Error('PASSWORD_POLICY');if(hashing>=4)throw Error('BUSY');hashing++;try{return(await scrypt(password,salt,32)).toString('hex')}finally{hashing--}}
async function makeUser(username,name,password,admin=false){if(!/^[a-zA-Z0-9_.-]{1,32}$/.test(username)||typeof name!=='string'||!name||name.length>64)throw Error('INVALID_USER');const salt=crypto.randomBytes(16).toString('hex');return{id:crypto.randomUUID(),username,name,salt,hash:await passwordHash(password,salt),admin,contacts:[],key:null}}
function save(){
 const tmp=path.join(DATA,crypto.randomUUID()+'.tmp');
 try{
  exclusive(tmp,seal(Buffer.from(JSON.stringify(store)),'store'));
  fs.renameSync(tmp,file);
  // Windows does not support opening directory handles through this Node API.
  if(process.platform!=='win32'){const directory=fs.openSync(DATA,fs.constants.O_RDONLY);try{fs.fsyncSync(directory)}finally{fs.closeSync(directory)}}
 }finally{fs.rmSync(tmp,{force:true})}
}
function pub(u){return{id:u.id,username:u.username,name:u.name,admin:u.admin,contacts:u.contacts,key:u.key}}
function byId(id){return store.users.find(u=>u.id===id)}
function auth(req){const bearer=req.headers.authorization?.match(/^Bearer ([a-f0-9]{64})$/)?.[1],cookie=req.headers.cookie?.match(/(?:^|;\s*)ziokt_session=([a-f0-9]{64})(?:;|$)/)?.[1];const s=sessions.get(bearer||cookie);return s&&s.expires>Date.now()?byId(s.id):null}
function originOK(req){
 const orig=req.headers.origin;
 if(!orig){
  const ref=req.headers.referer;
  if(ref){try{const refUrl=new URL(ref);if(refUrl.host===req.headers.host||(publicOrigin&&refUrl.origin===publicOrigin))return true}catch(_){}}
  const secFetch=req.headers['sec-fetch-site'];
  if(secFetch==='same-origin'||secFetch==='same-site'||secFetch==='none')return true;
  if(!publicOrigin)return true;
 }
 if(!orig)return true;
 if(publicOrigin&&orig===publicOrigin)return true;
 if(orig===`http://127.0.0.1:${PORT}`||orig===`http://localhost:${PORT}`)return true;
 if(req.headers.host&&(orig===`http://${req.headers.host}`||orig===`https://${req.headers.host}`))return true;
 return false;
}
function json(res,status,data,headers={}){res.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store','X-Content-Type-Options':'nosniff',...headers});res.end(JSON.stringify(data))}
let activeBodies=0;
const STORAGE_BUDGET=256*1024*1024;
function body(req,limit=65536){if(activeBodies>=8)return Promise.reject(Error('BUSY'));activeBodies++;return new Promise((resolve,reject)=>{let size=0,chunks=[];req.on('data',chunk=>{size+=chunk.length;if(size>limit){reject(Error('LIMIT'));req.destroy()}else chunks.push(chunk)});req.on('end',()=>resolve(Buffer.concat(chunks)));req.on('error',reject)}).finally(()=>activeBodies--)}
function send(ws,value){if(ws.readyState!==WebSocket.OPEN)return;if(ws.bufferedAmount>262144)return ws.close(1013);ws.send(JSON.stringify(value))}
function push(ids,value){for(const ws of wss.clients)if(ids.includes(ws.userId))send(ws,value)}
function can(me,to){return me&&to!==me.id&&me.contacts.includes(to)&&!!byId(to)}
function revoke(id){for(const [token,s]of sessions)if(s.id===id)sessions.delete(token);for(const ws of wss.clients)if(ws.userId===id)ws.close(4001)}
const staticFiles={'/':['index.html','text/html'],'/app.js':['app.js','text/javascript'],'/style.css':['style.css','text/css'],'/sw.js':['sw.js','text/javascript'],'/manifest.webmanifest':['manifest.webmanifest','application/manifest+json'],'/icon-192.png':['icon-192.png','image/png'],'/icon-512.png':['icon-512.png','image/png']};
const server=http.createServer(async(req,res)=>{try{
 const url=new URL(req.url,'http://localhost');
 if(url.pathname==='/app-config'&&req.method==='GET')return json(res,200,{title:store.settings?.title||'网页管理',mode:bridge||simBridge?'federated':'standalone'});
 if(req.method==='POST'&&!originOK(req)&&!req.headers.authorization)return json(res,403,{error:'ORIGIN_REJECTED'});
 if(url.pathname==='/api/register'&&req.method==='POST'){
  const ip=req.socket.remoteAddress,now=Date.now();let attempt=attempts.get(ip)||{n:0,until:now+60000};if(attempt.until<now)attempt={n:0,until:now+60000};attempt.n++;attempts.set(ip,attempt);if(attempt.n>12)return json(res,429,{error:'RATE_LIMIT'});
  if(store.users.length>=256)return json(res,413,{error:'LIMIT'});
  const x=JSON.parse(await body(req));
  const username=(x.username||'').trim(),name=(x.name||username).trim(),password=x.password;
  if(!username||!password)return json(res,400,{error:'INVALID_USER'});
  if(store.users.some(u=>u.username.toLowerCase()===username.toLowerCase()))return json(res,409,{error:'DUPLICATE'});
  const u=await makeUser(username,name,password,store.users.length===0);
  if(x.backup)u.backup={version:x.backup.version||2,algorithm:x.backup.algorithm||'AES-256-GCM',kdf:x.backup.kdf||'PBKDF2-SHA-256',iterations:x.backup.iterations||100000,salt:x.backup.salt,iv:x.backup.iv,ciphertext:x.backup.ciphertext,updatedAt:now};
  if(x.key)u.key={kty:'EC',crv:'P-256',x:x.key.x,y:x.key.y};
  const adminUser=store.users.find(a=>a.admin);
  if(adminUser&&adminUser.id!==u.id){if(!u.contacts.includes(adminUser.id))u.contacts.push(adminUser.id);if(!adminUser.contacts.includes(u.id))adminUser.contacts.push(u.id)}
  store.users.push(u);save();
  const token=crypto.randomBytes(32).toString('hex');sessions.set(token,{id:u.id,expires:now+3600000});
  return json(res,201,{user:{...pub(u),backup:u.backup||null}},{'Set-Cookie':`ziokt_session=${token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=3600${publicOrigin?'; Secure':''}`});
 }
 if(url.pathname==='/api/login'&&req.method==='POST'){
  const ip=req.socket.remoteAddress,now=Date.now();let attempt=attempts.get(ip)||{n:0,until:now+60000};if(attempt.until<now)attempt={n:0,until:now+60000};attempt.n++;attempts.set(ip,attempt);if(attempt.n>12)return json(res,429,{error:'RATE_LIMIT'});
  const x=JSON.parse(await body(req)),u=store.users.find(u=>u.username===x.username),salt=u?.salt||'dummy-authentication-salt';let valid=false;
  try{const hash=await passwordHash(x.password,salt);valid=!!u&&crypto.timingSafeEqual(Buffer.from(hash,'hex'),Buffer.from(u.hash,'hex'))}catch(e){if(e.message==='BUSY')return json(res,503,{error:'BUSY'})}
  if(!valid)return json(res,401,{error:'AUTH_FAILED'});if(sessions.size>=1024)return json(res,503,{error:'BUSY'});
  const token=crypto.randomBytes(32).toString('hex');sessions.set(token,{id:u.id,expires:now+3600000});return json(res,200,{user:{...pub(u),backup:u.backup||null}},{'Set-Cookie':`ziokt_session=${token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=3600${publicOrigin?'; Secure':''}`});
 }
 const me=auth(req);
 if(url.pathname.startsWith('/api/')||url.pathname.startsWith('/uploads/')){
  if(!me)return json(res,401,{error:'AUTH_REQUIRED'});
  if(req.method!=='GET'&&!originOK(req)&&!req.headers.authorization)return json(res,403,{error:'ORIGIN_REJECTED'});
  if(url.pathname==='/api/reminders'&&req.method==='POST'){const x=JSON.parse(await body(req));try{reminderScheduler.replace(me.id,x.items);if(simBridge){simFederation.queue(me.id,x.items);simFederation.flush()}return json(res,200,{accepted:x.items.length,background:!!notifier,webhook:!!webhook,federation_pending:!!simBridge})}catch(e){return json(res,400,{error:e.message})}}
  if(url.pathname==='/api/push-key'&&req.method==='GET')return json(res,200,{enabled:!!notifier,publicKey:notifier?.publicKey||null});
  if(url.pathname==='/api/push-subscription'&&req.method==='POST'){if(!notifier)return json(res,503,{error:'PUSH_NOT_CONFIGURED'});const x=JSON.parse(await body(req));try{return json(res,200,{id:notifier.register(me.id,x)})}catch(e){return json(res,400,{error:e.message})}}
  if(url.pathname==='/api/push-subscription'&&req.method==='DELETE'){notifier?.unregister(me.id);return json(res,200,{ok:true})}
  if(url.pathname==='/api/integration'&&req.method==='GET')return json(res,200,{chat_federation_configured:!!bridge,sim_federation_configured:!!simBridge,pending_messages:store.pending.length,pending_reminders:!!store.simPending?.[me.id],background_push_configured:!!notifier,webhook_configured:!!webhook,account:me.username});
   if(url.pathname==='/api/transport/modes'&&req.method==='GET')return json(res,200,{current:transportManager.getUserMode(me.id),modes:transportManager.getAllModesStatus()});
   if(url.pathname==='/api/transport/mode'&&req.method==='POST'){const x=JSON.parse(await body(req));if(!x.mode||!transportManager.setUserMode(me.id,x.mode))return json(res,400,{error:'INVALID_MODE'});return json(res,200,{ok:true,mode:x.mode})}
  if(url.pathname==='/api/settings'&&req.method==='POST'){
   if(!me.admin)return json(res,403,{error:'FORBIDDEN'});
   const x=JSON.parse(await body(req));
   if(!x||Object.keys(x).length!==1||typeof x.title!=='string'||x.title!==x.title.trim()||!x.title||[...x.title].length>80||/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/u.test(x.title))return json(res,400,{error:'INVALID_TITLE'});
   const previous=store.settings;store.settings={title:x.title.normalize('NFC')};try{save()}catch(error){store.settings=previous;throw error}return json(res,200,{title:store.settings.title});
  }
  if(url.pathname==='/api/presence'&&req.method==='GET')return json(res,200,{schema:'watchat.presence.v1',contacts:me.contacts.filter(id=>can(me,id)).map(id=>({id,online:[...wss.clients].some(ws=>ws.userId===id&&ws.readyState===WebSocket.OPEN)}))});
  if(url.pathname==='/api/me'&&req.method==='GET')return json(res,200,{user:{...pub(me),backup:me.backup||null}});
  if(url.pathname==='/api/logout'&&req.method==='POST'){revoke(me.id);return json(res,200,{ok:true},{'Set-Cookie':'ziokt_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'})}
  if(url.pathname==='/api/users'&&req.method==='GET')return json(res,200,{users:store.users.filter(u=>me.admin||me.contacts.includes(u.id)||u.id===me.id).map(pub)});
  if(url.pathname==='/api/users'&&req.method==='POST'){if(!me.admin)return json(res,403,{error:'FORBIDDEN'});if(store.users.length>=256)return json(res,413,{error:'LIMIT'});const x=JSON.parse(await body(req));if(store.users.some(u=>u.username===x.username))return json(res,409,{error:'DUPLICATE'});const u=await makeUser(x.username,x.name,x.password);store.users.push(u);save();return json(res,201,{user:pub(u)})}
  if(url.pathname==='/api/key'&&req.method==='POST'){const x=JSON.parse(await body(req));if(!x.key||Object.keys(x.key).some(k=>!['kty','crv','x','y','ext','key_ops'].includes(k))||x.key.kty!=='EC'||x.key.crv!=='P-256'||!/^[-_A-Za-z0-9]{43}$/.test(x.key.x)||!/^[-_A-Za-z0-9]{43}$/.test(x.key.y))return json(res,400,{error:'INVALID_KEY'});const value={kty:'EC',crv:'P-256',x:x.key.x,y:x.key.y};if(me.key&&JSON.stringify(me.key)!==JSON.stringify(value))return json(res,409,{error:'KEY_CHANGED'});me.key=value;save();return json(res,200,{ok:true})}
   if(url.pathname==='/api/key/backup'&&req.method==='POST'){const x=JSON.parse(await body(req));if(!x||typeof x!=='object'||!x.salt||!x.iv||!x.ciphertext||typeof x.ciphertext!=='string'||x.ciphertext.length>8192)return json(res,400,{error:'INVALID_BACKUP'});me.backup={version:x.version||2,algorithm:x.algorithm||'AES-256-GCM',kdf:x.kdf||'PBKDF2-SHA-256',iterations:x.iterations||100000,salt:x.salt,iv:x.iv,ciphertext:x.ciphertext,updatedAt:Date.now()};save();return json(res,200,{ok:true})}
   if(url.pathname==='/api/key/reset'&&req.method==='POST'){const x=JSON.parse(await body(req));me.key=null;me.backup=null;if(x.key){if(x.key.kty!=='EC'||x.key.crv!=='P-256'||!x.key.x||!x.key.y)return json(res,400,{error:'INVALID_KEY'});me.key={kty:'EC',crv:'P-256',x:x.key.x,y:x.key.y}}if(x.backup){me.backup={version:x.backup.version||2,algorithm:x.backup.algorithm||'AES-256-GCM',kdf:x.backup.kdf||'PBKDF2-SHA-256',iterations:x.backup.iterations||100000,salt:x.backup.salt,iv:x.backup.iv,ciphertext:x.backup.ciphertext,updatedAt:Date.now()}}save();push(me.contacts,{type:'key-reset',contactId:me.id});return json(res,200,{ok:true,reset:true})}
  if(url.pathname==='/api/contacts'&&req.method==='POST'){const x=JSON.parse(await body(req));const target=byId(x.id);if(!target||target.id===me.id)return json(res,400,{error:'INVALID_CONTACT'});if(!me.contacts.includes(target.id))me.contacts.push(target.id);if(!target.contacts.includes(me.id))target.contacts.push(me.id);save();return json(res,200,{ok:true})}
  const um=url.pathname.match(/^\/api\/users\/([a-f0-9-]{36})$/);
  if(um&&['PATCH','DELETE'].includes(req.method)){const u=byId(um[1]);if(!u||(!me.admin&&u.id!==me.id))return json(res,403,{error:'FORBIDDEN'});if(req.method==='DELETE'){if(!me.admin||u.admin)return json(res,403,{error:'FORBIDDEN'});store.users=store.users.filter(v=>v.id!==u.id);for(const v of store.users)v.contacts=v.contacts.filter(id=>id!==u.id);store.messages=store.messages.filter(m=>m.from!==u.id&&m.to!==u.id);revoke(u.id)}else{const x=JSON.parse(await body(req));if(x.name){if(typeof x.name!=='string'||x.name.length>64)throw Error('INVALID_USER');u.name=x.name}if(x.password){u.salt=crypto.randomBytes(16).toString('hex');u.hash=await passwordHash(x.password,u.salt);if(x.backup){u.backup={version:x.backup.version||2,algorithm:x.backup.algorithm||'AES-256-GCM',kdf:x.backup.kdf||'PBKDF2-SHA-256',iterations:x.backup.iterations||100000,salt:x.backup.salt,iv:x.backup.iv,ciphertext:x.backup.ciphertext,updatedAt:Date.now()}}else u.backup=null;revoke(u.id)}}save();return json(res,200,{ok:true})}
  if(url.pathname==='/api/upload'&&req.method==='POST'){
   const supplied=req.headers['x-upload-id'];if(supplied!==undefined&&(typeof supplied!=='string'||!/^[a-f0-9]{32}$/.test(supplied)))return json(res,400,{error:'INVALID_UPLOAD_ID'});
   const id=(supplied||crypto.randomBytes(16).toString('hex'))+'.bin',previous=store.uploads[id];
   if(previous&&previous.owner!==me.id)return json(res,409,{error:'UPLOAD_CONFLICT'});
   if(!previous&&(Object.keys(store.uploads).length>=1024||Object.values(store.uploads).reduce((n,item)=>n+item.size,0)>=STORAGE_BUDGET-MAX_UPLOAD))return json(res,413,{error:'LIMIT'});
   const data=await body(req,MAX_UPLOAD);if(data.length<28)return json(res,400,{error:'SEALED_MEDIA_REQUIRED'});if(bridgeInbox&&data.length>8*1024*1024)return json(res,413,{error:'FEDERATION_FILE_LIMIT'});
   const digest='sha256:'+crypto.createHash('sha256').update(data).digest('hex');
   if(previous){if(previous.digest!==digest||previous.size!==data.length)return json(res,409,{error:'UPLOAD_CONFLICT'});const saved=open(privateRead(path.join(DATA,id)),previous.purpose||'upload/'+id);if(!saved.equals(data))throw Error('UPLOAD_INTEGRITY');save();return json(res,201,{url:'/uploads/'+id,digest,duplicate:true})}
   // Recheck after the awaited body: another request may have installed this ID.
   if(store.uploads[id])return json(res,409,{error:'UPLOAD_RETRY'});
   if(Object.keys(store.uploads).length>=1024||Object.values(store.uploads).reduce((n,item)=>n+item.size,0)+data.length>STORAGE_BUDGET)return json(res,413,{error:'LIMIT'});
   const destination=path.join(DATA,id);
   if(fs.existsSync(destination)){const saved=open(privateRead(destination),'upload/'+id+'/'+me.id);if(!saved.equals(data))return json(res,409,{error:'UPLOAD_CONFLICT'})}else exclusive(destination,seal(data,'upload/'+id+'/'+me.id));
   store.uploads[id]={owner:me.id,size:data.length,digest,purpose:'upload/'+id+'/'+me.id};
   try{
    if(bridgeInbox){const target=path.join(bridgeInbox,digest.slice(7)+'.bin');if(!fs.existsSync(target))exclusive(target,data);if(!store.filePending.includes(digest))store.filePending.push(digest)}
    save();
   }catch(error){delete store.uploads[id];store.filePending=store.filePending.filter(item=>item!==digest);throw error}
   flushBridge();return json(res,201,{url:'/uploads/'+id,digest,duplicate:false});
  }
  if(url.pathname.startsWith('/uploads/')&&req.method==='GET'){const id=url.pathname.slice(9),upload=store.uploads[id];if(!/^[a-f0-9]{32}\.bin$/.test(id)||!upload||!(upload.owner===me.id||store.messages.some(m=>(m.from===me.id||m.to===me.id)&&m.attachments.includes('/uploads/'+id))))return json(res,404,{error:'NOT_FOUND'});const data=open(privateRead(path.join(DATA,id)),upload.purpose||'upload/'+id);res.writeHead(200,{'Content-Type':'application/octet-stream','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});return res.end(data)}
  return json(res,404,{error:'NOT_FOUND'});
 }
 if(req.method==='GET'&&url.pathname==='/manifest.webmanifest'){const manifest=JSON.parse(fs.readFileSync(path.join(FRONTEND,'manifest.webmanifest'),'utf8'));manifest.name=store.settings?.title||'网页管理';manifest.short_name=manifest.name.slice(0,24);return json(res,200,manifest)}
 if(req.method==='GET'&&staticFiles[url.pathname]){const [name,mime]=staticFiles[url.pathname];res.writeHead(200,{'Content-Type':mime+'; charset=utf-8','Cache-Control':'no-store','Content-Security-Policy':"default-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' blob:; media-src 'self' blob:; style-src 'self'; object-src 'none'; frame-ancestors 'none'",'X-Content-Type-Options':'nosniff'});return res.end(fs.readFileSync(path.join(FRONTEND,name)))}
 return json(res,404,{error:'NOT_FOUND'});
}catch(e){if(!res.headersSent)json(res,['PASSWORD_POLICY','INVALID_USER'].includes(e.message)?400:500,{error:['PASSWORD_POLICY','INVALID_USER','BUSY'].includes(e.message)?e.message:'REQUEST_REJECTED'})}});
server.requestTimeout=15000;server.headersTimeout=10000;
const wss=new WebSocketServer({noServer:true,maxPayload:8192});
server.on('upgrade',(req,socket,head)=>{const url=new URL(req.url,'http://localhost'),me=auth(req);if(url.pathname!=='/ws'||url.search||!originOK(req)||!me||[...wss.clients].filter(w=>w.userId===me.id).length>=4){socket.end('HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n');return}wss.handleUpgrade(req,socket,head,ws=>{ws.userId=me.id;ws.alive=true;wss.emit('connection',ws)})});
wss.on('connection',ws=>{send(ws,{type:'ready'});let count=0,start=Date.now();ws.on('pong',()=>ws.alive=true);ws.on('message',async raw=>{try{if(Date.now()-start>10000){start=Date.now();count=0}if(++count>64)return ws.close(1008);const me=byId(ws.userId);if(!me)return ws.close(4001);const x=JSON.parse(raw);
 if(x.action==='mode'){if(typeof x.mode==='string'&&transportManager.setUserMode(me.id,x.mode))send(ws,{type:'mode',mode:x.mode});return;}
  if(x.action==='read'){if(typeof x.id!=='string')return send(ws,{type:'error',error:'INVALID_RECEIPT'});const message=store.messages.find(m=>m.id===x.id&&m.to===me.id);if(!message||!can(me,message.from))return send(ws,{type:'error',error:'INVALID_RECEIPT'});message.readAt=Date.now();save();push([message.from],{type:'receipt',id:message.id,state:'read',time:message.readAt});transportManager.markRead(message.id);return;}
  if(x.action==='received'){
  if(typeof x.id!=='string')return send(ws,{type:'error',error:'INVALID_RECEIPT'});
  const message=store.messages.find(m=>m.id===x.id&&m.to===me.id);
  if(!message||!can(me,message.from))return send(ws,{type:'error',error:'INVALID_RECEIPT'});
  if(!message.receivedAt){message.receivedAt=Date.now();try{save()}catch(error){delete message.receivedAt;throw error}}
  push([message.from],{type:'receipt',id:message.id,state:'recipient-confirmed',time:message.receivedAt});return;
 }
 if(x.action==='history'){if(!can(me,x.peerId))return;return send(ws,{type:'history',peerId:x.peerId,messages:store.messages.filter(m=>(m.from===me.id&&m.to===x.peerId)||(m.to===me.id&&m.from===x.peerId)).slice(-100)})}
 if(x.action!=='send'||!can(me,x.to)||!/^([a-f0-9]{8}-){1}[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(x.id)||x.kind!=='sealed'||typeof x.ciphertext!=='string'||Buffer.from(x.ciphertext,'base64').length!==2048||Buffer.from(x.ciphertext,'base64').toString('base64')!==x.ciphertext||!Array.isArray(x.attachments)||x.attachments.length>2)return send(ws,{type:'error',error:'INVALID_FRAME'});
 const isCF=url=>typeof url==='string'&&(url.startsWith('cf1-')||url.startsWith('/cf1/')||url.startsWith('/content/cf1-'))&&/^(cf1-[a-f0-9]{64}|\/cf1\/[a-f0-9]{64}|\/content\/cf1-[a-f0-9]{64})$/.test(url);
 if(x.attachments.some(url=>!(/^\/uploads\/[a-f0-9]{32}\.bin$/.test(url)&&store.uploads[url.slice(9)]?.owner===me.id)&&!isCF(url)))return send(ws,{type:'error',error:'INVALID_ATTACHMENT'});
 const old=store.messages.find(m=>m.id===x.id);if(old){if(old.from!==me.id||old.to!==x.to||old.ciphertext!==x.ciphertext||JSON.stringify(old.attachments)!==JSON.stringify(x.attachments))return send(ws,{type:'error',error:'IDEMPOTENCY_CONFLICT'});save();return send(ws,{type:'ack',id:x.id})}
 if(store.messages.length>=10000||store.pending.length>=1000)return send(ws,{type:'error',error:'LIMIT'});
 const routeResult=await transportManager.routeMessage({id:x.id,from:me.id,to:x.to,kind:'sealed',ciphertext:x.ciphertext,attachments:x.attachments,transport:x.transport||transportManager.getUserMode(me.id),hops:x.hops,nonce:x.nonce||x.id},x.transport);
  const m={id:x.id,from:me.id,to:x.to,kind:'sealed',ciphertext:x.ciphertext,attachments:x.attachments,time:Date.now(),transport:routeResult.transport,hops:routeResult.hops,bridged:routeResult.bridged};store.messages.push(m);if(process.env.ZIOKT_BRIDGE_CONFIG)store.pending.push(m.id);try{save()}catch(error){store.messages.pop();store.pending=store.pending.filter(id=>id!==m.id);throw error}notifier?.enqueue(m.to);push([m.from,m.to],{type:'message',message:m,transport:routeResult.transport,hops:routeResult.hops,bridged:routeResult.bridged});send(ws,{type:'ack',id:m.id,state:routeResult.state,transport:routeResult.transport,hops:routeResult.hops,bridged:routeResult.bridged});flushBridge();
 }catch(_){send(ws,{type:'error',error:'INVALID_FRAME'})}})});
const bridge=process.env.ZIOKT_BRIDGE_CONFIG?new(require('./bridge').BridgeWorker)(path.resolve(process.env.ZIOKT_BRIDGE_CONFIG),process.env.ZIOKT_PYTHON||'python3',path.resolve(process.env.ZIOKT_PROJECT_ROOT||path.join(__dirname,'../../../..'))):null;
let bridgeBusy=false,bridgePollAt=0,bridgePollCursor=0;store.fileBackoff??={};
function bridgePairs(){const pairs=[],seen=new Set();for(const user of store.users)for(const peer of user.contacts||[]){if(!can(user,peer)||!can(byId(peer),user.id))continue;const key=[user.id,peer].sort().join('/');if(seen.has(key))continue;seen.add(key);pairs.push({from:user.id,to:peer})}return pairs}
async function pullBridgePair(){const pairs=bridgePairs();if(!pairs.length)return;const pair=pairs[bridgePollCursor++%pairs.length],reply=await bridge.call('chat.pull',pair);if(!reply||!Array.isArray(reply.messages)||reply.messages.length>12)throw Error('BRIDGE_PULL_INVALID');const ack=[];
 for(const frame of reply.messages){if(!frame||!/^([a-f0-9]{8}-){1}[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(frame.id)||!((frame.from===pair.from&&frame.to===pair.to)||(frame.from===pair.to&&frame.to===pair.from))||typeof frame.ciphertext!=='string'||Buffer.from(frame.ciphertext,'base64').length!==2048||Buffer.from(frame.ciphertext,'base64').toString('base64')!==frame.ciphertext||!Array.isArray(frame.attachments)||!Array.isArray(frame.attachment_digests)||frame.attachments.length!==frame.attachment_digests.length||frame.attachments.length>2)throw Error('BRIDGE_FRAME_INVALID');
  for(let i=0;i<frame.attachments.length;i++){const url=frame.attachments[i],digest=frame.attachment_digests[i],match=typeof url==='string'&&url.match(/^\/uploads\/([a-f0-9]{32})\.bin$/);if(!match||typeof digest!=='string'||!/^sha256:[a-f0-9]{64}$/.test(digest))throw Error('BRIDGE_ATTACHMENT_INVALID');const id=match[1]+'.bin',local=path.join(DATA,id),existing=store.uploads[id];if(existing){if(existing.digest!==digest)throw Error('BRIDGE_ATTACHMENT_CONFLICT');continue}if(!bridgeInbox)throw Error('BRIDGE_INBOX_REQUIRED');await bridge.call('file.read',{digest});const source=path.join(bridgeInbox,digest.slice(7)+'.bin'),stat=fs.lstatSync(source);if(stat.isSymbolicLink()||!stat.isFile()||stat.size>8*1024*1024)throw Error('BRIDGE_ATTACHMENT_INVALID');const data=privateRead(source);if('sha256:'+crypto.createHash('sha256').update(data).digest('hex')!==digest)throw Error('BRIDGE_ATTACHMENT_DIGEST');if(fs.existsSync(local)){const restored=open(privateRead(local),existing?.purpose||'upload/'+id);if('sha256:'+crypto.createHash('sha256').update(restored).digest('hex')!==digest)throw Error('BRIDGE_ATTACHMENT_CONFLICT')}else exclusive(local,seal(data,'upload/'+id));store.uploads[id]={owner:frame.from,size:data.length,digest}}
  // Membership can change while attachment retrieval awaits the federation.
  if(!can(byId(pair.from),pair.to)||!can(byId(pair.to),pair.from))throw Error('BRIDGE_CONTACT_REVOKED');
  const old=store.messages.find(message=>message.id===frame.id);if(old){if(old.from!==frame.from||old.to!==frame.to||old.ciphertext!==frame.ciphertext||JSON.stringify(old.attachments)!==JSON.stringify(frame.attachments))throw Error('BRIDGE_MESSAGE_CONFLICT');save()}else{if(store.messages.length>=10000)throw Error('LIMIT');const message={id:frame.id,from:frame.from,to:frame.to,kind:'sealed',ciphertext:frame.ciphertext,attachments:frame.attachments,time:Date.now()};store.messages.push(message);try{save()}catch(error){store.messages.pop();throw error}notifier?.enqueue(message.to);push([message.from,message.to],{type:'message',message})}ack.push(frame.event)}
 if(ack.length)await bridge.call('chat.ack',{...pair,events:ack});
}
async function flushBridge(){
 if(!bridge||bridgeBusy)return;
 const file=store.filePending.find(digest=>(store.fileBackoff[digest]||0)<=Date.now());
 store.pending=store.pending.filter(id=>store.messages.some(message=>message.id===id));
 const message=store.pending.length?store.messages.find(m=>m.id===store.pending[0]):null;
 const canPoll=bridgePairs().length>0&&Date.now()-bridgePollAt>=15000;
 if(!file&&!message&&!canPoll)return;bridgeBusy=true;
 try{
  if(file){await bridge.call('file.publish',{digest:file});const index=store.filePending.indexOf(file);if(index>=0)store.filePending.splice(index,1);delete store.fileBackoff[file]}
  else if(message){const attachment_digests=message.attachments.map(url=>{const upload=store.uploads[url.slice(9)];if(!upload||upload.owner!==message.from)throw Error('INVALID_ATTACHMENT');return upload.digest});await bridge.call('chat.append',{id:message.id,from:message.from,to:message.to,ciphertext:message.ciphertext,attachments:message.attachments,attachment_digests});const index=store.pending.indexOf(message.id);if(index>=0)store.pending.splice(index,1)}
  else{bridgePollAt=Date.now();await pullBridgePair()}
  save();
 }catch(_){if(file){store.fileBackoff[file]=Date.now()+30000;save()}}
 finally{bridgeBusy=false;if(store.pending.length||store.filePending.some(digest=>(store.fileBackoff[digest]||0)<=Date.now()))setTimeout(flushBridge,1000)}
}

const heartbeat=setInterval(()=>{const now=Date.now();for(const [token,s]of sessions)if(s.expires<now){sessions.delete(token);revoke(s.id)}for(const ws of wss.clients){if(!ws.alive)ws.terminate();else{ws.alive=false;ws.ping()}}flushBridge();simFederation?.flush();reminderScheduler.tick()},30000);
server.on('close',()=>{clearInterval(heartbeat);notifier?.close();bridge?.close();simBridge?.close();transportManager.close()});
(async()=>{if(!store.users.length){const password=process.env.ADMIN_PASSWORD;if(!password||password.length<12)throw Error('ADMIN_PASSWORD_REQUIRED');store.users.push(await makeUser('admin','Administrator',password,true));save()}if(!process.env.ZIOKT_BRIDGE_CONFIG&&!simBridge&&process.env.ZIOKT_STANDALONE!=='1')throw Error('FEDERATION_CONFIG_REQUIRED');server.listen(PORT,'127.0.0.1',()=>console.log('WATChat ready on loopback'))})().catch(e=>{clearInterval(heartbeat);console.error(e.message);process.exit(1)});
