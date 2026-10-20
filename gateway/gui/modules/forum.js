/* Native forum readers and publishers. No seeded posts or fabricated proofs. */
import {State,callTool,showConfirm} from '../core.js';

export function renderForum(container){
 const en=State.language==='en',tr=(zh,english)=>en?english:zh;
 const make=(tag,text)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;};
 container.replaceChildren();container.append(make('h2',tr('社区论坛','Community forums')));
 container.append(make('p',tr('选择原生论坛。身份、文章标识、签名和保留策略各自独立，发布成功仅表示对应原生节点接纳。','Choose a native forum. Identities, article IDs, proofs and retention remain independent. Publication confirms acceptance by that native node.')));
 const status=make('p');status.id='native-forum-status';status.setAttribute('role','status');container.append(status);
 const label=make('label',tr('论坛来源','Forum source')),source=make('select');source.id='native-forum-source';
 for(const [value,text] of [['community','Ziokt Community'],['corium','Gateway / Corium'],['etp','ETP Forum v2']]){const option=make('option',text);option.value=value;source.append(option);}label.append(source);container.append(label);
 const list=make('section');list.id='native-forum-list';list.setAttribute('aria-live','polite');container.append(list);
 function field(parent,text,id,multiline=false){const label=make('label',text),input=make(multiline?'textarea':'input');input.id=id;if(!multiline)input.type='text';label.append(input);parent.append(label);return input;}
 const lookup=make('section');lookup.className='card';lookup.append(make('h3',tr('ETP 原生文章','ETP native article')));const identifier=field(lookup,tr('文章 ID（64位十六进制）','Article ID (64 hexadecimal characters)'),'native-forum-id');container.append(lookup);
 const publishing=make('section');publishing.className='card';publishing.append(make('h3',tr('发布 / 回复','Publish / reply')));
 const title=field(publishing,tr('标题','Title'),'native-forum-title'),body=field(publishing,tr('正文','Body'),'native-forum-body',true),topic=field(publishing,tr('ETP 主题','ETP topic'),'native-forum-topic'),identity=field(publishing,tr('ETP 已配置身份名称（留空表示匿名）','ETP configured identity name (blank means anonymous)'),'native-forum-identity');title.maxLength=512;body.maxLength=32000;topic.value='general';
 const reply=make('p');publishing.append(reply);container.append(publishing);let parent=null;
 async function run(button,operation){button.disabled=true;status.textContent=tr('正在请求原生服务…','Contacting native service…');try{await operation();}catch(error){status.textContent=error.message;}finally{button.disabled=false;}}
 function action(parent,text,operation,id){const button=make('button',text);button.className='btn btn-primary';if(id)button.id=id;button.onclick=()=>run(button,operation);parent.append(button);return button;}
 function selectReply(id){parent=id;reply.textContent=tr('回复：','Reply to: ')+id;body.focus();}
 function postCard(record){const card=make('article');card.className='card';card.append(make('h3',record.title||record.id),make('p',record.author||tr('匿名','Anonymous')));
  if(record.text!==undefined){const text=make('pre',record.text);text.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere;font:inherit';card.append(text);}
  card.append(make('small',tr('原生标识：','Native ID: ')+record.id));
  if(record.proof){const details=make('details');details.append(make('summary',tr('原始来源证明','Original source proof')));const proof=make('pre',JSON.stringify(record.proof,null,2));proof.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere';details.append(proof);card.append(details);}
  if(source.value!=='corium')action(card,tr('回复','Reply'),async()=>selectReply(record.id));list.append(card);
 }
 async function load(){list.replaceChildren();
  if(source.value==='etp'){status.textContent=tr('按原生文章ID读取，或选择主题发布。此节点未提供主题目录接口。','Read by native article ID or publish to a topic. This node has no topic listing operation.');return;}
  if(source.value==='community'){const page=await callTool('community_forum_list',{limit:30,offset:0});for(const event of page.items)if(!event.deleted)postCard({id:event.native_id,title:event.body.title,text:event.body.text,author:event.author,proof:event.proof});}
  else {const page=await callTool('gateway_forum_list',{limit:50});for(const item of page.topics)postCard({id:item.id,title:item.title,author:item.author});}
  status.textContent=tr('已从原生服务读取 ','Loaded from native service: ')+list.children.length;
 }
 const refresh=action(container,tr('读取论坛','Load forum'),load,'native-forum-load');
 action(lookup,tr('读取文章','Read article'),async()=>{if(!/^[a-f0-9]{64}$/i.test(identifier.value))throw Error(tr('文章ID格式不正确','Invalid article ID'));const result=await callTool('etp_etp_forum_get',{params:{id:identifier.value}});if(!result.post)throw Error(tr('原生节点没有这篇文章','Article absent from native node'));const article=result.post,parts=article.content_base64.map(value=>Uint8Array.from(atob(value),character=>character.charCodeAt(0))),length=parts.reduce((sum,part)=>sum+part.length,0),bytes=new Uint8Array(length);let offset=0;for(const part of parts){bytes.set(part,offset);offset+=part.length;}list.replaceChildren();postCard({id:article.id,text:new TextDecoder().decode(bytes),author:article.author_id,proof:{signature_base64:article.signature_base64,parent_id:article.parent_id,topic_hash:article.topic_hash}});status.textContent=tr('已读取原生文章与来源字段','Native article and source fields received');},'native-forum-read');
 action(publishing,tr('提交原生论坛','Submit to native forum'),async()=>{
  const selected=source.value;
  if(!['community','etp'].includes(selected))throw Error(tr('请选择可发布的原生论坛','Choose a writable native forum'));
  if(!body.value.trim()||!title.value.trim())throw Error(tr('请填写标题和正文','Title and body required'));
  if(!await showConfirm(tr('发布文章','Publish article'),tr('将以当前授权的原生身份发布到所选论坛，保留其原生权限和传播策略。','Publish to the selected forum using the authorized native identity and its permission and propagation policy.')))return;
  let result;
  if(selected==='community')result=await callTool('community_forum_post',{title:title.value,body:body.value,operation:crypto.randomUUID(),...(parent?{reply_to:parent}:{})},{confirm:true});
  else result=await callTool('etp_etp_forum_publish',{params:{topic:topic.value,content:title.value+'\n\n'+body.value,author:identity.value.trim()||null,parent_id:parent}},{confirm:true});
  status.textContent=tr('原生节点已接纳：','Accepted by native node: ')+(result.id||'');body.value='';parent=null;reply.textContent='';
 },'native-forum-publish');
 function switchSource(){parent=null;reply.textContent='';list.replaceChildren();lookup.hidden=source.value!=='etp';topic.parentElement.hidden=source.value!=='etp';identity.parentElement.hidden=source.value!=='etp';publishing.hidden=source.value==='corium';status.textContent=tr('点击读取以请求原生数据；需要节点授权。','Choose Load to request native data; node authorization is required.');}
 source.onchange=switchSource;switchSource();
 const native=make('a',tr('打开 Corium 原生社区门户','Open Corium native community portal'));native.href='https://cor-web.ziokt.com/';native.target='_blank';native.rel='noopener noreferrer';native.className='btn btn-secondary';container.append(native);
}
