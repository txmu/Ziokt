'use strict';
let busy=false;
const supported=()=>self.crypto&&self.crypto.subtle&&typeof self.crypto.subtle.digest==='function'&&typeof TextEncoder==='function'&&typeof BigInt==='function';
self.onmessage=async({data:job})=>{
 if(busy)return;
 if(!supported()){postMessage({error:'UNSUPPORTED_BROWSER'});return close()}
 if(job&&job.type==='probe'){
  try{await crypto.subtle.digest('SHA-256',new Uint8Array());postMessage({type:'ready'})}
  catch(error){postMessage({error:'UNSUPPORTED_BROWSER'});close()}
  return;
 }
 if(!job||job.difficulty!==3||typeof job.start!=='string'||!/^\d{1,20}$/.test(job.start)||!Number.isInteger(job.limit)||job.limit<1||job.limit>1000000||!Number.isFinite(job.expires)||job.expires<=0||typeof job.network_id!=='string'||!job.network_id||job.network_id.length>128||typeof job.submitter_id!=='string'||!/^[a-f0-9]{64}$/.test(job.submitter_id)||typeof job.problem_id!=='string'||!/^[a-f0-9]{64}$/.test(job.problem_id)){
  postMessage({error:'INVALID_JOB'});return close();
 }
 busy=true;
 try{
  const encoder=new TextEncoder(),start=BigInt(job.start),began=performance.now();
  for(let offset=0;offset<job.limit;offset++){
   if(Date.now()/1000>=job.expires||performance.now()-began>=90000)break;
   const nonce=(start+BigInt(offset)).toString();
   const hash=new Uint8Array(await crypto.subtle.digest('SHA-256',encoder.encode(job.network_id+job.submitter_id+nonce+job.problem_id)));
   if(hash[0]===0&&(hash[1]&240)===0){postMessage({nonce});return close()}
   // Fixed browser budget: a server cannot raise batch size or remove pauses.
   if(offset%64===63)await new Promise(resolve=>setTimeout(resolve,40));
  }
  postMessage({exhausted:true});close();
 }catch(error){postMessage({error:'UNSUPPORTED_BROWSER'});close()}
};
