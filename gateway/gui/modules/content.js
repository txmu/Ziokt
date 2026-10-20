// Content applications use the same scoped MCP dispatcher as the existing GUI.
import { callTool, sha256 } from '../core.js';

function contentElement(tag,text){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;return el;}
function contentField(form,label,name,type='text'){const wrap=contentElement('label',label),input=contentElement(type==='textarea'?'textarea':'input');input.name=name;if(type!=='textarea')input.type=type;input.required=true;input.style.cssText='display:block;width:100%;min-height:44px;margin:8px 0 16px;padding:10px;background:var(--bg-panel);color:var(--text-main);border:1px solid var(--border-subtle)';wrap.append(input);form.append(wrap);return input;}
function contentAction(label,fn,status){const button=contentElement('button',label);button.className='btn btn-primary';button.style.cssText='min-height:44px;margin:8px 8px 8px 0';button.onclick=async()=>{button.disabled=true;try{await fn();}catch(error){status.textContent=error.message;}finally{button.disabled=false;}};return button;}
async function contentTool(operation,args={},write=false){return callTool(operation.replaceAll('.','_'),args,{confirm:write});}

export function renderLibrary(container){
  container.replaceChildren();container.append(contentElement('h1','Ziokt Library'));
  const headerBar = contentElement('div');
  headerBar.style.cssText = 'display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;margin-bottom:12px';
  const status=contentElement('p','支持只读检索与阅读，或使用节点授权的 Library 账户管理与上传藏书。');status.setAttribute('role','status');
  const extLink = contentElement('a','📖 打开独立阅读器 (read.ziokt.com) →');
  extLink.href = 'https://read.ziokt.com/';
  extLink.target = '_blank';
  extLink.className = 'btn btn-secondary';
  extLink.style.cssText = 'padding:6px 12px;font-size:0.9rem;text-decoration:none';
  headerBar.append(status, extLink);
  container.append(headerBar);
  const searchForm=contentElement('div'),query=contentField(searchForm,'搜索书名、作者、ISBN','query','search');query.required=false;
  const results=contentElement('section');results.style.cssText='display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:16px';
  const reader=contentElement('section');reader.hidden=true;
  async function show(book){
    reader.hidden=false;reader.replaceChildren(contentElement('h2',book.title));
    const info=await contentTool('content.object.info',{id:book.file_id});
    if(info.size>16*1024*1024)throw Error('此文件超过浏览器阅读预算，请使用流式客户端下载。');
    const parts=[];for(let position=0;position<Math.ceil(info.size/16384);position++){const part=await contentTool('content.object.get',{id:book.file_id,position});parts.push(Uint8Array.from(atob(part.data),c=>c.charCodeAt(0)));}
    const blob=new Blob(parts),bytes=await blob.arrayBuffer();if(await sha256(bytes)!==info.digest)throw Error('文件完整性校验失败');
    if(['text/plain','text/markdown','text/html'].includes(info.mime)){const text=contentElement('pre',new TextDecoder().decode(bytes));text.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere;max-height:60vh;overflow:auto;font:inherit';text.tabIndex=0;reader.append(text);try{const state=await contentTool('library.reading.get',{id:book.id});text.scrollTop=state?.settings?.scroll||0;}catch(_){}reader.append(contentAction('保存阅读位置',async()=>{await contentTool('library.reading.save',{id:book.id,state:{scroll:text.scrollTop}},true);status.textContent='阅读位置已保存';},status));}
    else reader.append(contentElement('p','此格式请下载后使用相应阅读器打开。'));
    const link=contentElement('a','下载已校验文件');link.href=URL.createObjectURL(blob);link.download=book.title;link.onclick=()=>setTimeout(()=>URL.revokeObjectURL(link.href),60000);reader.append(link);
  }
  async function downloadBook(book){status.textContent='正在下载 '+book.title+'…';const info=await contentTool('content.object.info',{id:book.file_id});if(info.size>16*1024*1024)throw Error('此文件超过浏览器下载预算，请使用流式客户端下载。');const parts=[];for(let position=0;position<Math.ceil(info.size/16384);position++){const part=await contentTool('content.object.get',{id:book.file_id,position});parts.push(Uint8Array.from(atob(part.data),c=>c.charCodeAt(0)));}const blob=new Blob(parts),bytes=await blob.arrayBuffer();if(await sha256(bytes)!==info.digest)throw Error('文件完整性校验失败');const link=contentElement('a','保存 '+book.title);link.href=URL.createObjectURL(blob);link.download=book.title;link.onclick=()=>setTimeout(()=>URL.revokeObjectURL(link.href),60000);document.body.append(link);link.click();link.remove();status.textContent='文件校验通过并已下载';}
  async function load(){results.replaceChildren();const data=await contentTool('library.search',{query:query.value,limit:30,offset:0});for(const book of data.items){const card=contentElement('article');card.style.cssText='padding:20px;border:1px solid var(--border-subtle);border-radius:8px';card.append(contentElement('h2',book.title),contentElement('p',(book.authors||[]).join(' · ')),contentElement('p',book.visibility==='private'?'私人藏书':'公开馆藏'),contentElement('small',book.local?'本地来源':'联邦目录，下载可用性需实际验证'),contentAction('阅读',()=>show(book),status),contentAction('下载',()=>downloadBook(book),status));results.append(card);}status.textContent=`找到 ${data.items.length} 本书`;
  }
  searchForm.append(contentAction('搜索',load,status));container.append(searchForm,results,reader);
  const details=contentElement('details'),summary=contentElement('summary','上传与出版');details.append(summary);const form=contentElement('div');details.append(form);container.append(details);
  const file=contentField(form,'文件（浏览器上限 16 MiB）','file','file'),title=contentField(form,'书名','title'),author=contentField(form,'作者','author'),work=contentField(form,'作品标识','work'),edition=contentField(form,'版本标识','edition'),license=contentField(form,'许可证 / 保存权声明','license');
  const visibility=contentElement('select');visibility.setAttribute('aria-label','传播范围');for(const [value,label] of [['private','私人藏书'],['public','公开分发（确认有传播权）']]){const option=contentElement('option',label);option.value=value;visibility.append(option);}form.append(visibility);
  const progress=contentElement('progress');progress.max=100;progress.value=0;progress.setAttribute('aria-label','上传进度');form.append(progress);
  form.append(contentAction('上传并保存书目',async()=>{const selected=file.files[0];if(!selected||!title.value||!work.value||!edition.value||!license.value)throw Error('请填写文件、书名、作品、版本和权利声明');if(selected.size>16*1024*1024)throw Error('浏览器上限 16 MiB，大文件请使用流式客户端');const upload=crypto.randomUUID(),digest=await sha256(await selected.arrayBuffer());await contentTool('content.upload.begin',{upload,size:selected.size,digest,mime:selected.type||'application/octet-stream'},true);for(let position=0,start=0;start<selected.size;position++,start+=16384){const bytes=new Uint8Array(await selected.slice(start,start+16384).arrayBuffer());let raw='';for(const b of bytes)raw+=String.fromCharCode(b);await contentTool('content.upload.put',{upload,position,data:btoa(raw)},true);progress.value=Math.min(100,(start+16384)/selected.size*100);}const object=await contentTool('content.upload.finish',{upload},true);await contentTool('library.publish',{metadata:{title:title.value,authors:[author.value],work_id:work.value,edition_id:edition.value,license:license.value,visibility:visibility.value,file_id:object.id}},true);progress.value=100;status.textContent='已保存';await load();},status));
  load().catch(()=>{});
}

export function renderNetnews(container){
  container.replaceChildren();container.append(contentElement('h1','Ziokt Netnews'));
  const headerBar = contentElement('div');
  headerBar.style.cssText = 'display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;margin-bottom:12px';
  const status=contentElement('p','支持只读浏览公开新闻组与文章，发布需经由授权 MCP 账户。');status.setAttribute('role','status');
  const extLink = contentElement('a','📰 打开独立新闻组与订阅 (read.ziokt.com) →');
  extLink.href = 'https://read.ziokt.com/';
  extLink.target = '_blank';
  extLink.className = 'btn btn-secondary';
  extLink.style.cssText = 'padding:6px 12px;font-size:0.9rem;text-decoration:none';
  headerBar.append(status, extLink);
  container.append(headerBar);
  const layout=contentElement('div');layout.style.cssText='display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:16px';const groups=contentElement('aside'),list=contentElement('section'),article=contentElement('article');layout.append(groups,list,article);container.append(layout);
  let selected='',refs=[];
  const posting=contentElement('details');posting.open=true;posting.append(contentElement('summary','发布 / 回复'));const form=contentElement('div');posting.append(form);container.append(posting);const groupField=contentField(form,'新闻组','group'),subject=contentField(form,'标题','subject'),body=contentField(form,'正文','body','textarea');
  async function loadArticles(name){selected=name;groupField.value=name;list.replaceChildren(contentElement('h2',name));list.append(contentAction('订阅',async()=>{await contentTool('content.subscription.save',{kind:'newsgroup',target:name,settings:{body:true,attachments:false}},true);status.textContent='订阅偏好已保存';},status));const data=await contentTool('netnews.articles',{group:name,low:1,limit:100});for(const item of data.items)list.append(contentAction(item.number+' · '+item.subject,async()=>{article.replaceChildren(contentElement('h2',item.subject),contentElement('p',item.from+' · '+item.date));const text=contentElement('pre',item.body);text.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere;font:inherit';article.append(text,contentAction('回复',()=>{refs=[...(item.references||[]),item.message_id].slice(-32);subject.value='Re: '+item.subject;body.focus();},status));},status));}
  async function loadGroups(){groups.replaceChildren(contentElement('h2','新闻组'));const data=await contentTool('netnews.groups');for(const group of data.items)groups.append(contentAction(group.name,()=>loadArticles(group.name),status));status.textContent=`${data.items.length} 个可见新闻组`;}
  container.insertBefore(contentAction('加载新闻组',loadGroups,status),layout);
  form.append(contentAction('发布',async()=>{if(!groupField.value||!subject.value||!body.value)throw Error('请填写新闻组、标题和正文');await contentTool('netnews.post',{groups:[groupField.value],subject:subject.value,body:body.value,references:refs},true);refs=[];body.value='';await loadArticles(groupField.value);status.textContent='文章已持久发布';},status));
  const create=contentElement('details');create.append(contentElement('summary','创建新闻组'));const fields=contentElement('div');const name=contentField(fields,'分层名称，例如 books.open','name');fields.append(contentAction('创建公开新闻组',async()=>{await contentTool('netnews.group.create',{name:name.value},true);await loadGroups();},status));create.append(fields);container.append(create);
  loadGroups().catch(()=>{});
}
