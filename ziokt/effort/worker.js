'use strict';
importScripts('/profiles.js');
let busy=false;
const supported=()=>self.crypto&&self.crypto.subtle&&typeof self.crypto.subtle.digest==='function'&&typeof TextEncoder==='function'&&typeof BigInt==='function';
self.onmessage=async({data:job})=>{
 if(busy)return;
 if(!supported()){postMessage({error:'UNSUPPORTED_BROWSER'});return close()}
 if(job&&job.type==='probe'){try{await crypto.subtle.digest('SHA-256',new Uint8Array());postMessage({type:'ready'})}catch(_){postMessage({error:'UNSUPPORTED_BROWSER'});close()}return}
 if(!job||job.difficulty!==3||typeof job.start!=='string'||!/^\d{1,20}$/.test(job.start)||!Number.isInteger(job.limit)||job.limit<1||job.limit>1000000||!Number.isFinite(job.expires)||job.expires<=0||typeof job.network_id!=='string'||!job.network_id||job.network_id.length>128||typeof job.submitter_id!=='string'||!/^[a-f0-9]{64}$/.test(job.submitter_id)||typeof job.problem_id!=='string'||!/^[a-f0-9]{64}$/.test(job.problem_id)||!Number.isInteger(job.level)||job.level<1||job.level>5||!Number.isInteger(job.parts)||job.parts<1||job.parts>8||!Number.isInteger(job.part)||job.part<0||job.part>=job.parts){postMessage({error:'INVALID_JOB'});return close()}
 busy=true;
 try{
  const profile=EFFORT_PROFILES[job.level-1],encoder=new TextEncoder(),start=BigInt(job.start),began=performance.now();let hashes=0,lastReport=began;
  for(let offset=job.part;offset<job.limit;){
   if(Date.now()/1000>=job.expires||performance.now()-began>=90000)break;
   const nonces=[];for(let lane=0;lane<profile.lanes&&offset<job.limit;lane++,offset+=job.parts)nonces.push((start+BigInt(offset)).toString());
   const digests=await Promise.all(nonces.map(nonce=>crypto.subtle.digest('SHA-256',encoder.encode(job.network_id+job.submitter_id+nonce+job.problem_id))));
   hashes+=digests.length;
   for(let i=0;i<digests.length;i++){const hash=new Uint8Array(digests[i]);if(hash[0]===0&&(hash[1]&240)===0){postMessage({nonce:nonces[i],hashes,elapsed:performance.now()-began});return close()}}
   if(performance.now()-lastReport>=250){postMessage({type:'progress',hashes,elapsed:performance.now()-began});lastReport=performance.now()}
   if(hashes%profile.batch<profile.lanes)await new Promise(resolve=>setTimeout(resolve,profile.pause));
  }
  postMessage({exhausted:true,hashes,elapsed:performance.now()-began});close();
 }catch(_){postMessage({error:'UNSUPPORTED_BROWSER'});close()}
};
