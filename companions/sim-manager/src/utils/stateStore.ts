// Persistent nonextractable browser key; this protects stored bytes, not a compromised origin.
import type { AppData } from '../types';
const encode=new TextEncoder(),decode=new TextDecoder();
async function database():Promise<IDBDatabase>{return new Promise((resolve,reject)=>{const r=indexedDB.open('ziokt-sim-vault',1);r.onupgradeneeded=()=>r.result.createObjectStore('vault');r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)})}
async function operation(db:IDBDatabase,key:string,value?:unknown):Promise<any>{return new Promise((resolve,reject)=>{const tx=db.transaction('vault',value===undefined?'readonly':'readwrite'),store=tx.objectStore('vault'),r=value===undefined?store.get(key):store.put(value,key);let result:any;r.onsuccess=()=>result=r.result;tx.oncomplete=()=>resolve(result);tx.onerror=()=>reject(tx.error)})}
async function key(db:IDBDatabase,create=true):Promise<CryptoKey>{
 const existing=await operation(db,'key');if(existing)return existing;
 if(!create)throw Error('SIM_KEY_MISSING');
 // Generate outside the transaction, then atomically select the first committed key.
 // A second tab must use that key rather than replace it with its own candidate.
 const candidate=await crypto.subtle.generateKey({name:'AES-GCM',length:256},false,['encrypt','decrypt']);
 return new Promise((resolve,reject)=>{const tx=db.transaction('vault','readwrite'),store=tx.objectStore('vault'),read=store.get('key');let selected:CryptoKey;
 read.onsuccess=()=>{selected=read.result||candidate;if(!read.result)store.put(candidate,'key')};
 tx.oncomplete=()=>resolve(selected);tx.onerror=tx.onabort=()=>reject(tx.error||Error('SIM_KEY_TRANSACTION'))})
}
function validate(value:any):AppData{if(!value||typeof value!=='object'||!Array.isArray(value.subscriptions)||value.subscriptions.length>1024||!Array.isArray(value.eSimChips)||value.eSimChips.length>1024||!Array.isArray(value.scripts)||value.scripts.length>128)throw Error('INVALID_SIM_STATE');return value}
let writes=Promise.resolve();
export function saveState(value:AppData):Promise<void>{writes=writes.catch(()=>{}).then(async()=>{const plain=encode.encode(JSON.stringify(validate(value)));if(plain.length>4*1024*1024)throw Error('SIM_STATE_LIMIT');const db=await database();try{const nonce=crypto.getRandomValues(new Uint8Array(12)),cipher=await crypto.subtle.encrypt({name:'AES-GCM',iv:nonce,additionalData:encode.encode('Ziokt/SIM/state/v1')},await key(db),plain);await operation(db,'state',{nonce,cipher})}finally{db.close()}});return writes}
export async function loadState():Promise<AppData|null>{const db=await database();try{const sealed=await operation(db,'state');if(sealed){const plain=await crypto.subtle.decrypt({name:'AES-GCM',iv:sealed.nonce,additionalData:encode.encode('Ziokt/SIM/state/v1')},await key(db,false),sealed.cipher);return validate(JSON.parse(decode.decode(plain)))}}finally{db.close()}const legacy=localStorage.getItem('sim-manager-data-v3');if(!legacy)return null;if(legacy.length>4*1024*1024)throw Error('SIM_STATE_LIMIT');const value=validate(JSON.parse(legacy));await saveState(value);localStorage.removeItem('sim-manager-data-v3');return value}
