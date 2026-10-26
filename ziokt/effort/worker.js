'use strict';
importScripts('/profiles.js');
let busy=false;
const supported=()=>self.crypto&&self.crypto.subtle&&typeof self.crypto.subtle.digest==='function'&&typeof TextEncoder==='function'&&typeof BigInt==='function';
self.onmessage=async({data:job})=>{
 if(busy)return;
 if(job&&job.type==='probe'&&job.engine==='gimps'){
  postMessage(typeof BigInt==='function'?{type:'ready'}:{error:'UNSUPPORTED_BROWSER'});return;
 }
 if(job&&job.engine==='gimps'){
  const isPrp=job.exponent!==2&&(job.proof_schema==='corium.gimps-prp-proof.v1'||job.method==='prp-fiat-shamir');
  const isLL=(job.proof_schema==='corium.gimps-proof.v2'&&job.method==='lucas-lehmer')||job.exponent===2;
  const maxExp=isPrp?Math.min(job.max_exponent||100000,100000):4096;
  if(typeof BigInt!=='function'||!Number.isInteger(job.exponent)||job.exponent<2||job.exponent>maxExp||job.problem_id!==String(job.exponent)||(!isPrp&&!isLL)||!Number.isInteger(job.level)||job.level<1||job.level>5||!Number.isFinite(job.expires)||job.expires<=Date.now()/1000){postMessage({error:'INVALID_JOB'});return close()}
  const p=job.exponent,profile=EFFORT_PROFILES[job.level-1],began=performance.now();
  if(p>2&&Array.from({length:Math.floor(Math.sqrt(p))-1},(_,i)=>i+2).some(divisor=>p%divisor===0)){postMessage({error:'INVALID_JOB'});return close()}
  busy=true;
  try{
   const modulus=(BigInt(1)<<BigInt(p))-BigInt(1);
   if(isPrp){
    let s=BigInt(3),startIter=0;
    if(job.checkpoint&&Number.isInteger(job.checkpoint.iteration)&&typeof job.checkpoint.s==='string'&&job.checkpoint.s.length<=Math.ceil(p/3)&&/^[0-9]+$/.test(job.checkpoint.s)&&job.checkpoint.iteration>=0&&job.checkpoint.iteration<p-1){
     try{s=BigInt(job.checkpoint.s);startIter=job.checkpoint.iteration}catch(_){}
    }
    for(let i=startIter;i<p-1;i++){
     if(Date.now()/1000>=job.expires||performance.now()-began>90000){postMessage({exhausted:true,checkpoint:{iteration:i,s:s.toString()}});return close()}
     s=(s*s)%modulus;
     if((i+1)%profile.batch===0){postMessage({type:'progress',iterations:i+1,total:p-1,elapsed:performance.now()-began,checkpoint:{iteration:i+1,s:s.toString()}});await new Promise(resolve=>setTimeout(resolve,profile.pause))}
    }
    const inv3=(BigInt(2)*modulus+BigInt(1))/BigInt(3);
    const y=(s*inv3)%modulus;
    const is_prime=p===2?true:(y===modulus-BigInt(1));
    const res64=(y&BigInt('0xFFFFFFFFFFFFFFFF')).toString(16).toUpperCase().padStart(16,'0');
    const encoder=new TextEncoder();
    const proof_steps=[];
    let curr_X=BigInt(3),curr_Y=(BigInt(3)*y)%modulus,curr_T=p-1;
    function modPow(base,exp,mod){let res=BigInt(1),b=base%mod,e=exp;while(e>BigInt(0)){if(e%BigInt(2)===BigInt(1))res=(res*b)%mod;e=e/BigInt(2);b=(b*b)%mod}return res}
    for(let d=0;(curr_T>4096||d<4)&&curr_T>1&&d<64;d++){
     const was_odd=(curr_T%2===1);
     if(was_odd){curr_X=(curr_X*curr_X)%modulus;curr_T-=1}
     const half=Math.floor(curr_T/2);
     let Z=curr_X;
     for(let j=0;j<half;j++)Z=(Z*Z)%modulus;
     const hBuf=await crypto.subtle.digest('SHA-256',encoder.encode(`${curr_X}:${curr_Y}:${Z}:${modulus}`));
     const hHex=Array.from(new Uint8Array(hBuf)).map(b=>b.toString(16).padStart(2,'0')).join('');
     const r=BigInt('0x'+hHex.slice(0,16));
     proof_steps.push({Z:'0x'+Z.toString(16),odd:was_odd});
     curr_X=(modPow(curr_X,r,modulus)*Z)%modulus;
     curr_Y=(modPow(Z,r,modulus)*curr_Y)%modulus;
     curr_T=half;
    }
    const digest=async text=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',encoder.encode(text)))).map(b=>b.toString(16).padStart(2,'0')).join('');
    const square=async(value,count)=>{for(let i=0;i<count;i++){value=value*value%modulus;if(i%256===255){if(Date.now()/1000>=job.expires||performance.now()-began>90000)throw Error('deadline');await new Promise(resolve=>setTimeout(resolve,profile.pause))}}return value};
    const transition=async(x,y,count)=>{
     const steps=[];
     while(count>32){
      const odd=count%2===1;
      if(odd){x=x*x%modulus;count--}
      const z=await square(x,Math.floor(count/2));
      const r=BigInt('0x'+await digest(`corium-checkpoint-v1:${x.toString(16)}:${y.toString(16)}:${z.toString(16)}:${modulus.toString(16)}:${count}`));
      steps.push({Z:'0x'+z.toString(16),odd});
      x=modPow(x,r,modulus)*z%modulus;y=modPow(z,r,modulus)*y%modulus;count=Math.floor(count/2);
     }
     return steps;
    };
    const gerbicz_checkpoints=[];
    let curr_chk_hash=await digest(`gerbicz-init:${p}:3:4294967311`),previousIt=0,previousState=BigInt(3);
    const chk_intervals=[...new Set([0,Math.floor((p-1)/2),p-1])].sort((a,b)=>a-b);
    for(const it of chk_intervals){
     const state=await square(previousState,it-previousIt);
     const state_hash=await digest(`${p}:${it}:${state.toString(16)}`);
     const res64=(state&BigInt('0xFFFFFFFFFFFFFFFF')).toString(16).toUpperCase().padStart(16,'0');
     const math_residue_q=Number(state%BigInt('4294967311'));
     curr_chk_hash=await digest(`${curr_chk_hash}:${it}:${state_hash}:${res64}:${math_residue_q}`);
     gerbicz_checkpoints.push({iteration:it,state:'0x'+state.toString(16),state_hash,res64,math_residue_q,hash:curr_chk_hash,transition:await transition(previousState,state,it-previousIt)});
     previousIt=it;previousState=state;
    }
    const block_size=Math.max(1,Math.floor(Math.sqrt(p-1))),blocks=Math.floor((p-1)/block_size);
    let blockState=BigInt(3),product=BigInt(1);
    for(let b=0;b<blocks;b++){product=product*blockState%modulus;blockState=await square(blockState,block_size)}
    if((await square(product,block_size))*BigInt(3)%modulus!==product*blockState%modulus)throw Error('Gerbicz identity');
    const gerbicz_check={block_size,blocks,product:'0x'+product.toString(16),end_state:'0x'+blockState.toString(16),transition:await transition(BigInt(3),blockState,blocks*block_size)};
    const KNOWN=[2,3,5,7,13,17,19,31,61,89,107,127,521,607,1279,2203,2281,3217,4253,4423,9689,9941,11213,19937,21701,23209,44497,86243,110503,132049,216091,756839,859433,1257787,1398269,2976221,3021377,6972593,13466917,20996011,24036583,25964951,30402457,32582657,37156667,42643801,43112609,57885161,74207281,77232917,82589933,136279841];
    postMessage({
     proof:{
      schema:'corium.gimps-prp-proof.v1',
      exponent:p,
      method:'prp-fiat-shamir',
      base:3,
      residue:y.toString(),
      res64:res64,
      is_prp:is_prime,
      prp_result:is_prime?'PRP':'COMPOSITE',
      is_prime:(is_prime&&KNOWN.includes(p)),
      iterations:p-1,
      proof_steps:proof_steps,
      gerbicz_status:'OK',
      gerbicz_checkpoints:gerbicz_checkpoints,
      gerbicz_check
     }
    });
    return close();
   }else{
    let residue=p===2?BigInt(0):BigInt(4);
    for(let i=0;i<p-2;i++){
     if(Date.now()/1000>=job.expires||performance.now()-began>90000){postMessage({exhausted:true});return close()}
     residue=(residue*residue-BigInt(2))%modulus;
     if((i+1)%profile.batch===0){postMessage({type:'progress',iterations:i+1,total:p-2,elapsed:performance.now()-began});await new Promise(resolve=>setTimeout(resolve,profile.pause))}
    }
    postMessage({proof:{schema:'corium.gimps-proof.v2',exponent:p,method:'lucas-lehmer',residue:residue.toString(),is_prime:residue===BigInt(0),iterations:p-2}});return close();
   }
  }catch(_){postMessage({error:'INVALID_JOB'});return close()}
 }
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
