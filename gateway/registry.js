(async()=>{
'use strict';const $=id=>document.getElementById(id),hex=b=>Array.from(new Uint8Array(b),x=>x.toString(16).padStart(2,'0')).join('');
const canonical=o=>JSON.stringify(o,(_,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]])):v);
const status=await fetch('/api/gateway/status').then(r=>r.json());
const template=()=>{const entry={kind:$('kind').value,target:'my-chain',description:'Describe chain or engine',weight:100};Object.assign(entry,entry.kind==='external_chain'?{genesis_hash:'',verifier_hash:''}:{pkg_id:'compute/example:0',compute_program_hash:'',verifier_script_hash:''});$('entry').value=JSON.stringify(entry,null,2);};$('kind').onchange=template;template();
async function refresh(){$('approved').textContent=JSON.stringify(await fetch('/api/gateway/registrations').then(r=>r.json()),null,2);}await refresh();
$('registration').onsubmit=async event=>{event.preventDefault();const button=event.target.querySelector('button');button.disabled=true;try{
 const entry=JSON.parse($('entry').value);const db=await new Promise((resolve,reject)=>{const r=indexedDB.open('ziokt-identity',1);r.onupgradeneeded=()=>r.result.createObjectStore('keys');r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
 let keys=await new Promise((resolve,reject)=>{const r=db.transaction('keys').objectStore('keys').get('registry');r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
 if(!keys){keys=await crypto.subtle.generateKey('Ed25519',false,['sign','verify']);await new Promise((resolve,reject)=>{const tx=db.transaction('keys','readwrite');tx.objectStore('keys').add(keys,'registry');tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);});}db.close();
 const payload={schema:'ziokt.registry.v1',network:status.network,entry,public_key:hex(await crypto.subtle.exportKey('raw',keys.publicKey)),timestamp:Math.floor(Date.now()/1000),nonce:hex(crypto.getRandomValues(new Uint8Array(32)))};
 payload.signature=hex(await crypto.subtle.sign('Ed25519',keys.privateKey,new TextEncoder().encode(canonical(payload))));
 const response=await fetch('/api/gateway/registrations',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const result=await response.json();if(!response.ok)throw new Error(result.error);$('result').textContent=JSON.stringify(result,null,2);await refresh();
}catch(error){$('result').textContent=error.message;}finally{button.disabled=false;}};
$('registration').dataset.ready='true';
})().catch(error=>{document.getElementById('result').textContent=error.message;});