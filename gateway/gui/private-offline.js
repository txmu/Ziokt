/* Opt-in private offline copies. No credentials or plaintext enter IndexedDB. */
import {State,getActiveRemoteNode} from './core.js';

const PRIVATE_OFFLINE_DB='ziokt-private-offline-v1',PRIVATE_OFFLINE_MAX=64*1024*1024,PRIVATE_OFFLINE_FILE=16*1024*1024;
function offlineRequest(request){return new Promise((resolve,reject)=>{request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);});}
function offlineDone(transaction){return new Promise((resolve,reject)=>{transaction.oncomplete=resolve;transaction.onabort=()=>reject(transaction.error||Error('Offline transaction aborted'));transaction.onerror=()=>reject(transaction.error);});}
export class PrivateOfflineVault extends EventTarget{
 #db;#key=null;#generation=0;#timer;
 async database(){if(!this.#db)this.#db=new Promise((resolve,reject)=>{const request=indexedDB.open(PRIVATE_OFFLINE_DB,1);request.onupgradeneeded=()=>{for(const name of ['vault','entries','blobs'])request.result.createObjectStore(name,{keyPath:'id'});};request.onsuccess=()=>{const db=request.result;db.onversionchange=()=>{this.lock();db.close();this.#db=null;};resolve(db);};request.onerror=()=>reject(request.error);request.onblocked=()=>reject(Error('Close other offline-cache tabs first'));});return this.#db;}
 get unlocked(){return this.#key!==null;}
 lock(){this.#key=null;this.#generation++;clearTimeout(this.#timer);this.dispatchEvent(new Event('lock'));}
 async unlock(password){
  this.lock();if(typeof password!=='string'||password.length<12||password.length>1024)throw Error('Use an offline password of 12–1024 characters');
  const generation=this.#generation,db=await this.database(),tx=db.transaction('vault'),existing=await offlineRequest(tx.objectStore('vault').get('main'));
  const salt=existing?existing.salt:crypto.getRandomValues(new Uint8Array(16));
  if(!(salt instanceof Uint8Array)||salt.length!==16||(existing&&existing.version!==1))throw Error('Unsupported offline vault');
  const material=await crypto.subtle.importKey('raw',new TextEncoder().encode(password),'PBKDF2',false,['deriveKey']);
  const key=await crypto.subtle.deriveKey({name:'PBKDF2',salt,iterations:310000,hash:'SHA-256'},material,{name:'AES-GCM',length:256},false,['encrypt','decrypt']);
  const aad=new TextEncoder().encode('Ziokt/private-offline/v1/verifier');
  if(existing){try{const value=await crypto.subtle.decrypt({name:'AES-GCM',iv:existing.iv,additionalData:aad},key,existing.box);if(new TextDecoder().decode(value)!=='Ziokt private offline vault v1')throw Error();}catch{throw Error('Wrong offline password or damaged vault');}}
  else {
   const iv=crypto.getRandomValues(new Uint8Array(12)),box=await crypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:aad},key,new TextEncoder().encode('Ziokt private offline vault v1'));
   if(generation!==this.#generation)throw Error('Offline vault locked');
   const write=db.transaction('vault','readwrite');write.objectStore('vault').add({id:'main',version:1,salt,iv,box});await offlineDone(write);
  }
  if(generation!==this.#generation)throw Error('Offline vault locked');this.#key=key;this.#timer=setTimeout(()=>this.lock(),15*60*1000);this.dispatchEvent(new Event('change'));return true;
 }
 session(){if(!this.#key)throw Error('Unlock the offline vault first');return {key:this.#key,generation:this.#generation};}
 assertSession(session){if(session.generation!==this.#generation||!this.#key)throw Error('Offline vault locked');}
 aad(id,part){return new TextEncoder().encode('Ziokt/private-offline/v1/'+id+'/'+part);}
 async records(){const db=await this.database();return offlineRequest(db.transaction('entries').objectStore('entries').getAll());}
 async list(){
  const session=this.session(),result=[];
  for(const record of await this.records()){
   if(record.expires<=Date.now()){await this.remove(record.id);continue;}
   const raw=await crypto.subtle.decrypt({name:'AES-GCM',iv:record.iv,additionalData:this.aad(record.id,'metadata')},session.key,record.box),metadata=JSON.parse(new TextDecoder().decode(raw));
   this.assertSession(session);if(metadata.expires!==record.expires)throw Error('Offline expiry integrity failed');result.push({...metadata,id:record.id});
  }
  this.assertSession(session);return result;
 }
 async save(metadata,data){
  const session=this.session();if(!(data instanceof Uint8Array))data=new Uint8Array(data);
  if(data.byteLength>PRIVATE_OFFLINE_FILE)throw Error('Offline file limit: 16 MiB');
  if(!['book','article','attachment'].includes(metadata.kind)||typeof metadata.source!=='string'||metadata.source.length>2048||typeof metadata.source_id!=='string'||metadata.source_id.length>512)throw Error('Offline source metadata required');
  const digest='sha256:'+Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',data)),b=>b.toString(16).padStart(2,'0')).join('');if(metadata.digest&&metadata.digest!==digest)throw Error('Offline content digest mismatch');
  const prior=(await this.list()).find(item=>item.source===metadata.source&&item.source_id===metadata.source_id&&item.kind===metadata.kind),id=prior?.id||crypto.randomUUID(),expires=Date.now()+7*86400000;
  const value={...metadata,digest,size:data.byteLength,expires},raw=new TextEncoder().encode(JSON.stringify(value));if(raw.byteLength>65536)throw Error('Offline metadata budget exceeded');
  const iv=crypto.getRandomValues(new Uint8Array(12)),contentIv=crypto.getRandomValues(new Uint8Array(12));
  const box=await crypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:this.aad(id,'metadata')},session.key,raw),content=await crypto.subtle.encrypt({name:'AES-GCM',iv:contentIv,additionalData:this.aad(id,'content')},session.key,data);
  this.assertSession(session);const db=await this.database();this.assertSession(session);
  const tx=db.transaction(['entries','blobs'],'readwrite'),entries=tx.objectStore('entries'),blobs=tx.objectStore('blobs');let failure;
  entries.getAll().onsuccess=event=>{
   try{
    this.assertSession(session);let total=0,count=0;
    for(const record of event.target.result){if(record.expires<=Date.now()){entries.delete(record.id);blobs.delete(record.id);}else if(record.id!==id){if(!Number.isSafeInteger(record.bytes)||record.bytes<0)throw Error('Damaged offline quota metadata');total+=record.bytes;count++;}}
    const bytes=box.byteLength+content.byteLength;if(count>=256||total+bytes>PRIVATE_OFFLINE_MAX)throw Error('Offline quota: 64 MiB / 256 items; delete older copies');
    entries.put({id,iv,contentIv,box,expires,bytes});blobs.put({id,box:content});
   }catch(error){failure=error;tx.abort();}
  };
  try{await offlineDone(tx);}catch(error){throw failure||error;}this.assertSession(session);this.dispatchEvent(new Event('change'));return {...value,id};
 }
 async read(id){
  const session=this.session(),db=await this.database(),tx=db.transaction(['entries','blobs']);
  const [record,blob]=await Promise.all([offlineRequest(tx.objectStore('entries').get(id)),offlineRequest(tx.objectStore('blobs').get(id))]);
  if(!record||!blob)throw Error('Offline copy missing');if(record.expires<=Date.now()){await this.remove(id);throw Error('Offline copy expired');}
  const raw=await crypto.subtle.decrypt({name:'AES-GCM',iv:record.iv,additionalData:this.aad(id,'metadata')},session.key,record.box),metadata=JSON.parse(new TextDecoder().decode(raw));
  if(metadata.expires!==record.expires)throw Error('Offline expiry integrity failed');
  const bytes=await crypto.subtle.decrypt({name:'AES-GCM',iv:record.contentIv,additionalData:this.aad(id,'content')},session.key,blob.box),digest='sha256:'+Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
  this.assertSession(session);if(digest!==metadata.digest||bytes.byteLength!==metadata.size)throw Error('Offline content integrity failed');return {metadata,bytes};
 }
 async remove(id){const db=await this.database(),tx=db.transaction(['entries','blobs'],'readwrite');tx.objectStore('entries').delete(id);tx.objectStore('blobs').delete(id);await offlineDone(tx);this.dispatchEvent(new Event('change'));}
 async clear(){this.lock();const db=await this.database(),tx=db.transaction(['entries','blobs','vault'],'readwrite');for(const name of ['entries','blobs','vault'])tx.objectStore(name).clear();await offlineDone(tx);this.dispatchEvent(new Event('change'));}
}
export const privateOfflineVault=new PrivateOfflineVault();
if(typeof window!=='undefined')window.privateOfflineVault=privateOfflineVault;
window.addEventListener('pagehide',()=>privateOfflineVault.lock());
window.addEventListener('ziokt-private-cache-lock',()=>privateOfflineVault.lock());
document.addEventListener('visibilitychange',()=>{if(document.hidden)privateOfflineVault.lock();});
export function privateOfflineSource(){return State.runtimeMode==='local'?State.localGatewayUrl:(getActiveRemoteNode()?.url||State.gatewayUrl);}

export function mountPrivateOffline(container){
 const en=State.language==='en',tr=(zh,english)=>en?english:zh,node=(tag,text)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;return el;};
 const panel=node('section');panel.className='card private-offline-panel';panel.id='private-offline-panel';panel.append(node('h3',tr('私有离线正文与附件','Private offline text and attachments')),node('p',tr('主动保存后在本机加密，密码不保存。单文件16 MiB，总64 MiB；7天过期，切到后台或15分钟后锁定。离线副本不能实时接收远端撤销；忘记密码需清空后重新下载。','Opt-in encrypted local copies. Password is never stored. 16 MiB/file, 64 MiB total, 7-day expiry. Locks in the background or after 15 minutes. Offline copies cannot receive remote revocations; a lost password requires clearing and downloading again.')));
 const form=node('form'),label=node('label',tr('离线密码（首次设置至少12个字符）','Offline password (at least 12 characters)')),password=node('input');password.type='password';password.autocomplete='off';password.minLength=12;password.maxLength=1024;password.required=true;password.id='private-offline-password';label.append(password);form.append(label);panel.append(form);
 const status=node('p');status.id='private-offline-status';status.setAttribute('role','status');panel.append(status);const list=node('div');list.id='private-offline-list';panel.append(list);const viewer=node('section');viewer.id='private-offline-viewer';panel.append(viewer);const urls=new Set();
 function locked(){for(const url of urls)URL.revokeObjectURL(url);urls.clear();list.replaceChildren();viewer.replaceChildren();password.value='';status.textContent=tr('已锁定','Locked');}
 async function execute(operation){try{await operation();}catch(error){status.textContent=error.message;}}
 function button(parent,title,operation,id){const value=node('button',title);value.type='button';value.className='btn btn-secondary';if(id)value.id=id;value.onclick=async()=>{value.disabled=true;await execute(operation);value.disabled=false;};parent.append(value);return value;}
 async function refresh(){list.replaceChildren();const items=await privateOfflineVault.list();for(const item of items){const row=node('article');row.className='card';row.append(node('h4',item.title||item.source_id),node('small',item.kind+' · '+item.size+' bytes · '+new Date(item.expires).toLocaleDateString()));button(row,tr('离线打开','Open offline'),async()=>{const {metadata,bytes}=await privateOfflineVault.read(item.id);viewer.replaceChildren(node('h4',metadata.title||metadata.source_id));if(metadata.kind==='article'||['text/plain','text/markdown','text/html'].includes(metadata.mime)){const text=node('pre',new TextDecoder().decode(bytes));text.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere';viewer.append(text);}const url=URL.createObjectURL(new Blob([bytes],{type:'application/octet-stream'}));urls.add(url);const link=node('a',tr('保存已校验文件','Save verified file'));link.href=url;link.download=(metadata.filename||metadata.title||'offline.bin').replace(/[\\/\x00-\x1f]/g,'_');viewer.append(link);});button(row,tr('删除离线副本','Delete offline copy'),async()=>{await privateOfflineVault.remove(item.id);await refresh();});list.append(row);}status.textContent=tr('已解锁，离线副本：','Unlocked, offline copies: ')+items.length;}
 const unlock=node('button',tr('创建 / 解锁离线保险箱','Create / unlock offline vault'));unlock.id='private-offline-unlock';unlock.className='btn btn-primary';form.append(unlock);
 form.onsubmit=async event=>{event.preventDefault();unlock.disabled=true;const secret=password.value;password.value='';await execute(async()=>{await privateOfflineVault.unlock(secret);await refresh();});unlock.disabled=false;};
 button(panel,tr('刷新离线列表','Refresh offline list'),refresh,'private-offline-refresh');button(panel,tr('锁定','Lock'),()=>privateOfflineVault.lock(),'private-offline-lock');button(panel,tr('清空本机离线副本及密码','Clear local copies and password'),async()=>{await privateOfflineVault.clear();locked();},'private-offline-clear');
 privateOfflineVault.addEventListener('lock',locked);const observer=new MutationObserver(()=>{if(!panel.isConnected){privateOfflineVault.removeEventListener('lock',locked);observer.disconnect();for(const url of urls)URL.revokeObjectURL(url);}});observer.observe(document.documentElement,{childList:true,subtree:true});
 container.append(panel);if(privateOfflineVault.unlocked)execute(refresh);else locked();return {refresh};
}
