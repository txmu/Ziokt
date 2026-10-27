(async()=>{
 'use strict';
 const box=document.querySelector('#mcp-console');if(!box)return;
 const connect=document.querySelector('#mcp-connect'),disconnect=document.querySelector('#mcp-disconnect'),form=document.querySelector('#mcp-form'),select=document.querySelector('#mcp-tool'),output=document.querySelector('#mcp-result');
 let issuer=sessionStorage.getItem('ziokt_mcp_issuer')||location.origin;
 let resource=issuer+'/mcp';
 let token=sessionStorage.getItem('ziokt_mcp_access'),tools=[];
 const meta=()=>({'io.modelcontextprotocol/protocolVersion':'2026-07-28','io.modelcontextprotocol/clientCapabilities':{},'io.modelcontextprotocol/clientInfo':{name:'ziokt-native-portal',version:'2.0.0'}});
 const b64=bytes=>btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
 async function rpc(method,params){
  params._meta={...meta(),...params._meta};
  const headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','Accept':'application/json, text/event-stream','MCP-Protocol-Version':'2026-07-28','Mcp-Method':method};
  if(params.name)headers['Mcp-Name']=params.name;
  const response=await fetch(issuer+'/mcp',{method:'POST',headers,body:JSON.stringify({jsonrpc:'2.0',id:crypto.randomUUID(),method,params})});
  const body=await response.json();if(!response.ok||body.error)throw new Error(body.error?.message||'Authorization rejected');return body.result;
 }
 const zh=()=>document.documentElement.lang.startsWith('zh');
 const label=(cn,en)=>zh()?cn:en;
 function operationSummary(value){
  let panel=box.querySelector('[data-operation-summary]');if(!panel){panel=document.createElement('p');panel.dataset.operationSummary='';panel.setAttribute('role','status');output.before(panel)}
  const facts=[];
  if(value&&typeof value==='object'){
   if(value.state)facts.push(label('操作状态：','Operation state: ')+String(value.state));
   if(value.state==='committed')facts.push(label('原生操作已提交；服务健康需独立确认','Native operation committed; assess service health independently'));
   if(value.application_health==='not-assessed'||value.service_health==='not-observed')facts.push(label('尚无服务健康观测','Service health has not been observed'));
   if(value.global_atomicity===false)facts.push(label('逐步恢复，无全局原子性保证','Recoverable steps; no global atomicity guarantee'));
   if(value.native_signature_verified===true)facts.push(label('原生签名验证通过','Native signature verified'));
   if(value.installation_authorized===false)facts.push(label('尚未授权安装','Installation is not authorized'));
   if(value.execution_authorized===false)facts.push(label('尚未授权执行','Execution is not authorized'));
   if(value.schema==='ziokt.upload.v1')facts.push(label('已持久化分块：','Durable chunks: ')+value.received_chunks+'/'+value.total_chunks);
   if(value.status==='local-bridge-reachable')facts.push(label('本地桥可访问；原生运行状态尚未观测','Local bridge reachable; native runtime has not been observed'));
  }
  panel.textContent=facts.join(' · ');
 }
 function installObjectUploader(){
  if(box.querySelector('[data-object-uploader]'))return;
  const names=new Set(tools.map(tool=>tool.name));
  const prefixes=tools.filter(tool=>tool.name.endsWith('_object_begin')).map(tool=>tool.name.slice(0,-13)).filter(prefix=>['status','chunk_put','finish'].every(suffix=>names.has(prefix+'_object_'+suffix)));
  if(!prefixes.length)return;
  const detail=document.createElement('details');detail.dataset.objectUploader='';const title=document.createElement('summary');title.textContent=label('可恢复文件上传','Resumable file upload');detail.append(title);
  const uploadForm=document.createElement('form'),target=document.createElement('select'),file=document.createElement('input'),expected=document.createElement('input'),submit=document.createElement('button'),pause=document.createElement('button'),progress=document.createElement('progress'),report=document.createElement('p');
  for(const prefix of prefixes)target.add(new Option(prefix,prefix));file.type='file';file.required=true;expected.required=true;expected.pattern='sha256:[a-f0-9]{64}';expected.placeholder='sha256:…';
  submit.textContent=label('上传或继续','Upload or resume');pause.textContent=label('暂停','Pause');pause.type='button';pause.disabled=true;report.setAttribute('role','status');progress.max=1;progress.value=0;
  for(const [input,text] of [[target,label('目标组件','Target component')],[file,label('文件（最多 512 MiB）','File (up to 512 MiB)')],[expected,label('预期 SHA-256 摘要','Expected SHA-256 digest')]]){const wrapper=document.createElement('label');wrapper.textContent=text;wrapper.append(input);uploadForm.append(wrapper)}
  uploadForm.append(submit,pause,progress,report);detail.append(uploadForm);form.after(detail);
  let paused=false;pause.onclick=()=>{paused=true;pause.disabled=true};
  async function invoke(prefix,method,params,key){const result=await rpc('tools/call',{name:prefix+'_object_'+method,arguments:{params},_meta:key?{'ziokt/idempotencyKey':key}:{}});if(result.isError)throw Error(result.content?.[0]?.text||'OBJECT_OPERATION_FAILED');return result.structuredContent}
  const hex=bytes=>Array.from(new Uint8Array(bytes),byte=>byte.toString(16).padStart(2,'0')).join('');
  uploadForm.onsubmit=async event=>{
   event.preventDefault();const source=file.files[0],prefix=target.value,sha=expected.value;if(!source||source.size>536870912||!/^sha256:[a-f0-9]{64}$/.test(sha))return;
   const storage='ziokt.upload/'+prefix+'/'+sha+'/'+source.size;let id=localStorage.getItem(storage);if(!id){id=crypto.randomUUID();localStorage.setItem(storage,id)}
   paused=false;submit.disabled=true;pause.disabled=false;target.disabled=true;file.disabled=true;expected.disabled=true;
   try{
    await invoke(prefix,'begin',{upload:id,size:source.size,digest:sha,ttl:86400},id+'-begin');const state=await invoke(prefix,'status',{upload:id});
    if(state.expired||state.state==='aborted'){localStorage.removeItem(storage);throw Error(label('上传已过期，请再次点击开始新上传','Upload expired; click again to start a new upload'));}
    progress.max=source.size||1;progress.value=Math.min(source.size,state.next_missing*16384);
    for(let index=state.next_missing;index<state.total_chunks;index++){
     if(paused){report.textContent=label('已暂停，可重新选择同一文件继续','Paused; select the same file to resume');return}
     const bytes=new Uint8Array(await source.slice(index*16384,(index+1)*16384).arrayBuffer());let binary='';for(const byte of bytes)binary+=String.fromCharCode(byte);
     await invoke(prefix,'chunk_put',{upload:id,position:index,digest:'sha256:'+hex(await crypto.subtle.digest('SHA-256',bytes)),data_base64:btoa(binary)},id+'-chunk-'+index);
     progress.value=Math.min(source.size,(index+1)*16384);report.textContent=progress.value+' / '+source.size;
    }
    if(paused)return;
    const ref=await invoke(prefix,'finish',{upload:id},id+'-finish');operationSummary(ref);report.textContent=label('完整性验证完成：','Integrity verified: ')+ref.manifest_digest;output.textContent=JSON.stringify(ref,null,2);
   }catch(error){report.textContent=error.message}
   finally{submit.disabled=false;pause.disabled=true;target.disabled=false;file.disabled=false;expected.disabled=false}
  };
 }
 async function load(){
  if(!token)return;
  try{
   tools=(await rpc('tools/list',{})).tools.filter(t=>box.dataset.component==='gateway'?t.name.startsWith('gateway_')||t.name.startsWith('ziokt_'):t.name.startsWith(box.dataset.component+'_')||t.name.startsWith('ziokt_'));
   select.replaceChildren(...tools.map(t=>new Option(t.name,t.name)));form.hidden=false;disconnect.hidden=false;connect.hidden=true;select.dispatchEvent(new Event('change'));installObjectUploader();
  }catch(error){output.textContent=error.message;sessionStorage.removeItem('ziokt_mcp_access');token=null;}
 }
 connect.onclick=async()=>{
  connect.disabled=true;try{
  const verifier=b64(crypto.getRandomValues(new Uint8Array(48))),state=b64(crypto.getRandomValues(new Uint8Array(32)));
  sessionStorage.setItem('ziokt_oauth_verifier',verifier);sessionStorage.setItem('ziokt_oauth_state',state);sessionStorage.setItem('ziokt_oauth_return',location.pathname+location.search);
  const challenge=b64(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(verifier)));
  const metadata=await fetch('/.well-known/oauth-protected-resource/mcp').then(r=>r.json());
  issuer=new URL(metadata.resource).origin;resource=issuer+'/mcp';
  if(metadata.resource!==resource||metadata.authorization_servers?.[0]!==issuer||(!issuer.startsWith('https://')&&!issuer.startsWith('http://127.0.0.1:')))throw new Error('Issuer mismatch');
  sessionStorage.setItem('ziokt_oauth_issuer',issuer);
  if(!Array.isArray(metadata.browser_scopes_supported)||!metadata.browser_scopes_supported.length)throw new Error('Browser OAuth client is not configured');
  location.assign(issuer+'/oauth/authorize?'+new URLSearchParams({client_id:'ziokt-browser',redirect_uri:location.origin+'/gateway-assets/oauth-callback.html',response_type:'code',code_challenge:challenge,code_challenge_method:'S256',scope:metadata.browser_scopes_supported.join(' '),state,resource}));
  }catch(error){output.textContent=error.message;}finally{connect.disabled=false;}
 };
 disconnect.onclick=async()=>{
  try{await fetch(issuer+'/oauth/revoke',{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({token})});}finally{sessionStorage.removeItem('ziokt_mcp_access');token=null;form.hidden=true;disconnect.hidden=true;connect.hidden=false;box.querySelector('[data-object-uploader]')?.remove();output.textContent='';}
 };
 select.onchange=()=>{
  const tool=tools.find(t=>t.name===select.value);if(!tool)return;document.querySelector('#mcp-description').textContent=tool.description;
  const fields=tool.inputSchema.properties;const args={};for(const key of tool.inputSchema.required||[]){const field=fields[key];args[key]=key==='idempotency_key'?crypto.randomUUID():'const' in field?field.const:field.type==='object'?{}:field.type==='integer'?field.minimum||1:field.type==='boolean'?false:'';}
  document.querySelector('#mcp-arguments').value=JSON.stringify(args,null,2);
 };
 form.onsubmit=async event=>{
  event.preventDefault();const button=form.querySelector('button');const tool=tools.find(t=>t.name===select.value);
  try{
   const args=JSON.parse(document.querySelector('#mcp-arguments').value);
   if(!tool.annotations.readOnlyHint&&!confirm(document.documentElement.lang.startsWith('zh')?'执行此写入操作？':'Apply this write operation?'))return;
   button.disabled=true;
   const request={name:tool.name,arguments:args,_meta:{'ziokt/idempotencyKey':args.idempotency_key||crypto.randomUUID()}};
   // Reuse the exact key on network retry: uncertain writes must not execute twice.
   let result;try{result=await rpc('tools/call',request);}catch(error){if(error instanceof TypeError)result=await rpc('tools/call',request);else throw error;}
   operationSummary(result.structuredContent);output.textContent=JSON.stringify(result.structuredContent||result.content,null,2);
  }catch(error){output.textContent=error.message;}finally{button.disabled=false;}
 };
 const streamForm=document.querySelector('#stream-form');
 if(streamForm)streamForm.onsubmit=event=>{event.preventDefault();const root=streamForm.elements.root.value;if(!/^[a-f0-9]{64}$/.test(root))return;const player=document.querySelector('#stream-player');player.src='/stream/'+root;player.hidden=false;const link=document.querySelector('#stream-download');link.href='/stream/'+root;link.hidden=false;};
 await load();
})();
