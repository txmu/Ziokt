'use strict';
const apps={
 forum:{name:'论坛',description:'发起讨论、回复帖子，保存可验证的社区历史。',fields:{title:'标题',text:'正文',reply_to:'回复内容标识（可留空）'}},
 chat:{name:'聊天',description:'社区成员共享频道。单独的私密群组应使用独立社区密钥。',fields:{channel:'频道',text:'消息'}},
 wiki:{name:'Wiki',description:'共同维护文档；并发版本会保留，合并时引用全部当前版本。',fields:{title:'文档标题',text:'文档内容'}},
 files:{name:'文件',description:'加密分块保存文件，副本可独立恢复原始内容。',fields:{name:'文件名称'}},
 packages:{name:'软件仓库',description:'发布原生签名的软件材料。安装和激活仍需原生系统验包。',fields:{name:'软件名称',version:'版本',native_kind:'原生软件类型',native_signature:'原生签名或签名材料引用'}},
 mail:{name:'私信',description:'使用收件人独立的信箱密钥加密。其他社区成员不能用社区密钥解密正文。',fields:{recipient:'收件人身份公钥',mailbox:'收件人信箱公钥',subject:'主题',text:'正文'}},
 names:{name:'命名',description:'为社区内容和服务保存签名名称映射。',fields:{target:'目标内容或服务引用'}},
 governance:{name:'社区自治',description:'保存签名提案和投票。系统操作需要另行审查与授权。',fields:{proposal:'提案内容或提案标识',choice:'提案类型（propose）'}},
 identity:{name:'成员身份',description:'发布可携带的社区身份。名字由签名声明，权限来自成员策略。',fields:{name:'显示名称',public_key:'身份公钥',mailbox_public:'信箱公钥'}},
 hosting:{name:'应用托管',description:'记录服务、部署计划与内容材料。使用原生工作流审查并执行部署。',fields:{service:'原生服务名称',workflow_digest:'已审查部署计划摘要',content:'内容材料引用'}},
 compute:{name:'计算任务',description:'记录经过授权的原生作业及其结果材料。',fields:{job:'任务名称',workflow_digest:'已审查任务计划摘要',result:'结果材料引用'}}
};
let token='',domain='forum',state=null,status=null;
const $=id=>document.getElementById(id);
const node=(tag,text)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;return el;};
async function api(path,data,binary=false){
 const headers={'Authorization':'Bearer '+token};if(data!==undefined)headers['Content-Type']='application/json';
 const response=await fetch(path,{method:data===undefined?'GET':'POST',headers,body:data===undefined?undefined:JSON.stringify(data),cache:'no-store'});
 if(!response.ok){let result;try{result=await response.json();}catch{result={error:'连接失败'};}throw Error(result.error||'请求失败');}
 return binary?response.blob():response.json();
}
function feedback(message,error=false){$('feedback').textContent=message;$('feedback').className=error?'error':'';}
function download(blob,name){const url=URL.createObjectURL(blob);const a=node('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function fields(){
 $('fields').replaceChildren();
 for(const [key,label] of Object.entries(apps[domain].fields)){
  const lab=node('label',label);lab.htmlFor='field-'+key;
  const input=node(key==='text'?'textarea':'input');input.id='field-'+key;input.name=key;input.required=key!=='reply_to'&&key!=='mailbox';
  if(key==='text')input.maxLength=1800;else input.maxLength=256;
  if(domain==='governance'&&key==='choice'){input.value='propose';input.readOnly=true;}if(domain==='identity'&&key==='public_key')input.value=status.public_key;if(domain==='identity'&&key==='mailbox_public')input.value=status.mailbox_public||'';
  $('fields').append(lab,input);
 }
 if(domain==='files'||domain==='packages'){
  const lab=node('label','上传文件（最多 8 MiB）');lab.htmlFor='upload';const input=node('input');input.type='file';input.id='upload';input.required=true;$('fields').append(lab,input);
 }
 $('compose').hidden=!status.rights.includes(domain);
}
function render(){
 $('content').replaceChildren();
 const heads=new Set(state.heads);
 const events=state.events.filter(e=>heads.has(e.id)&&!e.deleted);
 if(!events.length)$('content').append(node('p','这里还没有内容。你可以发布第一条内容。'));
 for(const event of events){
  const card=node('article');card.append(node('h2',event.body.title||event.body.name||event.body.channel||event.key));
  const meta=node('p',event.key+' · '+event.author.slice(0,12));meta.className='meta';card.append(meta);
  if(state.conflicts[event.key]){const badge=node('p','存在并发版本，请查看后合并');badge.className='badge';card.append(badge);}
  if(domain==='mail'){
   card.append(node('p','收件人：'+event.body.to.slice(0,16)));
   if(status.mailbox&&event.body.to===status.public_key){const open=node('button','解密私信');open.type='button';open.onclick=async()=>{open.disabled=true;try{const mail=await api('/api/mail-open',event.body);card.append(node('h3',mail.subject),node('pre',mail.text));open.remove();}catch(error){feedback(error.message,true);open.disabled=false;}};card.append(open);}
  }else{
   for(const [key,value] of Object.entries(event.body)){if(key==='chunks'||key==='size'||key==='digest')continue;card.append(node('p',(apps[domain].fields[key]||key)+'：'),node('pre',typeof value==='string'?value:JSON.stringify(value)));}
  }
  const actions=node('div');actions.className='actions';
  if(domain==='files'||domain==='packages'){const button=node('button','下载文件');button.onclick=async()=>{button.disabled=true;try{download(await api('/api/file-get',event.body,true),event.body.name);}catch(error){feedback(error.message,true);}finally{button.disabled=false;}};actions.append(button);}
  if(domain==='governance'&&event.body.choice==='propose'){for(const [choice,label] of [['yes','赞成'],['no','反对'],['abstain','弃权']]){const vote=node('button',label);vote.onclick=async()=>{vote.disabled=true;try{const result=await api('/api/vote',{proposal:event.key,choice});feedback('投票已签名保存：'+JSON.stringify(result.tally.votes));await select(domain);}catch(error){feedback(error.message,true);}finally{vote.disabled=false;}};actions.append(vote);}}
  if(status.rights.includes('moderate')){const remove=node('button','删除标记');remove.onclick=async()=>{if(!window.confirm('为这条内容添加删除标记？已有副本和历史仍会保留。'))return;remove.disabled=true;try{await api('/api/publish',{domain,key:event.key,body:{reason:'community moderation'},parents:null,deleted:true});await select(domain);}catch(error){feedback(error.message,true);remove.disabled=false;}};actions.append(remove);}
  if(status.rights.includes(domain)){const edit=node('button','引用 / 更新');edit.onclick=()=>{$('object-key').value=event.key;for(const key of Object.keys(apps[domain].fields)){const input=$('field-'+key);if(typeof event.body[key]==='string')input.value=event.body[key];}$('compose').scrollIntoView({behavior:'auto'});$('object-key').focus();};actions.append(edit);}
  card.append(actions);$('content').append(card);
 }
}
async function select(next){domain=next;feedback('正在读取本地副本…');$('title').textContent=apps[domain].name;$('description').textContent=apps[domain].description;
 for(const button of $('navigation').querySelectorAll('button'))button.setAttribute('aria-current',button.dataset.domain===domain?'page':'false');
 fields();$('object-key').value=domain==='identity'?status.public_key:'';state=await api('/api/view?domain='+encodeURIComponent(domain));render();feedback('本地内容已加载');
}
$('session').onsubmit=async event=>{event.preventDefault();const button=event.submitter;button.disabled=true;token=$('token').value;
 try{status=await api('/api/status');$('login').hidden=true;$('workspace').hidden=false;$('status').textContent=status.community_id+' · '+status.privacy;
 for(const [key,app] of Object.entries(apps)){const button=node('button',app.name);button.dataset.domain=key;button.onclick=()=>select(key).catch(error=>feedback(error.message,true));$('navigation').append(button);}
 if(status.network_sync_available){const sync=node('button','同步网络副本');sync.onclick=async()=>{sync.disabled=true;feedback('正在通过已批准路径同步…');try{await api('/api/sync',{});await select(domain);feedback('网络副本已验证并同步');}catch(error){feedback(error.message,true);}finally{sync.disabled=false;}};$('navigation').append(sync);}
 const recovery=node('button','导出恢复包');recovery.onclick=async()=>{recovery.disabled=true;try{download(await api('/api/checkpoint',{},true),'community-recovery.bin');feedback('加密恢复包已导出，请与密钥分开保存。');}catch(error){feedback(error.message,true);}finally{recovery.disabled=false;}};$('navigation').append(recovery);await select(domain);
 }catch(error){$('login').append(node('p',error.message));}finally{button.disabled=false;}
};
$('refresh').onclick=()=>select(domain).catch(error=>feedback(error.message,true));
$('publish').onsubmit=async event=>{event.preventDefault();$('submit').disabled=true;feedback('正在签名保存…');
 try{
 const body={};for(const key of Object.keys(apps[domain].fields))body[key]=$('field-'+key).value;
 if(domain==='files'||domain==='packages'){const file=$('upload').files[0];if(!file||file.size>8388608)throw Error('请选择最多 8 MiB 的文件');const response=await fetch('/api/file-upload',{method:'POST',headers:{'Authorization':'Bearer '+token,'Content-Type':'application/octet-stream'},body:file});const result=await response.json();if(!response.ok)throw Error(result.error||'上传失败');Object.assign(body,result);}
 const key=$('object-key').value;
 if(domain==='mail')await api('/api/mail-send',{...body,key});
 else await api('/api/publish',{domain,key,body,parents:null,deleted:false});
 await select(domain);feedback('内容已签名保存。网络副本将在显式同步后获得此内容。');
 }catch(error){feedback(error.message,true);}finally{$('submit').disabled=false;}
};
