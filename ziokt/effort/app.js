'use strict';
const button=document.querySelector('#start'),status=document.querySelector('#status');
const language=navigator.language||(navigator.languages&&navigator.languages[0])||'en';
const en=!language.toLowerCase().startsWith('zh');
let active=false,worker=null,workerCancel=null,controller=null,timer=null,epoch=0;
const text=(english,chinese)=>en?english:chinese;
function label(){button.textContent=active?text('Stop','停止奋斗'):text('Start contributing','一键开始奋斗');button.setAttribute('aria-pressed',String(active))}
if(en){document.documentElement.lang='en';document.title='Contribute · Ziokt';document.querySelector('h1').textContent='Contribute together';document.querySelector('#notice').textContent='Starting uses this device’s CPU and battery for Corium Engine Zero. Contributions belong to the server’s configured node. Stop anytime; leaving or hiding this page stops computation.';status.textContent='Not started'}
label();
function hidden(){return document.hidden===true||document.visibilityState==='hidden'||document.webkitHidden===true}
function terminate(instance){if(instance)instance.terminate();if(worker===instance)worker=null}
function stop(message){active=false;epoch++;clearTimeout(timer);timer=null;if(workerCancel)workerCancel();terminate(worker);if(controller)controller.abort();controller=null;label();status.textContent=typeof message==='string'?message:text('Stopped','已停止')}
function supported(){return window.isSecureContext===true&&window.crypto&&window.crypto.subtle&&typeof window.crypto.subtle.digest==='function'&&typeof window.Worker==='function'&&typeof window.AbortController==='function'&&typeof window.fetch==='function'&&typeof window.TextEncoder==='function'&&typeof window.BigInt==='function'}
async function api(path,value){
 const request=new AbortController();controller=request;
 const deadline=setTimeout(()=>request.abort(),20000);
 try{const res=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value),signal:request.signal,credentials:'same-origin',cache:'no-store'});const data=await res.json();if(!res.ok)throw Error(data.error||'REQUEST_FAILED');return data}
 finally{clearTimeout(deadline);if(controller===request)controller=null}
}
function exchange(instance,message,generation,milliseconds){
 return new Promise((resolve,reject)=>{
  let finished=false;
  function finish(error,value){if(finished)return;finished=true;clearTimeout(deadline);instance.onmessage=null;instance.onerror=null;instance.onmessageerror=null;if(workerCancel===cancel)workerCancel=null;if(error)reject(error);else resolve(value)}
  function cancel(){finish(Error('STOPPED'))}
  const deadline=setTimeout(()=>finish(Error('WORKER_TIMEOUT')),milliseconds);
  workerCancel=cancel;
  instance.onerror=event=>{event.preventDefault();finish(Error('WORKER_UNAVAILABLE'))};
  instance.onmessageerror=()=>finish(Error('WORKER_UNAVAILABLE'));
  instance.onmessage=event=>{if(!active||generation!==epoch||worker!==instance)return cancel();const value=event.data;if(!value||typeof value!=='object')return finish(Error('INVALID_WORKER_RESULT'));if(value.error)return finish(Error(value.error));finish(null,value)};
  try{instance.postMessage(message)}catch(error){finish(Error('WORKER_UNAVAILABLE'))}
 });
}
function retry(generation){if(active&&generation===epoch)timer=setTimeout(()=>next(generation),5000)}
async function next(generation){
 if(!active||generation!==epoch||hidden())return;
 let instance=null;
 try{
  try{instance=new Worker('/worker.js')}catch(error){throw Error('WORKER_UNAVAILABLE')}
  worker=instance;
  const ready=await exchange(instance,{type:'probe'},generation,5000);
  if(ready.type!=='ready')throw Error('WORKER_UNAVAILABLE');
  const job=await api('/api/job',{});
  if(!active||generation!==epoch)return;
  if(!job.available){terminate(instance);status.textContent=text('Waiting for a chain task','等待链上新任务');retry(generation);return}
  status.textContent=text('Computing with short pauses','正在计算，间歇休息');
  const result=await exchange(instance,job,generation,90000);
  terminate(instance);
  if(!active||generation!==epoch)return;
  if(typeof result.nonce==='string'){
   const receipt=await api('/api/proof',{token:job.token,nonce:result.nonce});
   if(!active||generation!==epoch)return;
   status.textContent=receipt.confirmed?text('Confirmed','已确认'):text('Proof submitted; awaiting chain consensus','证明已提交，等待链上共识');
  }
  retry(generation);
 }catch(error){
  terminate(instance);
  if(!active||generation!==epoch)return;
  if(['UNSUPPORTED_BROWSER','WORKER_UNAVAILABLE'].includes(error.message)){stop(text('This browser needs HTTPS, Web Crypto and dedicated workers. Try an updated browser.','此浏览器需要 HTTPS、Web Crypto 与专用 Worker 支持，请更新浏览器。'));return}
  status.textContent=text('Task changed or server unavailable; retrying','任务变化或服务暂不可用，稍后重试');retry(generation);
 }
}
button.addEventListener('click',()=>{
 if(active)return stop();
 if(!supported()){status.textContent=text('This browser needs HTTPS, Web Crypto and dedicated workers. Try an updated browser.','此浏览器需要 HTTPS、Web Crypto 与专用 Worker 支持，请更新浏览器。');return}
 if(hidden())return;
 active=true;label();next(++epoch);
});
function background(){if(hidden()&&active)stop()}
document.addEventListener('visibilitychange',background);
document.addEventListener('webkitvisibilitychange',background);
document.addEventListener('freeze',()=>stop());
addEventListener('pagehide',()=>stop());
addEventListener('pageshow',event=>{if(event.persisted)stop()});
