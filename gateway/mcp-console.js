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
 async function load(){
  if(!token)return;
  try{
   tools=(await rpc('tools/list',{})).tools.filter(t=>box.dataset.component==='gateway'?t.name.startsWith('gateway_')||t.name.startsWith('ziokt_'):t.name.startsWith(box.dataset.component+'_')||t.name.startsWith('ziokt_'));
   select.replaceChildren(...tools.map(t=>new Option(t.name,t.name)));form.hidden=false;disconnect.hidden=false;connect.hidden=true;select.dispatchEvent(new Event('change'));
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
  location.assign(issuer+'/oauth/authorize?'+new URLSearchParams({client_id:'ziokt-browser',redirect_uri:location.origin+'/gateway-assets/oauth-callback.html',response_type:'code',code_challenge:challenge,code_challenge_method:'S256',scope:metadata.scopes_supported.join(' '),state,resource}));
  }catch(error){output.textContent=error.message;}finally{connect.disabled=false;}
 };
 disconnect.onclick=async()=>{
  try{await fetch(issuer+'/oauth/revoke',{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({token})});}finally{sessionStorage.removeItem('ziokt_mcp_access');token=null;form.hidden=true;disconnect.hidden=true;connect.hidden=false;output.textContent='';}
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
   output.textContent=JSON.stringify(result.structuredContent||result.content,null,2);
  }catch(error){output.textContent=error.message;}finally{button.disabled=false;}
 };
 const streamForm=document.querySelector('#stream-form');
 if(streamForm)streamForm.onsubmit=event=>{event.preventDefault();const root=streamForm.elements.root.value;if(!/^[a-f0-9]{64}$/.test(root))return;const player=document.querySelector('#stream-player');player.src='/stream/'+root;player.hidden=false;const link=document.querySelector('#stream-download');link.href='/stream/'+root;link.hidden=false;};
 await load();
})();
