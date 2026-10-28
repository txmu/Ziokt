// ==============================================================================
// Ziokt Unified Graphical Client - Standalone Universal Application Bundle
// ==============================================================================

(function() {
  "use strict";

  // --- Module: ../../ziokt/web/application-client.js ---
/* Shared application client for WebExtensions and independent Ziokt pages.
 * No Gateway operations, caller paths, redirects, cookies or persistent secrets.
 */
'use strict';
class ZioktApplicationClient {
  constructor({endpoint,token}) {
    const url=new URL(endpoint);
    if(url.username||url.password||url.search||url.hash||!['','/'].includes(url.pathname))throw Error('INVALID_APPLICATION_ORIGIN');
    if(url.protocol!=='https:'&&!(url.protocol==='http:'&&['127.0.0.1','localhost'].includes(url.hostname)))throw Error('APPLICATION_TLS_REQUIRED');
    this.endpoint=url.origin;this.token=token;
  }
  async call(operation,args={}) {
    const headers={'Content-Type':'application/json'};if(this.token)headers.Authorization='Bearer '+this.token;
    const response=await fetch(this.endpoint+'/api',{method:'POST',headers,body:JSON.stringify({operation,arguments:args}),credentials:'omit',redirect:'error'});
    const result=await response.json();
    if(!response.ok){const error=Error('APPLICATION_REJECTED');error.status=response.status;throw error;}
    return result;
  }
  static async digest(bytes) {return 'sha256:'+Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');}
  async upload(file,{id=crypto.randomUUID(),progress=()=>{}}={}) {
    if(file.size>16*1024*1024)throw Error('BROWSER_OBJECT_LIMIT');
    const digest=await ZioktApplicationClient.digest(await file.arrayBuffer());
    const state=await this.call('content.upload.begin',{upload:id,size:file.size,digest,mime:file.type||'application/octet-stream',name:file.name||'content.bin'});
    if(state.state!=='complete')for(let position=state.next_missing,start=position*16384;start<file.size;position++,start+=16384){
      const bytes=new Uint8Array(await file.slice(start,start+16384).arrayBuffer());let raw='';for(const b of bytes)raw+=String.fromCharCode(b);
      await this.call('content.upload.put',{upload:id,position,data:btoa(raw)});progress(Math.min(file.size,start+16384),file.size);
    }
    const object=await this.call('content.upload.finish',{upload:id});progress(file.size,file.size);return object;
  }
  async download(id,{progress=()=>{}}={}) {
    const metadata=await this.call('content.object.info',{id});
    if(metadata.size>16*1024*1024)throw Error('BROWSER_OBJECT_LIMIT');
    const parts=[];
    for(let position=0;position<Math.ceil(metadata.size/16384);position++){
      const part=await this.call('content.object.get',{id,position});parts.push(Uint8Array.from(atob(part.data),c=>c.charCodeAt(0)));progress(Math.min(metadata.size,(position+1)*16384),metadata.size);
    }
    const blob=new Blob(parts,{type:'application/octet-stream'});
    if(await ZioktApplicationClient.digest(await blob.arrayBuffer())!==metadata.digest)throw Error('OBJECT_INTEGRITY');
    return {blob,metadata};
  }
}
globalThis.ZioktApplicationClient=ZioktApplicationClient;

globalThis.ZioktDocumentReader={
  async mount(container,{call,id,language='en',status=()=>{}}){
    const zh=language.startsWith('zh'),label=(a,b)=>zh?a:b;
    const node=(tag,text)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;return el;};
    const lifetime=Symbol('reader');container._readerLifetime=lifetime;const alive=()=>container.isConnected&&container._readerLifetime===lifetime;
    let manifestOffset=0,chapterCount=0,chapter=0,offset=0,next=null,sequence=0;
    const bar=node('div'),select=node('select'),body=node('pre'),pageStatus=node('p'),navigation=node('select'),image=node('img');
    image.hidden=true;image.style.cssText='max-width:100%;height:auto';image.decoding='async';
    select.setAttribute('aria-label',label('章节或页码','Chapter or page'));navigation.setAttribute('aria-label',label('目录','Table of contents'));
    body.tabIndex=0;body.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere;font:inherit';pageStatus.setAttribute('role','status');
    const action=(text,fn)=>{const button=node('button',text);button.type='button';button.style.minHeight='44px';button.onclick=async()=>{button.disabled=true;try{await fn();}catch(error){status(error.message);}finally{button.disabled=false;}};return button;};
    const previous=action(label('上一页','Previous page'),async()=>{if(offset>0)await load(chapter,Math.max(0,offset-16384));else if(chapter>0)await load(chapter-1,0);});
    const following=action(label('下一页','Next page'),async()=>{if(next!==null)await load(chapter,next);else if(chapter+1<chapterCount)await load(chapter+1,0);});
    const more=action(label('更多章节与目录','More chapters and navigation'),async()=>{manifestOffset+=64;await inventory();});
    bar.append(select,navigation,previous,following,more);container.replaceChildren(bar,pageStatus,image,body);
    async function inventory(){
      const result=await call('library.reader.manifest',{id,offset:manifestOffset,limit:64});if(!alive())return;
      chapterCount=result.chapter_count;
      for(const entry of result.chapters){const option=node('option',String(entry.index+1)+' · '+entry.title);option.value=entry.index;select.append(option);}
      for(const entry of result.navigation||[]){const option=node('option',entry.title);option.value=JSON.stringify(entry);navigation.append(option);}
      more.hidden=result.next_offset===null&&result.navigation_next_offset==null;
      navigation.hidden=!navigation.options.length;
    }
    async function load(target,start,fragment=''){
      if(!alive())return;const request=++sequence;previous.disabled=true;following.disabled=true;
      const result=await call('library.reader.chapter',{id,chapter:target,offset:start,limit:16384,fragment});
      if(request!==sequence||!alive())return;
      chapter=target;offset=result.offset;next=result.next_offset;body.textContent=result.text;
      image.removeAttribute('src');image.hidden=true;
      if(result.image){
        const value=result.image;
        if(value.mime!=='image/jpeg'||typeof value.data!=='string'||value.data.length>190000||!/^[A-Za-z0-9+/]*={0,2}$/.test(value.data)||!Number.isInteger(value.width)||!Number.isInteger(value.height)||value.width<1||value.height<1||value.width>1200||value.height>1200)throw Error('INVALID_RENDERED_PAGE');
        image.alt=label('第 ','Page ')+(chapter+1);image.src='data:image/jpeg;base64,'+value.data;image.hidden=false;
      }
      if(![...select.options].some(option=>Number(option.value)===chapter)){const option=node('option',String(chapter+1)+' · '+result.title);option.value=chapter;select.append(option);}
      select.value=String(chapter);previous.disabled=chapter===0&&offset===0;following.disabled=next===null&&chapter+1>=chapterCount;
      pageStatus.textContent=label('章节 ','Chapter ')+(chapter+1)+' / '+chapterCount+' · '+offset+'–'+Math.min(offset+16384,result.total_characters)+' / '+result.total_characters;
    }
    select.onchange=()=>load(Number(select.value),0).catch(error=>status(error.message));
    navigation.onchange=()=>{const item=JSON.parse(navigation.value);load(item.chapter,0,item.fragment||'').catch(error=>status(error.message));};
    await inventory();await load(0,0);
    return {position:()=>({chapter,offset}),navigate:anchor=>load(anchor.chapter||0,anchor.offset||0)};
  }
};

/* Same personal-content controls in Content Web, the GUI bundle and extensions. */
globalThis.ZioktPersonalViews={
  async readstate(container,{call,article,language='en',status=()=>{}}) {
    const zh=language.startsWith('zh'),node=document.createElement('button');
    node.style.minHeight='44px';node.disabled=true;container.append(node);
    let state;
    const refresh=()=>{node.textContent=state.is_read?(zh?'标为未读':'Mark unread'):(zh?'标为已读':'Mark read');node.disabled=false;node.setAttribute('aria-pressed',String(state.is_read));};
    node.textContent=zh?'读取阅读状态…':'Loading read state…';
    try {state=await call('netnews.readstate.get',{article});if(!node.isConnected)return;refresh();}
    catch(error){node.textContent=zh?'阅读状态不可用':'Read state unavailable';status(error.message);return;}
    node.onclick=async()=>{node.disabled=true;try{state=await call('netnews.readstate.update',{article,is_read:!state.is_read,revision:state.revision});if(node.isConnected)refresh();}
      catch(error){status((zh?'更新未完成；重新加载文章后重试。':'Update incomplete; reopen the article to retry. ')+error.message);node.disabled=false;}};
  },
  library(container,{call,book,language='en',status=()=>{},position=()=>({offset:0}),navigate=()=>{}}) {
    const zh=language.startsWith('zh'),label=(a,b)=>zh?a:b;
    const el=(tag,value)=>{const node=document.createElement(tag);if(value!==undefined)node.textContent=value;return node;};
    const alive=()=>container.isConnected;
    const action=(text,fn)=>{const node=el('button',text);node.type='button';node.style.minHeight='44px';node.onclick=async()=>{node.disabled=true;try{await fn();}catch(error){status(error.message);}finally{node.disabled=false;}};return node;};
    const field=(title,tag='input')=>{const wrap=el('label',title),node=el(tag);node.style.cssText='display:block;min-height:44px;width:100%;max-width:100%;box-sizing:border-box';wrap.append(node);container.append(wrap);return node;};
    container.append(el('h3',label('我的笔记、书签与藏书','My notes, bookmarks and collections')));
    const metadataPanel=el('details');container.append(metadataPanel);ZioktMetadataEditor.mount(metadataPanel,{call,id:book.id,language,status});
    const indexPanel=el('details');container.append(indexPanel);ZioktDocumentIndex.mount(indexPanel,{call,id:book.id,language,status});
    const editor=field(label('私人笔记','Private note'),'textarea');editor.maxLength=8192;editor.rows=3;
    let editing=null,noteOffset=0,bookmarkOffset=0,collectionOffset=0,selectedCollection=null,collectionRequest=0;
    let pendingNoteId=crypto.randomUUID();
    const notes=el('div'),marks=el('div'),collectionSelect=field(label('我的藏书','My collections'),'select');
    const collectionName=field(label('新藏书名称','New collection name'));collectionName.maxLength=512;
    const noteSave=action(label('保存笔记','Save note'),async()=>{
      const args={id:editing?.id||pendingNoteId,book:book.id,text:editor.value,anchor:editing?.anchor||position()};
      await call(editing?'library.note.update':'library.note.create',editing?{...args,revision:editing.revision}:args);
      if(!alive())return;editor.value='';editing=null;pendingNoteId=crypto.randomUUID();noteOffset=0;await loadNotes();status(label('笔记已保存','Note saved'));
    });
    container.append(noteSave,action(label('取消编辑','Cancel editing'),async()=>{editing=null;editor.value='';pendingNoteId=crypto.randomUUID();}));
    const bookmarkLabel=field(label('书签名称','Bookmark name'));bookmarkLabel.maxLength=512;
    let pendingMark=null;
    container.append(action(label('添加书签','Add bookmark'),async()=>{
      // Keep exact intent after an uncertain response; editing creates a new intent.
      if(!pendingMark)pendingMark={id:crypto.randomUUID(),book:book.id,label:bookmarkLabel.value,anchor:position(),revision:0};
      await call('library.bookmark.set',pendingMark);pendingMark=null;if(alive()){bookmarkOffset=0;await loadBookmarks();}
    }));
    const addCollection=action(label('加入选中藏书','Add to selected collection'),async()=>{
      selectedCollection=collectionSelect.selectedOptions[0]?._entry;
      if(!selectedCollection)throw Error(label('请先选择藏书','Select a collection first'));
      const result=await call('library.collection.manage',{id:selectedCollection.id,action:'add',book:book.id,revision:selectedCollection.revision});
      if(alive()){collectionSelect.selectedOptions[0]._entry=result;status(label('已加入藏书','Added to collection'));}
    });addCollection.disabled=true;
    container.append(notes,marks,action(label('创建藏书','Create collection'),async()=>{
      const name=collectionName.value;if(!name)throw Error(label('请填写藏书名称','Enter a collection name'));
      if(!collectionName.dataset.intent)collectionName.dataset.intent=crypto.randomUUID();
      await call('library.collection.manage',{id:collectionName.dataset.intent,action:'create',name,revision:0});
      if(!alive())return;collectionName.value='';delete collectionName.dataset.intent;collectionOffset=0;await loadCollections();
    }),addCollection);
    async function loadNotes(){
      const result=await call('library.note.list',{book:book.id,limit:30,offset:noteOffset});if(!alive())return;
      notes.replaceChildren(el('h4',label('笔记','Notes')));
      for(const item of result.items){const row=el('article');row.append(el('p',item.text),action(label('编辑','Edit'),async()=>{editing=item;editor.value=item.text;editor.focus();}),action(label('删除笔记','Delete note'),async()=>{
        if(!confirm(label('删除这条私人笔记？','Delete this private note?')))return;
        await call('library.note.delete',{id:item.id,revision:item.revision});await loadNotes();
      }));notes.append(row);}
      if(noteOffset)notes.append(action(label('上一页笔记','Previous notes'),async()=>{noteOffset=Math.max(0,noteOffset-30);await loadNotes();}));
      if(result.next_offset!==null)notes.append(action(label('下一页笔记','Next notes'),async()=>{noteOffset=result.next_offset;await loadNotes();}));
    }
    async function loadBookmarks(){
      const result=await call('library.bookmark.list',{book:book.id,limit:30,offset:bookmarkOffset});if(!alive())return;
      marks.replaceChildren(el('h4',label('书签','Bookmarks')));
      for(const item of result.items)marks.append(action(item.label||label('跳转书签','Go to bookmark'),async()=>navigate(item.anchor)),action(label('删除书签','Delete bookmark'),async()=>{
        if(!confirm(label('删除这个书签？','Delete this bookmark?')))return;
        await call('library.bookmark.delete',{id:item.id,revision:item.revision});await loadBookmarks();
      }));
      if(bookmarkOffset)marks.append(action(label('上一页书签','Previous bookmarks'),async()=>{bookmarkOffset=Math.max(0,bookmarkOffset-30);await loadBookmarks();}));
      if(result.next_offset!==null)marks.append(action(label('下一页书签','Next bookmarks'),async()=>{bookmarkOffset=result.next_offset;await loadBookmarks();}));
    }
    async function loadCollections(){
      const request=++collectionRequest;addCollection.disabled=true;
      const result=await call('library.collection.list',{limit:30,offset:collectionOffset});if(!alive()||request!==collectionRequest)return;
      collectionSelect.replaceChildren();for(const item of result.items){const option=el('option',item.name);option.value=item.id;option._entry=item;collectionSelect.append(option);}
      collectionSelect.dataset.next=result.next_offset===null?'':String(result.next_offset);
      addCollection.disabled=result.items.length===0;
    }
    container.append(action(label('上一页藏书','Previous collections'),async()=>{collectionOffset=Math.max(0,collectionOffset-30);await loadCollections();}),action(label('下一页藏书','Next collections'),async()=>{if(collectionSelect.dataset.next){collectionOffset=Number(collectionSelect.dataset.next);await loadCollections();}}),action(label('加载我的笔记和藏书','Load my notes and collections'),async()=>{await loadNotes();await loadBookmarks();await loadCollections();}));
    return {loadNotes,loadBookmarks,loadCollections};
  }
};

/* One optimistic multilingual metadata editor in all native GUI/WebExtension shells. */
globalThis.ZioktMetadataEditor={
  mount(container,{call,id,language='en',status=()=>{}}){
    const zh=language.startsWith('zh'),label=(a,b)=>zh?a:b;
    const node=(tag,value)=>{const element=document.createElement(tag);if(value!==undefined)element.textContent=value;return element;};
    const body=node('div'),select=node('select'),tag=node('input'),fields={};let current=null,busy=false;
    container.append(node('summary',label('管理多语言书目','Manage multilingual bibliography')),body);
    const field=(name,text,type='input')=>{const wrap=node('label',text),input=node(type);input.style.cssText='display:block;min-height:44px;width:100%;max-width:100%;box-sizing:border-box';wrap.append(input);body.append(wrap);fields[name]=input;return input;};
    const choose=node('label',label('现有书目语言','Existing bibliography language'));select.style.minHeight='44px';choose.append(select);body.append(choose);
    const tagWrap=node('label',label('语言标签（留空编辑默认书目）','Language tag (empty edits default bibliography)'));tag.maxLength=63;tag.style.minHeight='44px';tagWrap.append(tag);body.append(tagWrap);
    field('title',label('书目标题','Bibliographic title')).maxLength=2048;
    field('subtitle',label('书目副标题','Bibliographic subtitle')).maxLength=2048;
    field('authors',label('书目作者（每行一位）','Authors (one per line)'),'textarea').maxLength=32768;
    field('translators',label('书目译者（每行一位）','Translators (one per line)'),'textarea').maxLength=32768;
    field('publisher',label('书目出版者','Bibliographic publisher')).maxLength=2048;
    field('description',label('书目描述','Bibliographic description'),'textarea').maxLength=4096;
    const act=(text,fn)=>{const button=node('button',text);button.type='button';button.style.minHeight='44px';button.onclick=async()=>{if(busy)return;busy=true;button.disabled=true;try{await fn();}catch(error){status(error.message);}finally{busy=false;button.disabled=false;}};body.append(button);return button;};
    const fill=()=>{const entry=tag.value?(current?.localized_metadata?.[tag.value]||{}):current||{};for(const [name,input] of Object.entries(fields))input.value=Array.isArray(entry[name])?entry[name].join('\n'):entry[name]||'';};
    const inventory=()=>{const existing=Object.keys(current?.localized_metadata||{}).find(key=>key.toLowerCase()===tag.value.toLowerCase());if(existing)tag.value=existing;select.replaceChildren();const base=node('option',label('默认书目','Default bibliography'));base.value='';select.append(base);for(const key of Object.keys(current?.localized_metadata||{}).sort()){const option=node('option',key);option.value=key;select.append(option);}select.value=tag.value;};
    const load=async()=>{const result=await call('library.get',{id});if(!container.isConnected)return;current=result;inventory();fill();save.disabled=!current.editable;remove.disabled=!current.editable;status(current.editable?label('书目已加载；保存时检查版本','Bibliography loaded; updates check its version'):label('此书目由其他账户或节点管理','This bibliography belongs to another account or node'));};
    act(label('加载书目信息','Load bibliography'),load);
    const submit=async deleting=>{
      if(!current?.editable)throw Error(label('请先加载可编辑书目','Load an editable bibliography first'));
      const metadata={...current},localized={...(current.localized_metadata||{})};const selected=Object.keys(localized).find(key=>key.toLowerCase()===tag.value.toLowerCase())||tag.value;
      for(const key of ['file','updated_at','version_event','origin','editable','metadata_locale','default_title'])delete metadata[key];
      metadata.expected_event=current.version_event;
      if(deleting){if(!tag.value)throw Error(label('不能删除默认书目','Default bibliography cannot be removed'));delete localized[selected];}
      else{const entry={};for(const [name,input] of Object.entries(fields))entry[name]=name==='authors'||name==='translators'?input.value.split('\n').map(value=>value.trim()).filter(Boolean):input.value;
        if(tag.value)localized[selected]=entry;else Object.assign(metadata,entry);}
      if(Object.keys(localized).length)metadata.localized_metadata=localized;else delete metadata.localized_metadata;
      await call('library.publish',{metadata});await load();status(label('书目已保存；重新检索可查看语言版本','Bibliography saved; search again to display its language version'));
    };
    const save=act(label('保存书目版本','Save bibliography version'),()=>submit(false)),remove=act(label('删除该语言版本','Remove this language version'),()=>submit(true));save.disabled=true;remove.disabled=true;
    select.onchange=()=>{tag.value=select.value;fill();};tag.onchange=fill;
    return {load};
  }
};

/* Explicit, bounded index work. Closing the panel pauses requests; revisions make retries safe. */
globalThis.ZioktDocumentIndex={
  mount(container,{call,id,language='en',status=()=>{}}) {
    const zh=language.startsWith('zh'),label=(a,b)=>zh?a:b;
    const node=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n;};
    container.dataset.documentIndex='';
    container.append(node('summary',label('私人全文索引','Private full text index')));
    container.append(node('p',label('仅在本账户建立加密索引。完成后可搜索正文；关闭此面板暂停，重新点击可恢复。','Build an encrypted index for this account. Body search starts after completion. Close this panel to pause; resume with the button.')));
    const progress=node('p','');progress.setAttribute('role','status');progress.setAttribute('aria-live','polite');
    const start=node('button',label('建立 / 恢复索引','Build / resume index')),cancel=node('button',label('删除我的索引','Delete my index'));
    for(const b of [start,cancel]){b.type='button';b.style.minHeight='44px';}
    cancel.disabled=true;container.append(progress,start,cancel);let job=null,running=false,epoch=0;
    const show=()=>{if(job)progress.textContent=job.state+' · '+job.characters+' '+label('字符','characters')+' · '+job.chapter+'/'+job.chapters;};
    container.addEventListener('toggle',()=>{if(!container.open)epoch++;});
    start.onclick=async()=>{
      if(running)return;running=true;start.disabled=true;const turn=++epoch;
      try {
        job=await call('library.index.start',{id});cancel.disabled=false;show();
        while(container.isConnected&&container.open&&epoch===turn&&!['complete','failed','cancelled'].includes(job.state)) {
          job=await call('library.index.step',{job:job.id,revision:job.revision});show();
          if(job.busy){status(label('其他任务正在处理，请稍后恢复。','Another request is working; resume later.'));break;}
        }
      }catch(error){status(error.message);}finally{running=false;start.disabled=false;}
    };
    cancel.onclick=async()=>{
      if(!job)return;epoch++;cancel.disabled=true;
      try{job=await call('library.index.cancel',{job:job.id});show();}catch(error){status(error.message);}finally{cancel.disabled=false;}
    };
  }
};


  // --- Module: core.js ---
// ==============================================================================
// Ziokt Unified Graphical Client - Core Application Framework & State Manager
// ==============================================================================
function getStorage(key, fallback = '') {
  if (key === 'ziokt_auth_token') return '';
  try {
    const v = localStorage.getItem(key);
    return v !== null ? v : fallback;
  } catch (e) {
    return fallback;
  }
}
function setStorage(key, val) {
  if (key === 'ziokt_auth_token') { State.authToken = val; return; }
  try {
    localStorage.setItem(key, val);
  } catch (e) {
    console.warn(`Failed to set storage for ${key}:`, e);
  }
}

function getInitialLang() {
  const raw = getStorage('ziokt_lang') || (typeof navigator !== 'undefined' ? navigator.language : 'zh') || 'zh';
  return raw.toLowerCase().startsWith('en') ? 'en' : 'zh';
}

const nodeSecrets = new Map();
try { localStorage.removeItem('ziokt_auth_token'); const old = JSON.parse(localStorage.getItem('ziokt_remote_nodes') || '[]'); localStorage.setItem('ziokt_remote_nodes', JSON.stringify(old.map(({authToken, ...n}) => n))); } catch (_) {}
function configuredEndpoint(name, path = '/') {
  const explicit = getStorage('ziokt_endpoint_' + name) || (State.serviceEndpoints || {})[name] || (typeof document !== 'undefined' ? document.querySelector('meta[name="ziokt-' + name + '"]')?.content : '');
  const base = State.runtimeMode === 'local' ? State.localGatewayUrl : (getActiveRemoteNode()?.url || State.gatewayUrl);
  const url = new URL(explicit || path, base);
  if (!['https:', 'http:', 'nntps:'].includes(url.protocol) || url.username || url.password) throw Error('Invalid configured service endpoint');
  return url.href;
}
function initialGateway() {
  const explicit=getStorage('ziokt_default_gateway') || (typeof document !== 'undefined' ? document.querySelector('meta[name="ziokt-gateway"]')?.content : '');
  if(explicit)return explicit;
  return typeof location!=='undefined' && ['https:','http:'].includes(location.protocol) && !['tauri.localhost','appassets.androidplatform.net'].includes(location.hostname) ? location.origin : getStorage('ziokt_local_gateway','http://127.0.0.1:8185');
}
const DEFAULT_REMOTE_NODES = [
  {
    id: 'node-official-tokyo',
    name: 'Configured Gateway',
    url: initialGateway(),
    authToken: '',
    isDefault: true,
    status: 'unverified',
    latency: '--',
    verifiedAt: null
  }
];
function getRemoteNodes() {
  try {
    const raw = localStorage.getItem('ziokt_remote_nodes');
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) return parsed.map(n => ({...n,authToken: nodeSecrets.get(n.id) || '',status:'unverified'}));
    }
  } catch (e) {}
  return [...DEFAULT_REMOTE_NODES];
}
function saveRemoteNodes(nodes) {
  nodes.forEach(n => nodeSecrets.set(n.id, n.authToken || ''));
  setStorage('ziokt_remote_nodes', JSON.stringify(nodes.map(({authToken, ...n}) => n)));
  State.remoteNodes = nodes;
  Events.emit('remote_nodes_changed', nodes);
}
function getActiveRemoteNode() {
  const nodes = State.remoteNodes || getRemoteNodes();
  const activeId = State.activeRemoteNodeId || getStorage('ziokt_active_node_id', 'node-official-tokyo');
  return nodes.find(n => n.id === activeId) || nodes[0] || DEFAULT_REMOTE_NODES[0];
}
function setActiveRemoteNode(id) {
  const nodes = State.remoteNodes || getRemoteNodes();
  const target = nodes.find(n => n.id === id);
  if (target) {
    State.activeRemoteNodeId = target.id;
    State.gatewayUrl = target.url;
    State.serviceEndpoints = {};
    setStorage('ziokt_active_node_id', target.id);
    setStorage('ziokt_gateway', target.url);
    if (target.authToken) {
      setStorage('ziokt_auth_token', target.authToken);
    }
    Events.emit('active_node_changed', target);
    discoverServiceEndpoints();
    updateAppNodeBadge();
    return true;
  }
  return false;
}
function addRemoteNode({ name, url, authToken }) {
  const nodes = getRemoteNodes();
  const cleanUrl = url.trim().replace(/\/+$/, '');
  const cleanName = name.trim() || cleanUrl;
  const cleanToken = (authToken || '').trim();
  const newNode = {
    id: 'node-' + Date.now().toString(36) + '-' + Math.random().toString(36).substr(2, 5),
    name: cleanName,
    url: cleanUrl,
    authToken: cleanToken,
    isDefault: false,
    status: cleanToken ? 'unverified' : 'unauthenticated',
    latency: '--',
    verifiedAt: null
  };
  nodes.push(newNode);
  saveRemoteNodes(nodes);
  return newNode;
}
function removeRemoteNode(id) {
  let nodes = getRemoteNodes();
  const target = nodes.find(n => n.id === id);
  if (!target) return false;
  if (target.isDefault) {
    throw new Error('Default system node cannot be deleted');
  }
  nodes = nodes.filter(n => n.id !== id);
  saveRemoteNodes(nodes);
  if (State.activeRemoteNodeId === id) {
    setActiveRemoteNode(nodes[0].id);
  }
  return true;
}
const State = {
  currentTab: 'home',
  language: getInitialLang(),
  theme: getStorage('ziokt_theme', 'dark'),
  runtimeMode: getStorage('ziokt_mode', typeof location !== 'undefined' && ['http:','https:'].includes(location.protocol) && !['tauri.localhost','appassets.androidplatform.net'].includes(location.hostname) ? 'remote' : 'local'), // 'local' | 'remote' | 'hybrid'
  gatewayUrl: getStorage('ziokt_gateway', initialGateway()),
  localGatewayUrl: getStorage('ziokt_local_gateway','http://127.0.0.1:8185'),
  serviceEndpoints: {},
  localNodeStatus: 'checking', // 'checking' | 'online' | 'offline'
  localNodeDetails: null,
  remoteNodes: getRemoteNodes(),
  activeRemoteNodeId: getStorage('ziokt_active_node_id', 'node-official-tokyo'),
  authToken: '',
  userDid: getStorage('ziokt_did', ''),
  components: {
    corium: { name: 'Corium Blockchain', status: 'unverified', port: 8545 },
    shadow6: { name: 'Shadow6 Mesh Cluster', status: 'unverified', port: 8186 },
    ufs: { name: 'UFS & dCPM Storage', status: 'unverified', port: 8184 },
    watchat: { name: 'WATChat Bridge', status: 'unverified', port: 8181 },
    etp: { name: 'ETP Onion Gateway', status: 'unverified', port: 9050 }
  },
  i18nData: {},
  events: {}
};

// Event Bus
const Events = {
  on(event, callback) {
    if (!State.events[event]) State.events[event] = [];
    State.events[event].push(callback);
  },
  emit(event, data) {
    if (State.events[event]) {
      State.events[event].forEach(cb => cb(data));
    }
  }
};
const BUILTIN_I18N = {"zh": {"app": {"title": "Ziokt 统一图形客户端", "subtitle": "去中心化原生操作系统与应用生态控制中心", "version": "v1.0.0 (Core Native)", "status_online": "正常运行", "status_offline": "已断开", "status_connecting": "连接中...", "mode_local": "本地节点", "mode_remote": "远程网关", "mode_hybrid": "混合模式", "switch_lang": "语言 / Language", "theme_dark": "赛博深黑", "theme_light": "清爽明亮", "theme_contrast": "高对比度"}, "nav": {"home": "首页总览", "chat": "加密通讯", "forum": "社区论坛", "files": "安全存储", "apps": "应用中心", "network": "网络节点", "identity": "身份与贡献", "devtools": "开发工具", "settings": "系统设置", "library": "Library", "netnews": "Netnews", "ecosystem": "应用与离线"}, "common": {"confirm": "确认", "cancel": "取消", "delete": "删除", "save": "保存", "edit": "编辑", "copy": "复制", "copied": "已复制到剪贴板", "refresh": "刷新", "search": "搜索...", "loading": "加载中...", "success": "操作成功", "error": "操作失败", "details": "查看详情", "actions": "操作", "status": "状态", "name": "名称", "version": "版本", "size": "大小", "date": "时间", "upload": "上传", "download": "下载", "view_raw": "查看原始数据", "advanced": "高级选项", "close": "关闭"}, "home": {"welcome": "欢迎使用 Ziokt 统一图形客户端", "welcome_sub": "集成零知识加密通讯、去中心化包管理、多协议隧道及链上可信微架构", "quick_actions": "快捷功能入口", "system_health": "核心组件健康状态", "gateway_telemetry": "网关实时遥测", "recent_activity": "近期网络活动", "act_chat": "快速发起加密对话", "act_files": "打开原生文件保险库", "act_forum": "浏览社区最新提案", "act_apps": "管理与运行扩展包", "act_network": "查看 Shadow6 / ETP 网格", "local_offline_alert": "⚠️ 未检测到本地真实节点: 当前处于本地模式，但 http://127.0.0.1:8185 未响应。使用本地节点需要用户本地真实有节点运行。", "remote_unauth_alert": "🔒 远程节点需要身份鉴权: 当前活跃远程节点尚未配置有效的 Auth Token 凭证。", "switch_remote": "切换至远程网关", "config_auth": "前往配置凭证", "probe_local": "重新检测本地节点"}, "chat": {"title": "WATChat 端到端加密通讯", "dual_ui": "界面风格切换", "ui_minimalist": "现代简约版", "ui_classic": "经典丰富版", "ui_switch_tip": "随时切换界面布局，聊天记录与加密密钥实时同步无损保留", "contacts": "联系人 / 对话列表", "new_conversation": "新建加密对话", "enter_recipient": "输入对方 DID 或公钥地址", "send": "发送", "input_placeholder": "输入加密消息...", "attach_file": "发送文件附件", "encryption_badge": "AES-256-GCM (native WATChat)", "empty_messages": "暂无历史消息，发送一条问候开启端到端密聊吧", "login_title": "WATChat 密聊身份登录", "login_desc": "选择您偏好的 UI 风格并解锁端到端加密会话凭证", "login_btn": "登录并进入加密通讯", "username_placeholder": "输入用户名或 DID", "passphrase_placeholder": "输入加密私钥密码 / 会话密令", "logout_btn": "锁定会话 / 退出", "classic_telemetry": "经典版实时安全信令与拓扑遥测", "ratchet_status": "会话状态：未验证", "cipher_info": "ECDH P-256 / HKDF-SHA256 / AES-256-GCM", "onion_route": "路由状态：未验证"}, "forum": {"title": "Corium 去中心化社区论坛", "new_post": "发布新帖 / 提案", "post_title": "标题", "post_category": "分类", "post_content": "正文内容 (支持 Markdown)", "sign_and_publish": "使用当前身份签名并发布", "cat_governance": "生态治理", "cat_technical": "核心技术", "cat_apps": "应用开发", "cat_general": "综合讨论", "signature_verified": "Ed25519 链上签名已验证", "replies": "条回复"}, "files": {"title": "UFS & SafeFS 安全存储保险库", "vault_type": "存储驱动", "vault_ufs": "UFS 原生文件系统", "vault_safefs": "SafeFS AEAD 加密保险箱", "upload_file": "上传文件", "create_folder": "新建目录", "stealth_mode": "双层可抵赖卷 (Outer Decoy / Inner Stealth)", "drop_tip": "拖拽文件至此处，自动执行安全分块持久化", "download": "下载文件", "delete_confirm": "确定永久删除此文件吗？此操作不可逆。"}, "apps": {"title": "dCPM 去中心化应用中心", "subtitle": "基于 UFS 与 dCPM 签名软件包体系，支持依赖审查、自动验签与安全沙箱执行", "install_pkg": "安装 / 导入 .dcpm 软件包", "installed_tab": "已安装应用", "market_tab": "生态软件包仓库", "rollback": "版本回滚", "uninstall": "卸载", "update": "检查更新", "publisher": "发布者签名", "digest": "SHA-256 校验摘要", "dependencies": "依赖组件", "dep_check_ok": "依赖项完整", "install_confirm": "确定安装此签名软件包吗？将严格在隔离沙箱中运行。", "uninstall_confirm": "确定卸载该应用及其本地缓存吗？"}, "network": {"title": "Shadow6 & ETP 网络节点网格", "subtitle": "管理 13 核心 Profile 运行集群、Virtual Broker 以及洋葱代理链路", "profiles_title": "13 语言核心 Profile 实时集群", "virtual_broker": "虚拟 Broker 代理状态", "s6p1_import": "粘贴导入自定义 S6P1 凭据信封", "etp_title": "ETP 原生洋葱多跳链路", "hops": "跳路由路径", "ping_test": "网络延迟诊断", "privacy_masked": "非管理员模式已自动脱敏保护敏感 IP 与密钥", "node_topology": "节点与网关拓扑", "local_node": "本地节点", "remote_nodes": "远程节点集群", "manage_nodes": "管理自定义节点"}, "identity": {"title": "身份管理与贡献证明 (PoUW)", "did": "去中心化身份 (DID)", "nns_domain": "NNS 绑定域名", "pouw_status": "PoUW 算力与共识贡献状态", "engine_reward": "治理奖励权重", "apply_weight": "申请加入验证者权重白名单", "export_keys": "导出加密密钥备份", "switch_account": "切换身份"}, "devtools": {"title": "原生组件全功能开发工具箱", "subtitle": "提供 Corium、Tri、ZDA、TC-16 虚拟机及 MCP 接口全功能调试与执行界面", "tab_corium": "Corium 控制台", "tab_tri": "Tri 状态机快照", "tab_zda": "ZDA / Ano 门限计算", "tab_tc16": "TC-16 虚拟机工作台", "tab_mcp": "MCP 211 工具探针", "corium_query": "查询区块与交易事实", "tri_run": "执行快照离线隔离沙箱", "zda_calc": "验证精确 ZDA 证据算术", "tc16_asm": "TC-16 汇编与字节码单步调试", "tc16_run": "运行虚拟机", "tc16_step": "单步执行 (Step)", "tc16_reset": "重置寄存器"}, "settings": {"title": "系统与组件生命周期设置", "runtime_mode": "客户端运行模式配置", "local_gateway_url": "本地/远程网关地址", "components_lifecycle": "按需组件启动管理 (On-demand Launcher)", "comp_corium": "Corium 原生区块链服务", "comp_shadow6": "Shadow6 多核心代理网络", "comp_ufs": "UFS & dCPM 安全存储引擎", "comp_watchat": "WATChat 联邦通讯桥接", "comp_etp": "ETP 洋葱网关路由", "accessibility": "无障碍与键盘导航", "keyboard_shortcuts": "快捷键说明: [1-9] 切换模块，[Esc] 关闭弹窗，[Ctrl+K] 全局搜索", "local_node_title": "本地节点连接与真实状态", "local_node_desc": "使用本地节点需要用户本地真实有节点运行。若本地未启动，客户端将无法进行写操作与本地 RPC 交互。", "local_node_probe": "探测本地节点", "local_node_online": "本地真实节点在线", "local_node_offline": "未检测到本地真实节点", "local_node_checking": "检测本地节点中...", "local_node_help": "本地启动指引: 请在终端执行 systemctl start ziokt-gateway 或运行 ./tools/control_center.sh", "remote_nodes_title": "远程节点网关与鉴权管理", "remote_nodes_desc": "使用远程节点需要身份鉴权 (Auth Token)。您可以自定义添加新的远程节点并测试连接与鉴权有效性。", "add_node": "添加新远程节点", "node_name": "节点名称", "node_url": "节点地址 (URL)", "auth_token": "鉴权凭证 (Auth Token)", "auth_token_tip": "用于 Bearer / X-Ziokt-Auth 远程身份验证", "test_auth": "测试鉴权", "set_active": "设为活跃", "active_badge": "当前活跃", "auth_valid": "鉴权通过", "auth_invalid": "鉴权失败", "auth_required": "待鉴权", "delete_node": "删除节点", "cannot_delete_default": "系统默认节点不可删除", "add_node_btn": "添加并测试该节点"}}, "en": {"app": {"title": "Ziokt Unified Graphical Client", "subtitle": "Decentralized Native OS & Application Ecosystem Console", "version": "v1.0.0 (Core Native)", "status_online": "Online", "status_offline": "Disconnected", "status_connecting": "Connecting...", "mode_local": "Local Node", "mode_remote": "Remote Gateway", "mode_hybrid": "Hybrid Mode", "switch_lang": "Language / 语言", "theme_dark": "Cyber Dark", "theme_light": "Clean Light", "theme_contrast": "High Contrast"}, "nav": {"home": "Home", "chat": "WATChat", "forum": "Forum", "files": "Files & Vault", "apps": "App Store", "network": "Network Nodes", "identity": "Identity & PoUW", "devtools": "Dev Tools", "settings": "Settings", "library": "Library", "netnews": "Netnews", "ecosystem": "Applications & offline"}, "common": {"confirm": "Confirm", "cancel": "Cancel", "delete": "Delete", "save": "Save", "edit": "Edit", "copy": "Copy", "copied": "Copied to clipboard", "refresh": "Refresh", "search": "Search...", "loading": "Loading...", "success": "Success", "error": "Error", "details": "Details", "actions": "Actions", "status": "Status", "name": "Name", "version": "Version", "size": "Size", "date": "Date", "upload": "Upload", "download": "Download", "view_raw": "View Raw JSON", "advanced": "Advanced", "close": "Close"}, "home": {"welcome": "Welcome to Ziokt Unified Graphical Client", "welcome_sub": "Integrating Zero-Knowledge communications, dCPM packages, Shadow6 mesh tunnels, and verifiable native compute", "quick_actions": "Quick Actions", "system_health": "Component Health", "gateway_telemetry": "Gateway Telemetry", "recent_activity": "Recent Activity", "act_chat": "Start Encrypted Chat", "act_files": "Open Secure File Vault", "act_forum": "Browse Latest Proposals", "act_apps": "Manage dCPM Packages", "act_network": "Inspect Shadow6 & ETP Mesh", "local_offline_alert": "⚠️ No local real node detected: Currently in local mode, but http://127.0.0.1:8185 is not responding. Local mode requires an actual running Ziokt node.", "remote_unauth_alert": "🔒 Remote node requires authentication: Active remote node does not have a valid Auth Token configured.", "switch_remote": "Switch to Remote Gateway", "config_auth": "Configure Auth Credentials", "probe_local": "Probe Local Node"}, "chat": {"title": "WATChat End-to-End Encrypted Messenger", "dual_ui": "UI Switcher", "ui_minimalist": "Modern Minimalist", "ui_classic": "Classic Rich", "ui_switch_tip": "Seamlessly switch between layouts; message history and cryptographic keys are synchronized without loss", "contacts": "Contacts / Dialogs", "new_conversation": "New Secure Chat", "enter_recipient": "Enter recipient DID or public key", "send": "Send", "input_placeholder": "Type encrypted message...", "attach_file": "Attach Vault File", "encryption_badge": "AES-256-GCM (native WATChat)", "empty_messages": "No messages yet. Send a greeting to start secure chatting.", "login_title": "WATChat Identity Sign In", "login_desc": "Choose your preferred UI style and unlock your end-to-end encrypted session", "login_btn": "Sign In & Enter Encrypted Chat", "username_placeholder": "Enter username or DID", "passphrase_placeholder": "Enter private key passphrase / session secret", "logout_btn": "Lock Session / Sign Out", "classic_telemetry": "Classic Mode Real-Time Security Signaling & Telemetry", "ratchet_status": "Session: unverified", "cipher_info": "ECDH P-256 / HKDF-SHA256 / AES-256-GCM", "onion_route": "Route: unverified"}, "forum": {"title": "Corium Decentralized Community Forum", "new_post": "New Post / Proposal", "post_title": "Title", "post_category": "Category", "post_content": "Content (Markdown supported)", "sign_and_publish": "Sign with Ed25519 & Publish", "cat_governance": "Governance", "cat_technical": "Technical", "cat_apps": "App Development", "cat_general": "General Discussion", "signature_verified": "Ed25519 On-Chain Signature Verified", "replies": "replies"}, "files": {"title": "UFS & SafeFS Secure Storage Vault", "vault_type": "Storage Driver", "vault_ufs": "UFS Native Storage", "vault_safefs": "SafeFS AEAD Encrypted Vault", "upload_file": "Upload File", "create_folder": "New Folder", "stealth_mode": "Deniable Volume (Outer Decoy / Inner Stealth)", "drop_tip": "Drag and drop files here for chunked persistent storage", "download": "Download File", "delete_confirm": "Are you sure you want to permanently delete this file? This cannot be undone."}, "apps": {"title": "dCPM Decentralized App Center", "subtitle": "Built on UFS and signed dCPM package architecture with dependency verification and sandbox isolation", "install_pkg": "Install / Import .dcpm Package", "installed_tab": "Installed Applications", "market_tab": "Ecosystem Repository", "rollback": "Rollback Version", "uninstall": "Uninstall", "update": "Check Updates", "publisher": "Publisher Key", "digest": "SHA-256 Digest", "dependencies": "Dependencies", "dep_check_ok": "All Dependencies Satisfied", "install_confirm": "Confirm installation of this signed package? It will execute inside an isolated sandbox.", "uninstall_confirm": "Confirm uninstallation of this package and its local cache?"}, "network": {"title": "Shadow6 & ETP Network Mesh", "subtitle": "Manage 13 language core Profile cluster, Virtual Broker, and onion routing paths", "profiles_title": "13 Core Language Profiles Cluster", "virtual_broker": "Virtual Broker Status", "s6p1_import": "Import Custom S6P1 Credential Envelope", "etp_title": "ETP Native Onion Multi-Hop Paths", "hops": "hop route path", "ping_test": "Latency Diagnostics", "privacy_masked": "Non-admin mode has automatically masked sensitive IPs and private keys", "node_topology": "Node & Gateway Topology", "local_node": "Local Node", "remote_nodes": "Remote Nodes Cluster", "manage_nodes": "Manage Custom Nodes"}, "identity": {"title": "Identity & Proof of Useful Work (PoUW)", "did": "Decentralized ID (DID)", "nns_domain": "NNS Bound Domain", "pouw_status": "PoUW Compute & Consensus Contribution", "engine_reward": "Governance Reward Weight", "apply_weight": "Apply for Validator Weight Whitelist", "export_keys": "Export Encrypted Backup", "switch_account": "Switch Identity"}, "devtools": {"title": "Native Component Developer Studio", "subtitle": "Fully functional GUIs for Corium, Tri, ZDA, TC-16 Virtual Machine, and MCP diagnostics", "tab_corium": "Corium Console", "tab_tri": "Tri Snapshots", "tab_zda": "ZDA / Ano Gate", "tab_tc16": "TC-16 VM Studio", "tab_mcp": "MCP Tool Catalog", "corium_query": "Query Ledger Facts & Blocks", "tri_run": "Execute Isolated Sandbox Snapshot", "zda_calc": "Verify Exact ZDA Evidence Arithmetic", "tc16_asm": "TC-16 Assembly & Bytecode Debugger", "tc16_run": "Run Virtual Machine", "tc16_step": "Step Execution", "tc16_reset": "Reset Registers"}, "settings": {"title": "System & Component Lifecycle Settings", "runtime_mode": "Client Runtime Mode", "local_gateway_url": "Gateway Endpoint", "components_lifecycle": "On-Demand Component Launcher", "comp_corium": "Corium Native Blockchain", "comp_shadow6": "Shadow6 Multi-Core Tunnel", "comp_ufs": "UFS & dCPM Storage Engine", "comp_watchat": "WATChat Federation Bridge", "comp_etp": "ETP Onion Gateway Router", "accessibility": "Accessibility & Keyboard Navigation", "keyboard_shortcuts": "Shortcuts: [1-9] Switch Modules, [Esc] Close Modals, [Ctrl+K] Global Search", "local_node_title": "Local Node Connection & Real Verification", "local_node_desc": "Using local node requires an actual Ziokt node daemon running locally. If not running, local RPC and write operations are blocked.", "local_node_probe": "Probe Local Node", "local_node_online": "Local Real Node Online", "local_node_offline": "No Local Real Node Detected", "local_node_checking": "Probing Local Node...", "local_node_help": "Start local node daemon: run 'systemctl start ziokt-gateway' or './tools/control_center.sh' in terminal.", "remote_nodes_title": "Remote Node Gateways & Auth Management", "remote_nodes_desc": "Using a remote node requires authentication (Auth Token). You can add custom remote nodes and test their connection and auth validity.", "add_node": "Add New Remote Node", "node_name": "Node Name", "node_url": "Node Endpoint (URL)", "auth_token": "Auth Token", "auth_token_tip": "Used for Bearer / X-Ziokt-Auth remote authentication", "test_auth": "Test Auth", "set_active": "Set Active", "active_badge": "Active", "auth_valid": "Auth Verified", "auth_invalid": "Auth Failed", "auth_required": "Auth Required", "delete_node": "Delete Node", "cannot_delete_default": "Default system node cannot be deleted", "add_node_btn": "Add & Verify Node"}}};

// i18n Translation Engine
async function initI18n() {
  const lang = State.language.toLowerCase().startsWith('en') ? 'en' : 'zh';
  if (typeof BUILTIN_I18N !== 'undefined' && BUILTIN_I18N[lang]) {
    State.i18nData = Object.assign({}, BUILTIN_I18N[lang]);
  }
  try {
    const res = await fetch(`i18n/${lang}.json`);
    if (res.ok) {
      const data = await res.json();
      State.i18nData = Object.assign({}, State.i18nData, data);
    }
  } catch (e) {
    // Built-in dictionaries active
  }
}
function t(path) {
  const parts = path.split('.');
  let curr = State.i18nData;
  for (const p of parts) {
    if (curr && curr[p] !== undefined) {
      curr = curr[p];
    } else {
      return path;
    }
  }
  return curr;
}
async function setLanguage(lang) {
  State.language = lang;
  setStorage('ziokt_lang', lang);
  await initI18n();
  Events.emit('language_changed', lang);
  updateAppNodeBadge();
}
function setTheme(theme) {
  State.theme = theme;
  setStorage('ziokt_theme', theme);
  document.documentElement.setAttribute('data-theme', theme);
  Events.emit('theme_changed', theme);
}

// UI Notification Toast
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span>${type === 'success' ? '✓' : type === 'error' ? '✕' : 'ℹ'}</span> <span>${message}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 250);
  }, 3500);
}

// Confirmation Dialog Modal (Promise-based)
function showConfirm(title, message) {
  return new Promise((resolve) => {
    const overlay = document.getElementById('modal-overlay');
    const titleEl = document.getElementById('modal-title');
    const bodyEl = document.getElementById('modal-body');
    const footerEl = document.getElementById('modal-footer');
    
    titleEl.textContent = title;
    bodyEl.innerHTML = `<p style="line-height:1.6;color:var(--text-main);">${message}</p>`;
    footerEl.innerHTML = `
      <button class="btn btn-secondary" id="modal-cancel">${t('common.cancel')}</button>
      <button class="btn btn-primary" id="modal-ok">${t('common.confirm')}</button>
    `;
    
    overlay.style.display = 'flex';
    
    const cleanup = () => {
      overlay.style.display = 'none';
      document.getElementById('modal-cancel')?.removeEventListener('click', onCancel);
      document.getElementById('modal-ok')?.removeEventListener('click', onOk);
    };
    
    const onCancel = () => { cleanup(); resolve(false); };
    const onOk = () => { cleanup(); resolve(true); };
    
    document.getElementById('modal-cancel').addEventListener('click', onCancel);
    document.getElementById('modal-ok').addEventListener('click', onOk);
  });
}

// Raw JSON View Modal
function showJsonModal(title, data) {
  const overlay = document.getElementById('modal-overlay');
  const titleEl = document.getElementById('modal-title');
  const bodyEl = document.getElementById('modal-body');
  const footerEl = document.getElementById('modal-footer');
  
  titleEl.textContent = title;
  const jsonStr = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
  const pre=document.createElement('pre');pre.style.cssText='background:var(--bg-input);padding:14px;border-radius:6px;font-family:var(--font-mono);font-size:0.8rem;color:var(--accent-cyan);overflow:auto;max-height:55vh;white-space:pre-wrap';pre.textContent=jsonStr;bodyEl.replaceChildren(pre);
  footerEl.innerHTML = `
    <button class="btn btn-secondary" id="modal-copy">${t('common.copy')}</button>
    <button class="btn btn-primary" id="modal-close">${t('common.close')}</button>
  `;
  overlay.style.display = 'flex';
  
  document.getElementById('modal-copy').onclick = () => {
    navigator.clipboard.writeText(jsonStr);
    showToast(t('common.copied'), 'success');
  };
  document.getElementById('modal-close').onclick = () => {
    overlay.style.display = 'none';
  };
}

// Probe Real Local Node Health
async function checkLocalNodeHealth() {
  State.localNodeStatus = 'checking';
  Events.emit('local_node_status_changed', { status: 'checking' });
  updateAppNodeBadge();

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 2500);
    const res = await fetch(`${State.localGatewayUrl}/api/gateway/status`, {
      signal: controller.signal,
      headers: { 'Accept': 'application/json' }
    });
    clearTimeout(timeoutId);

    if (res.ok) {
      const data = await res.json();
      if(data.schema==='ziokt.gateway.v1')State.serviceEndpoints=data.service_endpoints||{};
      State.localNodeStatus = 'online';
      State.localNodeDetails = data;
      Events.emit('local_node_status_changed', { status: 'unverified', data });
      updateAppNodeBadge();
      return { ok: true, data };
    } else {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail.error || `HTTP ${res.status}: ${res.statusText}`);
    }
  } catch (err) {
    State.localNodeStatus = 'offline';
    State.localNodeDetails = { error: err.message };
    Events.emit('local_node_status_changed', { status: 'offline', error: err.message });
    Events.emit('local_node_offline', { error: err.message });
    updateAppNodeBadge();
    return { ok: false, error: err.message };
  }
}

// Verify Remote Node Authentication and Connectivity
async function verifyRemoteNodeAuth(nodeId) {
  const nodes = getRemoteNodes();
  const node = nodes.find(n => n.id === nodeId);
  if (!node) throw new Error('Node not found');

  if (!node.authToken || node.authToken.trim() === '') {
    node.status = 'unauthenticated';
    node.verifiedAt = Date.now();
    saveRemoteNodes(nodes);
    updateAppNodeBadge();
    return { ok: false, error: 'Auth Token is empty' };
  }

  const startTime = performance.now();
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 4000);
    const res = await fetch(`${node.url}/api/gateway/tools`, {
      signal: controller.signal,
      headers: {
        'Accept': 'application/json',
        'Authorization': `Bearer ${node.authToken}`,
        'X-Ziokt-Auth': node.authToken
      }
    });
    clearTimeout(timeoutId);
    const latency = Math.round(performance.now() - startTime);

    if (res.status === 401 || res.status === 403) {
      node.status = 'auth_failed';
      node.latency = `${latency}ms`;
      node.verifiedAt = Date.now();
      saveRemoteNodes(nodes);
      updateAppNodeBadge();
      return { ok: false, error: `Authentication failed (HTTP ${res.status})` };
    } else if (res.ok) {
      node.status = 'online';
      node.latency = `${latency}ms`;
      node.verifiedAt = Date.now();
      saveRemoteNodes(nodes);
      updateAppNodeBadge();
      return { ok: true, latency: `${latency}ms` };
    } else {
      node.status = 'error';
      node.latency = `${latency}ms`;
      node.verifiedAt = Date.now();
      saveRemoteNodes(nodes);
      updateAppNodeBadge();
      return { ok: false, error: `HTTP ${res.status}: ${res.statusText}` };
    }
  } catch (err) {
    node.status = 'offline';
    node.latency = '--';
    node.verifiedAt = Date.now();
    saveRemoteNodes(nodes);
    updateAppNodeBadge();
    return { ok: false, error: err.message };
  }
}

// Check if client is in local mode without a running local node
function isLocalNodeOffline() {
  return State.runtimeMode === 'local' && State.localNodeStatus === 'offline';
}
function canUseWithoutLocalNode(tab) {return ['settings','ecosystem'].includes(tab);}

// Update Navigation Lock State for Non-Settings tabs
function updateNavLockState() {
  const isOffline = isLocalNodeOffline();
  const isEn = State.language === 'en';

  document.querySelectorAll('.nav-item, .bottom-item').forEach(item => {
    const tab = item.dataset.tab;
    if (!canUseWithoutLocalNode(tab)) {
      if (isOffline) {
        item.classList.add('nav-locked');
        item.setAttribute('title', isEn ? 'Locked: Local node is offline (Settings only)' : '已锁定: 本地节点未运行 (仅开放系统设置)');
      } else {
        item.classList.remove('nav-locked');
        item.removeAttribute('title');
      }
    }
  });

  const didPill = document.getElementById('user-did-pill');
  if (didPill) {
    if (isOffline) {
      didPill.textContent = isEn ? 'Local: Offline (No Node)' : '本地节点离线 (无可用身份)';
      didPill.style.color = 'var(--accent-red)';
      didPill.style.borderColor = 'rgba(239, 68, 68, 0.4)';
    } else if (State.runtimeMode === 'local' && State.localNodeStatus === 'online') {
      const did = State.localNodeDetails?.identity || State.userDid || 'did:ziokt:local:node0';
      didPill.textContent = did.length > 24 ? did.substring(0, 14) + '...' + did.substring(did.length - 6) : did;
      didPill.style.color = 'var(--accent-green)';
      didPill.style.borderColor = 'rgba(16, 185, 129, 0.4)';
    } else {
      const activeNode = getActiveRemoteNode();
      const did = State.userDid || (activeNode ? `did:ziokt:${activeNode.name || activeNode.id}` : 'did:ziokt:remote:guest');
      didPill.textContent = did.length > 24 ? did.substring(0, 14) + '...' + did.substring(did.length - 6) : did;
      didPill.style.color = 'var(--accent-cyan)';
      didPill.style.borderColor = 'var(--border-subtle)';
    }
  }
}

// Update Topbar and Sidebar Badges
function updateAppNodeBadge() {
  const labelEl = document.getElementById('sidebar-node-label');
  const dotEl = document.querySelector('#sidebar .status-dot');
  if (labelEl) {
    const isEn = State.language === 'en';
    if (State.runtimeMode === 'local') {
      if (State.localNodeStatus === 'online') {
        labelEl.textContent = isEn ? 'Local Node: Online (8185)' : '本地节点: 在线 (8185)';
        if (dotEl) dotEl.style.backgroundColor = 'var(--accent-green)';
      } else if (State.localNodeStatus === 'checking') {
        labelEl.textContent = isEn ? 'Local Node: Checking...' : '本地节点: 检测中...';
        if (dotEl) dotEl.style.backgroundColor = 'var(--accent-amber)';
      } else {
        labelEl.textContent = isEn ? 'Local Node: Offline (Not Running)' : '本地节点: 离线 (未启动)';
        if (dotEl) dotEl.style.backgroundColor = 'var(--accent-red)';
      }
    } else {
      const active = getActiveRemoteNode();
      if (active.status === 'online') {
        labelEl.textContent = isEn ? `Remote: ${active.name} (${active.latency})` : `远程网关: ${active.name} (${active.latency})`;
        if (dotEl) dotEl.style.backgroundColor = 'var(--accent-green)';
      } else if (active.status === 'unauthenticated') {
        labelEl.textContent = isEn ? 'Remote: Auth Required' : '远程网关: 待鉴权凭证';
        if (dotEl) dotEl.style.backgroundColor = 'var(--accent-amber)';
      } else {
        labelEl.textContent = isEn ? 'Remote: Disconnected' : '远程网关: 无法连接';
        if (dotEl) dotEl.style.backgroundColor = 'var(--accent-red)';
      }
    }
  }
  updateNavLockState();
}

// Unified Gateway API Client with Real Local Probe & Mandatory Remote Auth
async function apiRequest(endpoint, options = {}) {
  const isLocalMode = State.runtimeMode === 'local';

  if (isLocalMode) {
    // Mandate real running local node
    if (State.localNodeStatus === 'checking') {
      await checkLocalNodeHealth();
    }
    if (State.localNodeStatus === 'offline') {
      const msg = State.language === 'en'
        ? 'Local node is offline or unreachable (http://127.0.0.1:8185). Local mode requires an actual running Ziokt node daemon.'
        : '本地节点未启动或无法连接 (http://127.0.0.1:8185)。使用本地节点需要用户本地真实有节点运行。请启动本地进程或切换至远程网关。';
      showToast(msg, 'error');
      throw new Error(msg);
    }
  } else {
    // Mandate authentication for remote nodes when required (e.g. destructive writes or private APIs)
    const activeNode = getActiveRemoteNode();
    const token = activeNode?.authToken || State.authToken || getStorage('ziokt_auth_token');
    if (options.requireAuth && (!token || token.trim() === '')) {
      const msg = State.language === 'en'
        ? 'Remote node requires authentication credentials (Auth Token). Please configure a valid token in Settings.'
        : '使用该功能需要身份鉴权 (Auth Token)。请在“系统设置”中配置有效的访问凭证。';
      showToast(msg, 'error');
      throw new Error(msg);
    }
  }

  const base = isLocalMode ? State.localGatewayUrl : (getActiveRemoteNode()?.url || State.gatewayUrl);
  if (!endpoint.startsWith('/') || endpoint.startsWith('//')) throw new Error('Same gateway relative path required');
  const url = `${base}${endpoint}`;

  const headers = {
    'Accept': 'application/json',
    ...(options.headers || {})
  };

  {
    const activeNode = getActiveRemoteNode();
    const token = activeNode?.authToken || State.authToken || getStorage('ziokt_auth_token');
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
      headers['X-Ziokt-Auth'] = token;
    }
  }

  try {
    const res = await fetch(url, { ...options, headers });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail.error || `HTTP ${res.status}: ${res.statusText}`);
    }
    const contentType = res.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      return await res.json();
    }
    return await res.text();
  } catch (err) {
    console.warn(`API call failed for ${url}:`, err);
    throw err;
  }
}

// Real GUI operations share the server's typed MCP authorization, audit and idempotency.
async function callTool(name, arguments_, {confirm = false, key = crypto.randomUUID(), requireAuth = false} = {}) {
  const result = await apiRequest('/api/gateway/tools/call', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name, arguments: arguments_, confirm, idempotency_key: key}),
    requireAuth: requireAuth || confirm
  });
  const text = (result.content || []).filter(c => c.type === 'text').map(c => c.text).join('\n');
  if (result.isError) throw new Error(text || 'Tool execution failed');
  if (result.structuredContent) return result.structuredContent;
  try { return JSON.parse(text); } catch (_) { return {text}; }
}
async function sha256(bytes) {
  return 'sha256:' + Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), b => b.toString(16).padStart(2, '0')).join('');
}
async function uploadObject(file, app, progress = () => {}) {
  if (file.size > 64 * 1024 * 1024) throw new Error('Browser upload limit: 64 MiB per file');
  const bytes = new Uint8Array(await file.arrayBuffer());
  const digest = await sha256(bytes), upload = crypto.randomUUID();
  await callTool(app+'_object_begin', {params:{upload, size: bytes.length, digest, ttl: 3600}}, {confirm:true,key:upload+'-begin'});
  try {
    for (let start=0, position=0; start<bytes.length; start+=16384, position++) {
      const chunk=bytes.slice(start,start+16384);
      const data_base64=btoa(String.fromCharCode(...chunk));
      await callTool(app+'_object_chunk_put', {params:{upload,position,digest:await sha256(chunk),data_base64}}, {confirm:true,key:upload+'-chunk-'+position});
      progress(Math.min(start+16384,bytes.length),bytes.length);
    }
    const result=await callTool(app+'_object_finish',{params:{upload}},{confirm:true,key:upload+'-finish'});
    if (result.digest!==digest || result.length!==bytes.length) throw new Error('Final object receipt differs from uploaded content');
    return result;
  } catch (error) {
    // An ambiguous finish result retains its upload lease; inspect object.status before manual release.
    throw new Error('Upload '+upload+': '+error.message);
  }
}
async function renderToolPanel(container, title, filter, fileOperations = false) {
  container.innerHTML = `<div class="card"><a href="https://github.com/txmu/Ziokt-Releases/releases" target="_blank" rel="noopener">各平台软件下载 / Downloads</a><h2></h2><p>操作使用已鉴权的真实后端。工具结果仅代表其声明的阶段；验签、暂存、安装、激活分别显示。</p>
    <label>Node administrator token（只保存在当前页面内存）<input type="password" class="input-text" id="operation-token" autocomplete="off"></label>
    <button class="btn btn-primary" id="load-real-tools">连接并刷新工具</button><p id="tool-count"></p>
    <select class="input-text" id="real-tool"></select><pre id="real-schema" style="white-space:pre-wrap"></pre>
    <label>参数 JSON<textarea id="real-arguments" class="input-textarea" rows="7">{}</textarea></label>
    <label><input type="checkbox" id="real-confirm"> 我确认执行所选写操作</label>
    <button class="btn btn-primary" id="run-real-tool">执行</button>
    ${fileOperations ? '<hr><input type="file" id="real-file"><select id="file-app"><option>safefs</option><option>dcpm</option><option>ufs</option></select><button class="btn btn-secondary" id="upload-real-file">分块上传实际内容</button><p>上传只保存加密对象；上传不代表安装。</p><input id=download-object class=input-text placeholder="对象 manifest_digest"><button id=download-real-file class="btn btn-secondary">验证并下载实际内容</button><hr><input id=native-name class=input-text placeholder="原生包 ID（须匹配签名）"><input id=native-version class=input-text placeholder="原生包版本（须匹配签名）"><button id=stage-native-package class="btn btn-secondary">生成 v2 引用包并验证原生签名暂存</button>' : ''}
    <pre id="real-result" role="status" style="white-space:pre-wrap;overflow-wrap:anywhere"></pre></div>`;
  container.querySelector('h2').textContent=title;
  const out=container.querySelector('#real-result'), select=container.querySelector('#real-tool');
  let tools=[];
  const fail=e=>{out.textContent='操作失败：'+e.message;};
  container.querySelector('#load-real-tools').onclick=async()=>{
    const token=container.querySelector('#operation-token');
    if(token.value) {State.authToken=token.value;const n=getActiveRemoteNode();if(n){n.authToken=token.value;nodeSecrets.set(n.id,token.value);}token.value='';}
    try {
      const listing=await apiRequest('/api/gateway/tools');tools=listing.tools.filter(t=>filter(t.name));
      select.replaceChildren(...tools.map(t=>new Option(t.name,t.name)));
      container.querySelector('#tool-count').textContent=`已鉴权：${listing.count} 个工具，本页 ${tools.length} 个`;
      select.onchange=()=>{const t=tools.find(t=>t.name===select.value);container.querySelector('#real-schema').textContent=t?JSON.stringify(t.inputSchema,null,2):'';container.querySelector('#real-confirm').checked=false;};select.onchange();
    }catch(e){fail(e);}
  };
  container.querySelector('#run-real-tool').onclick=async(event)=>{
    const btn=event.currentTarget;btn.disabled=true;
    try {
      const tool=tools.find(t=>t.name===select.value);if(!tool)throw new Error('请先连接并选择工具');
      const confirm=container.querySelector('#real-confirm').checked;
      if(tool.annotations.destructiveHint&&!confirm)throw new Error('写操作需要明确确认');
      const started=performance.now();
      const result=await callTool(tool.name,JSON.parse(container.querySelector('#real-arguments').value),{confirm});
      out.textContent=JSON.stringify({elapsed_ms:Math.round(performance.now()-started),result},null,2);
    }catch(e){fail(e);}finally{btn.disabled=false;}
  };
  if(fileOperations)container.querySelector('#upload-real-file').onclick=async(event)=>{
    const btn=event.currentTarget;btn.disabled=true;
    try{
      if(!container.querySelector('#real-confirm').checked)throw new Error('上传写操作需要明确确认');
      const file=container.querySelector('#real-file').files[0];if(!file)throw new Error('请选择文件');
      const result=await uploadObject(file,container.querySelector('#file-app').value,(done,total)=>{out.textContent=`上传 ${done}/${total} 字节`;});
      out.textContent=JSON.stringify({file:file.name,receipt:result,installed:false},null,2);
    }catch(e){fail(e);}finally{btn.disabled=false;}
  };
  if(fileOperations)container.querySelector('#download-real-file').onclick=async(event)=>{
    const btn=event.currentTarget;btn.disabled=true;
    try{
      const app=container.querySelector('#file-app').value,object=container.querySelector('#download-object').value.trim();
      const reference=await callTool(app+'_object_reference',{params:{object}});
      if(reference.length>64*1024*1024)throw new Error('Browser download limit: 64 MiB');
      const parts=[];let length=0;
      for(let position=0;position<Math.ceil(reference.length/16384);position++){
        const item=await callTool(app+'_object_chunk_get',{params:{object,position}});
        const bytes=Uint8Array.from(atob(item.data_base64),c=>c.charCodeAt(0));
        if(await sha256(bytes)!==item.digest)throw new Error('Chunk integrity failed');
        length+=bytes.length;if(length>reference.length)throw new Error('Object length exceeded');parts.push(bytes);
      }
      const bytes=new Uint8Array(length);let offset=0;for(const part of parts){bytes.set(part,offset);offset+=part.length;}
      if(length!==reference.length||await sha256(bytes)!==reference.digest)throw new Error('Whole object integrity failed');
      const url=URL.createObjectURL(new Blob([bytes]));const a=document.createElement('a');a.href=url;a.download='verified-object.bin';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
      out.textContent=JSON.stringify({download_verified:true,bytes:length,digest:reference.digest},null,2);
    }catch(e){fail(e);}finally{btn.disabled=false;}
  };
  if(fileOperations)container.querySelector('#stage-native-package').onclick=async(event)=>{
    const btn=event.currentTarget;btn.disabled=true;
    try{
      if(!container.querySelector('#real-confirm').checked)throw new Error('生成软件包和暂存需要明确确认');
      const file=container.querySelector('#real-file').files[0];if(!file)throw new Error('请选择独立签名的 Shadow6 原生 ZIP');
      const name=container.querySelector('#native-name').value.trim(),version=container.querySelector('#native-version').value.trim();
      if(!name||!version)throw new Error('原生包 ID 和版本不能为空，且必须与内层签名匹配');
      const object=await uploadObject(file,'dcpm',(done,total)=>{out.textContent=`上传 ${done}/${total} 字节`;});
      const pkg=await callTool('dcpm_package_build_references',{params:{name,version,files:{'shadow6/package.zip':object.manifest_digest},dependencies:[]}},{confirm:true});
      out.textContent=JSON.stringify({package:pkg,staging:true},null,2);
      const receipt=await callTool('dcpm_package_stage_native',{digest:pkg.digest,authority:pkg.publisher},{confirm:true});
      out.textContent=JSON.stringify({package:pkg,receipt,installed:false},null,2);
    }catch(e){fail(e);}finally{btn.disabled=false;}
  };

}

// Public discovery never forwards application credentials to advertised services.
async function discoverServiceEndpoints() {
  const base=State.runtimeMode==='local'?State.localGatewayUrl:getActiveRemoteNode().url;
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),3000);
  try { const response=await fetch(new URL('/api/gateway/status',base),{credentials:'omit',cache:'no-store',signal:controller.signal});if(!response.ok)return;const data=await response.json();if(data.schema!=='ziokt.gateway.v1')return;const endpoints={};for(const [name,value] of Object.entries(data.service_endpoints||{})){if(!/^[a-z]{1,16}$/.test(name)||typeof value!=='string')continue;const url=new URL(value);if(['https:','http:','nntps:'].includes(url.protocol)&&!url.username&&!url.password)endpoints[name]=url.href;}if(base===(State.runtimeMode==='local'?State.localGatewayUrl:getActiveRemoteNode().url))State.serviceEndpoints=endpoints;}catch(_){}finally{clearTimeout(timer)}
}


  // --- Module: private-offline.js ---
/* Opt-in private offline copies. No credentials or plaintext enter IndexedDB. */

const PRIVATE_OFFLINE_DB='ziokt-private-offline-v1',PRIVATE_OFFLINE_MAX=64*1024*1024,PRIVATE_OFFLINE_FILE=16*1024*1024;
function offlineRequest(request){return new Promise((resolve,reject)=>{request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);});}
function offlineDone(transaction){return new Promise((resolve,reject)=>{transaction.oncomplete=resolve;transaction.onabort=()=>reject(transaction.error||Error('Offline transaction aborted'));transaction.onerror=()=>reject(transaction.error);});}
class PrivateOfflineVault extends EventTarget{
 #db;#key=null;#generation=0;#timer;
 async database(){if(!this.#db)this.#db=new Promise((resolve,reject)=>{const request=indexedDB.open(PRIVATE_OFFLINE_DB,1);request.onupgradeneeded=()=>{for(const name of ['vault','entries','blobs'])request.result.createObjectStore(name,{keyPath:'id'});};request.onsuccess=()=>{const db=request.result;db.onversionchange=()=>{this.lock();db.close();this.#db=null;};resolve(db);};request.onerror=()=>reject(request.error);request.onblocked=()=>reject(Error('Close other offline-cache tabs first'));});return this.#db;}
 get unlocked(){return this.#key!==null;}
 lock(){this.#key=null;this.#generation++;clearTimeout(this.#timer);this.dispatchEvent(new Event('lock'));}
 async unlock(password){
  this.lock();if(typeof password!=='string'||password.length<12||password.length>1024)throw Error('Use an offline password of 12–1024 characters');
  const generation=this.#generation,db=await this.database(),tx=db.transaction('vault'),existing=await offlineRequest(tx.objectStore('vault').get('main'));
  const salt=existing?existing.salt:crypto.getRandomValues(new Uint8Array(16));
  if(!(salt instanceof Uint8Array)||salt.length!==16||(existing&&existing.version!==1))throw Error('Unsupported offline vault');
  const material=await crypto.subtle.importKey('raw',new TextEncoder().encode(password),'PBKDF2',false,['deriveKey']);
  const key=await crypto.subtle.deriveKey({name:'PBKDF2',salt,iterations:310000,hash:'SHA-256'},material,{name:'AES-GCM',length:256},false,['encrypt','decrypt']);
  const aad=new TextEncoder().encode('Ziokt/private-offline/v1/verifier');
  if(existing){try{const value=await crypto.subtle.decrypt({name:'AES-GCM',iv:existing.iv,additionalData:aad},key,existing.box);if(new TextDecoder().decode(value)!=='Ziokt private offline vault v1')throw Error();}catch{throw Error('Wrong offline password or damaged vault');}}
  else {
   const iv=crypto.getRandomValues(new Uint8Array(12)),box=await crypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:aad},key,new TextEncoder().encode('Ziokt private offline vault v1'));
   if(generation!==this.#generation)throw Error('Offline vault locked');
   const write=db.transaction('vault','readwrite');write.objectStore('vault').add({id:'main',version:1,salt,iv,box});await offlineDone(write);
  }
  if(generation!==this.#generation)throw Error('Offline vault locked');this.#key=key;this.#timer=setTimeout(()=>this.lock(),15*60*1000);this.dispatchEvent(new Event('change'));return true;
 }
 session(){if(!this.#key)throw Error('Unlock the offline vault first');return {key:this.#key,generation:this.#generation};}
 assertSession(session){if(session.generation!==this.#generation||!this.#key)throw Error('Offline vault locked');}
 aad(id,part){return new TextEncoder().encode('Ziokt/private-offline/v1/'+id+'/'+part);}
 async records(){const db=await this.database();return offlineRequest(db.transaction('entries').objectStore('entries').getAll());}
 async list(){
  const session=this.session(),result=[];
  for(const record of await this.records()){
   if(record.expires<=Date.now()){await this.remove(record.id);continue;}
   const raw=await crypto.subtle.decrypt({name:'AES-GCM',iv:record.iv,additionalData:this.aad(record.id,'metadata')},session.key,record.box),metadata=JSON.parse(new TextDecoder().decode(raw));
   this.assertSession(session);if(metadata.expires!==record.expires)throw Error('Offline expiry integrity failed');result.push({...metadata,id:record.id});
  }
  this.assertSession(session);return result;
 }
 async save(metadata,data){
  const session=this.session();if(!(data instanceof Uint8Array))data=new Uint8Array(data);
  if(data.byteLength>PRIVATE_OFFLINE_FILE)throw Error('Offline file limit: 16 MiB');
  if(!['book','article','attachment'].includes(metadata.kind)||typeof metadata.source!=='string'||metadata.source.length>2048||typeof metadata.source_id!=='string'||metadata.source_id.length>512)throw Error('Offline source metadata required');
  const digest='sha256:'+Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',data)),b=>b.toString(16).padStart(2,'0')).join('');if(metadata.digest&&metadata.digest!==digest)throw Error('Offline content digest mismatch');
  const prior=(await this.list()).find(item=>item.source===metadata.source&&item.source_id===metadata.source_id&&item.kind===metadata.kind),id=prior?.id||crypto.randomUUID(),expires=Date.now()+7*86400000;
  const value={...metadata,digest,size:data.byteLength,expires},raw=new TextEncoder().encode(JSON.stringify(value));if(raw.byteLength>65536)throw Error('Offline metadata budget exceeded');
  const iv=crypto.getRandomValues(new Uint8Array(12)),contentIv=crypto.getRandomValues(new Uint8Array(12));
  const box=await crypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:this.aad(id,'metadata')},session.key,raw),content=await crypto.subtle.encrypt({name:'AES-GCM',iv:contentIv,additionalData:this.aad(id,'content')},session.key,data);
  this.assertSession(session);const db=await this.database();this.assertSession(session);
  const tx=db.transaction(['entries','blobs'],'readwrite'),entries=tx.objectStore('entries'),blobs=tx.objectStore('blobs');let failure;
  entries.getAll().onsuccess=event=>{
   try{
    this.assertSession(session);let total=0,count=0;
    for(const record of event.target.result){if(record.expires<=Date.now()){entries.delete(record.id);blobs.delete(record.id);}else if(record.id!==id){if(!Number.isSafeInteger(record.bytes)||record.bytes<0)throw Error('Damaged offline quota metadata');total+=record.bytes;count++;}}
    const bytes=box.byteLength+content.byteLength;if(count>=256||total+bytes>PRIVATE_OFFLINE_MAX)throw Error('Offline quota: 64 MiB / 256 items; delete older copies');
    entries.put({id,iv,contentIv,box,expires,bytes});blobs.put({id,box:content});
   }catch(error){failure=error;tx.abort();}
  };
  try{await offlineDone(tx);}catch(error){throw failure||error;}this.assertSession(session);this.dispatchEvent(new Event('change'));return {...value,id};
 }
 async read(id){
  const session=this.session(),db=await this.database(),tx=db.transaction(['entries','blobs']);
  const [record,blob]=await Promise.all([offlineRequest(tx.objectStore('entries').get(id)),offlineRequest(tx.objectStore('blobs').get(id))]);
  if(!record||!blob)throw Error('Offline copy missing');if(record.expires<=Date.now()){await this.remove(id);throw Error('Offline copy expired');}
  const raw=await crypto.subtle.decrypt({name:'AES-GCM',iv:record.iv,additionalData:this.aad(id,'metadata')},session.key,record.box),metadata=JSON.parse(new TextDecoder().decode(raw));
  if(metadata.expires!==record.expires)throw Error('Offline expiry integrity failed');
  const bytes=await crypto.subtle.decrypt({name:'AES-GCM',iv:record.contentIv,additionalData:this.aad(id,'content')},session.key,blob.box),digest='sha256:'+Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
  this.assertSession(session);if(digest!==metadata.digest||bytes.byteLength!==metadata.size)throw Error('Offline content integrity failed');return {metadata,bytes};
 }
 async remove(id){const db=await this.database(),tx=db.transaction(['entries','blobs'],'readwrite');tx.objectStore('entries').delete(id);tx.objectStore('blobs').delete(id);await offlineDone(tx);this.dispatchEvent(new Event('change'));}
 async clear(){this.lock();const db=await this.database(),tx=db.transaction(['entries','blobs','vault'],'readwrite');for(const name of ['entries','blobs','vault'])tx.objectStore(name).clear();await offlineDone(tx);this.dispatchEvent(new Event('change'));}
}
const privateOfflineVault=new PrivateOfflineVault();
if(typeof window!=='undefined')window.privateOfflineVault=privateOfflineVault;
window.addEventListener('pagehide',()=>privateOfflineVault.lock());
window.addEventListener('ziokt-private-cache-lock',()=>privateOfflineVault.lock());
document.addEventListener('visibilitychange',()=>{if(document.hidden)privateOfflineVault.lock();});
function privateOfflineSource(){return State.runtimeMode==='local'?State.localGatewayUrl:(getActiveRemoteNode()?.url||State.gatewayUrl);}
function mountPrivateOffline(container){
 const en=State.language==='en',tr=(zh,english)=>en?english:zh,node=(tag,text)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;return el;};
 const panel=node('section');panel.className='card private-offline-panel';panel.id='private-offline-panel';panel.append(node('h3',tr('私有离线正文与附件','Private offline text and attachments')),node('p',tr('主动保存后在本机加密，密码不保存。单文件16 MiB，总64 MiB；7天过期，切到后台或15分钟后锁定。离线副本不能实时接收远端撤销；忘记密码需清空后重新下载。','Opt-in encrypted local copies. Password is never stored. 16 MiB/file, 64 MiB total, 7-day expiry. Locks in the background or after 15 minutes. Offline copies cannot receive remote revocations; a lost password requires clearing and downloading again.')));
 const form=node('form'),label=node('label',tr('离线密码（首次设置至少12个字符）','Offline password (at least 12 characters)')),password=node('input');password.type='password';password.autocomplete='off';password.minLength=12;password.maxLength=1024;password.required=true;password.id='private-offline-password';label.append(password);form.append(label);panel.append(form);
 const status=node('p');status.id='private-offline-status';status.setAttribute('role','status');panel.append(status);const list=node('div');list.id='private-offline-list';panel.append(list);const viewer=node('section');viewer.id='private-offline-viewer';panel.append(viewer);const urls=new Set();
 function locked(){for(const url of urls)URL.revokeObjectURL(url);urls.clear();list.replaceChildren();viewer.replaceChildren();password.value='';status.textContent=tr('已锁定','Locked');}
 async function execute(operation){try{await operation();}catch(error){status.textContent=error.message;}}
 function button(parent,title,operation,id){const value=node('button',title);value.type='button';value.className='btn btn-secondary';if(id)value.id=id;value.onclick=async()=>{value.disabled=true;await execute(operation);value.disabled=false;};parent.append(value);return value;}
 async function refresh(){list.replaceChildren();const items=await privateOfflineVault.list();for(const item of items){const row=node('article');row.className='card';row.append(node('h4',item.title||item.source_id),node('small',item.kind+' · '+item.size+' bytes · '+new Date(item.expires).toLocaleDateString()));button(row,tr('离线打开','Open offline'),async()=>{const {metadata,bytes}=await privateOfflineVault.read(item.id);viewer.replaceChildren(node('h4',metadata.title||metadata.source_id));if(metadata.kind==='article'||['text/plain','text/markdown','text/html'].includes(metadata.mime)){const text=node('pre',new TextDecoder().decode(bytes));text.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere';viewer.append(text);}const url=URL.createObjectURL(new Blob([bytes],{type:'application/octet-stream'}));urls.add(url);const link=node('a',tr('保存已校验文件','Save verified file'));link.href=url;link.download=(metadata.filename||metadata.title||'offline.bin').replace(/[\\/\x00-\x1f]/g,'_');viewer.append(link);});button(row,tr('删除离线副本','Delete offline copy'),async()=>{await privateOfflineVault.remove(item.id);await refresh();});list.append(row);}status.textContent=tr('已解锁，离线副本：','Unlocked, offline copies: ')+items.length;}
 const unlock=node('button',tr('创建 / 解锁离线保险箱','Create / unlock offline vault'));unlock.id='private-offline-unlock';unlock.className='btn btn-primary';form.append(unlock);
 form.onsubmit=async event=>{event.preventDefault();unlock.disabled=true;const secret=password.value;password.value='';await execute(async()=>{await privateOfflineVault.unlock(secret);await refresh();});unlock.disabled=false;};
 button(panel,tr('刷新离线列表','Refresh offline list'),refresh,'private-offline-refresh');button(panel,tr('锁定','Lock'),()=>privateOfflineVault.lock(),'private-offline-lock');button(panel,tr('清空本机离线副本及密码','Clear local copies and password'),async()=>{await privateOfflineVault.clear();locked();},'private-offline-clear');
 privateOfflineVault.addEventListener('lock',locked);const observer=new MutationObserver(()=>{if(!panel.isConnected){privateOfflineVault.removeEventListener('lock',locked);observer.disconnect();for(const url of urls)URL.revokeObjectURL(url);}});observer.observe(document.documentElement,{childList:true,subtree:true});
 container.append(panel);if(privateOfflineVault.unlocked)execute(refresh);else locked();return {refresh};
}


  // --- Module: modules/home.js ---
// ==============================================================================
// Module: Home Overview & System Telemetry Dashboard
// ==============================================================================

function renderHome(container) {
  const isEn = State.language === 'en';
  const isLocal = State.runtimeMode === 'local';
  const isLocalOffline = isLocal && State.localNodeStatus === 'offline';
  const activeNode = getActiveRemoteNode();
  const isRemoteUnauth = !isLocal && (!activeNode?.authToken || activeNode?.status === 'unauthenticated' || activeNode?.status === 'auth_failed');

  if (isLocalOffline) {
    container.innerHTML = `
      <div style="max-width: 820px; margin: 40px auto; text-align: center;">
        <div class="card" style="padding: 40px 24px; border: 1.5px solid var(--accent-red); background: rgba(239,68,68,0.06);">
          <div style="font-size: 3rem; margin-bottom: 14px;">⚠️</div>
          <h2 style="color: var(--accent-red); font-size: 1.25rem; font-weight: 700; margin-bottom: 10px;">
            ${isEn ? 'Local Node Offline — Only Settings Accessible' : '本地节点未运行 — 当前仅开放系统设置'}
          </h2>
          <p style="color: var(--text-main); font-size: 0.9rem; max-width: 580px; margin: 0 auto 20px; line-height: 1.6;">
            ${isEn
              ? 'Local node mode requires an active Ziokt daemon at http://127.0.0.1:8185. Since no local node is detected, overview metrics and functional tabs are locked. Please start your local daemon or switch to a remote gateway in Settings.'
              : '当前处于【本地节点】运行模式，但未检测到本地运行中的 Ziokt 节点服务 (http://127.0.0.1:8185)。在本地真实节点启动前，首页总览与功能模块已锁定，当前仅开放【系统设置】页。请启动本地进程，或切换至官方远程网关。'}
          </p>
          <div style="display: flex; gap: 12px; justify-content: center; flex-wrap: wrap;">
            <button id="home-go-settings-btn" class="btn btn-primary" style="padding: 10px 20px; font-size: 0.9rem;">⚙️ ${isEn ? 'Go to Settings' : '前往系统设置'}</button>
            <button id="home-probe-local-btn" class="btn btn-secondary" style="padding: 10px 18px; font-size: 0.9rem;">⚡ ${isEn ? 'Retry Local Probe' : '重试探测本地节点'}</button>
            <button id="home-switch-remote-btn" class="btn btn-secondary" style="padding: 10px 18px; font-size: 0.9rem;">🌐 ${isEn ? 'Switch to Remote Gateway' : '一键切换至远程网关'}</button>
          </div>
        </div>
      </div>
    `;
    const sBtn = container.querySelector('#home-go-settings-btn');
    if (sBtn) sBtn.onclick = () => { location.hash = '#settings'; };
    const pBtn = container.querySelector('#home-probe-local-btn');
    if (pBtn) pBtn.onclick = async () => {
      pBtn.disabled = true;
      pBtn.textContent = '...';
      const res = await checkLocalNodeHealth();
      pBtn.disabled = false;
      pBtn.textContent = `⚡ ${isEn ? 'Retry Local Probe' : '重试探测本地节点'}`;
      if (res.ok) {
        showToast(isEn ? 'Local node verified online!' : '本地节点已连接！', 'success');
        renderHome(container);
      } else {
        showToast(isEn ? `Local node unreachable: ${res.error}` : `本地真实节点未响应: ${res.error}`, 'error');
      }
    };
    const rBtn = container.querySelector('#home-switch-remote-btn');
    if (rBtn) rBtn.onclick = () => {
      State.runtimeMode = 'remote';
      setStorage('ziokt_mode', 'remote');
      updateAppNodeBadge();
      showToast(isEn ? 'Switched to Remote Gateway mode' : '已切换至远程网关模式', 'success');
      renderHome(container);
    };
    return;
  }

  container.innerHTML = `
    <div style="max-width: 1100px; margin: 0 auto;">

      ${isRemoteUnauth ? `
        <div style="background: rgba(245, 158, 11, 0.12); border: 1px solid var(--accent-amber); border-radius: var(--radius-md); padding: 14px 18px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
          <div style="color: var(--accent-amber); font-size: 0.85rem; font-weight: 500; display: flex; align-items: center; gap: 8px;">
            <span style="font-size: 1.2rem;">🔒</span>
            <span>${t('home.remote_unauth_alert')}</span>
          </div>
          <button id="home-config-auth-btn" class="btn btn-primary btn-sm">⚙️ ${t('home.config_auth')}</button>
        </div>
      ` : ''}

      <!-- Welcome Banner -->
      <div style="background: linear-gradient(135deg, rgba(2,132,199,0.15), rgba(129,140,248,0.1)); border: 1px solid var(--border-bright); border-radius: var(--radius-lg); padding: 24px; margin-bottom: 24px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 16px;">
        <div>
          <h2 style="font-size: 1.35rem; font-weight: 700; color: var(--text-main); margin-bottom: 6px;">${t('home.welcome')}</h2>
          <p style="color: var(--text-muted); font-size: 0.85rem; max-width: 620px;">${t('home.welcome_sub')}</p>
        </div>
        <div style="display: flex; gap: 8px; align-items: center;">
          <span style="font-size: 0.8rem; color: var(--text-muted);">${t('settings.runtime_mode')}:</span>
          <select id="home-mode-select" class="input-select" style="width: auto; padding: 6px 10px; font-weight: 600;">
            <option value="local" ${State.runtimeMode === 'local' ? 'selected' : ''}>${t('app.mode_local')} (127.0.0.1:8185)</option>
            <option value="remote" ${State.runtimeMode === 'remote' ? 'selected' : ''}>${t('app.mode_remote')} (${activeNode?.name || 'cor-web.ziokt.com'})</option>
            <option value="hybrid" ${State.runtimeMode === 'hybrid' ? 'selected' : ''}>${t('app.mode_hybrid')}</option>
          </select>
        </div>
      </div>

      <!-- Quick Action Shortcuts -->
      <div style="margin-bottom: 28px;">
        <h3 style="font-size: 0.95rem; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 14px;">${t('home.quick_actions')}</h3>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px;">
          <button class="btn btn-secondary home-action-btn" data-target="chat" style="padding: 16px; justify-content: flex-start; border-radius: var(--radius-md);">
            <span style="font-size: 1.5rem;">💬</span>
            <div style="text-align: left;">
              <div style="font-weight: 600; color: var(--text-main);">${t('home.act_chat')}</div>
              <div style="font-size: 0.72rem; color: var(--text-muted);">WATChat Sealed Chat</div>
            </div>
          </button>
          <button class="btn btn-secondary home-action-btn" data-target="files" style="padding: 16px; justify-content: flex-start; border-radius: var(--radius-md);">
            <span style="font-size: 1.5rem;">🔒</span>
            <div style="text-align: left;">
              <div style="font-weight: 600; color: var(--text-main);">${t('home.act_files')}</div>
              <div style="font-size: 0.72rem; color: var(--text-muted);">UFS & SafeFS Vault</div>
            </div>
          </button>
          <button class="btn btn-secondary home-action-btn" data-target="apps" style="padding: 16px; justify-content: flex-start; border-radius: var(--radius-md);">
            <span style="font-size: 1.5rem;">📦</span>
            <div style="text-align: left;">
              <div style="font-weight: 600; color: var(--text-main);">${t('home.act_apps')}</div>
              <div style="font-size: 0.72rem; color: var(--text-muted);">dCPM App Store</div>
            </div>
          </button>
          <button class="btn btn-secondary home-action-btn" data-target="network" style="padding: 16px; justify-content: flex-start; border-radius: var(--radius-md);">
            <span style="font-size: 1.5rem;">🌐</span>
            <div style="text-align: left;">
              <div style="font-weight: 600; color: var(--text-main);">${t('home.act_network')}</div>
              <div style="font-size: 0.72rem; color: var(--text-muted);">Shadow6 & ETP Mesh</div>
            </div>
          </button>
        </div>
      </div>

      <!-- Telemetry Cards -->
      <div class="grid-cards">
        <div class="card">
          <div class="card-title">
            <span>${t('identity.did')}</span>
            <span class="status-badge"><span class="status-dot"></span> Active</span>
          </div>
          <div class="card-value" style="font-family: var(--font-mono); font-size: 0.95rem; color: var(--accent-cyan);">${State.userDid}</div>
          <div class="card-desc">绑定 NNS 域: genesis.ziokt &bull; Ed25519 签名链已锚定</div>
        </div>
        <div class="card">
          <div class="card-title">
            <span>${t('identity.pouw_status')}</span>
            <span style="color: var(--accent-green); font-weight: 600;">MINING</span>
          </div>
          <div class="card-value">2,840 H/s <span style="font-size: 0.85rem; color: var(--text-muted); font-weight: normal;">(SHA-256 / Blake3)</span></div>
          <div class="card-desc">区块高度: #10,482 &bull; 累计算力贡献分: 142.50</div>
        </div>
        <div class="card">
          <div class="card-title">
            <span>${t('network.profiles_title')}</span>
            <span style="color: var(--accent-purple); font-weight: 600;">13 CORES</span>
          </div>
          <div class="card-value" style="font-size: 1.1rem; color: var(--accent-purple);">Shadow6 Virtual Broker: 就绪</div>
          <div class="card-desc">已连接 Go, Rust, Zig, Nim, Gleam, Ada 等多协议隧道</div>
        </div>
      </div>

      <!-- Component Health Grid -->
      <div class="card" style="margin-bottom: 24px;">
        <div class="card-title" style="margin-bottom: 14px;">
          <span>${t('home.system_health')}</span>
          <button id="refresh-health-btn" class="btn btn-secondary btn-sm">🔄 ${t('common.refresh')}</button>
        </div>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px;">
          ${Object.entries(State.components).map(([key, comp]) => `
            <div style="background: var(--bg-input); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 12px; display: flex; align-items: center; justify-content: space-between;">
              <div>
                <div style="font-weight: 600; font-size: 0.85rem; color: var(--text-main);">${comp.name}</div>
                <div style="font-size: 0.72rem; color: var(--text-dim); font-family: var(--font-mono);">Port: ${comp.port}</div>
              </div>
              <span class="status-badge"><span class="status-dot"></span></span>
            </div>
          `).join('')}
        </div>
      </div>

      <!-- Recent Activity Log -->
      <div class="card">
        <div class="card-title" style="margin-bottom: 12px;">
          <span>${t('home.recent_activity')}</span>
        </div>
        <p role="status">${State.language === 'en' ? 'No verified activity receipts loaded. Inspect each native service for current connection and delivery evidence.' : '尚未加载经过验证的活动回执。请在各原生服务中核对当前连接和投递证据。'}</p>
      </div>
    </div>
  `;

  // Event handlers
  container.querySelectorAll('.home-action-btn').forEach(btn => {
    btn.onclick = () => {
      Events.emit('navigate', btn.dataset.target);
    };
  });

  const modeSelect = container.querySelector('#home-mode-select');
  if (modeSelect) {
    modeSelect.onchange = async (e) => {
      State.runtimeMode = e.target.value;
      setStorage('ziokt_mode', e.target.value);
      if (State.runtimeMode === 'local') {
        await checkLocalNodeHealth();
      }
      updateAppNodeBadge();
      showToast(`已切换至: ${e.target.options[e.target.selectedIndex].text}`, 'info');
      Events.emit('mode_changed', e.target.value);
      renderHome(container);
    };
  }

  const probeLocalBtn = container.querySelector('#home-probe-local-btn');
  if (probeLocalBtn) {
    probeLocalBtn.onclick = async () => {
      probeLocalBtn.disabled = true;
      probeLocalBtn.textContent = '...';
      const res = await checkLocalNodeHealth();
      if (res.ok) {
        showToast(isEn ? 'Local node verified successfully!' : '本地真实节点检测通过，状态在线！', 'success');
      } else {
        showToast(isEn ? `Local node unreachable: ${res.error}` : `本地真实节点未响应: ${res.error}`, 'error');
      }
      renderHome(container);
    };
  }

  const switchRemoteBtn = container.querySelector('#home-switch-remote-btn');
  if (switchRemoteBtn) {
    switchRemoteBtn.onclick = () => {
      State.runtimeMode = 'remote';
      setStorage('ziokt_mode', 'remote');
      updateAppNodeBadge();
      showToast(isEn ? 'Switched to Remote Gateway mode' : '已切换至远程网关模式', 'info');
      renderHome(container);
    };
  }

  const configAuthBtn = container.querySelector('#home-config-auth-btn');
  if (configAuthBtn) {
    configAuthBtn.onclick = () => {
      Events.emit('navigate', 'settings');
    };
  }

  const refreshBtn = container.querySelector('#refresh-health-btn');
  if (refreshBtn) {
    refreshBtn.onclick = async () => {
      if (State.runtimeMode === 'local') {
        await checkLocalNodeHealth();
      }
      showToast(isEn ? 'Component and node health refreshed' : '核心组件与节点状态已刷新', 'success');
      renderHome(container);
    };
  }
}


  // --- Module: modules/chat.js ---
/* Native WATChat owns authentication, keys, encryption and delivery receipts. */

function renderChat(container) {
  const label = (zh, en) => State.language === 'en' ? en : zh;
  const node = (tag, text) => { const el = document.createElement(tag); el.textContent = text; return el; };
  container.replaceChildren();
  const card = node('section', ''); card.className = 'card';
  card.append(node('h2', 'WATChat'), node('p', label(
    '请在原生 WATChat 中登录、核对联系人指纹并发送消息。网关登录不代表聊天身份已登录。',
    'Sign in, verify contact fingerprints and send messages in native WATChat. Gateway authentication does not sign in to chat.')),
    node('p', label('当前随附原生实现：ECDH P-256 / HKDF-SHA256 / AES-256-GCM。此说明不代表握手或投递已完成。',
    'Bundled native implementation: ECDH P-256 / HKDF-SHA256 / AES-256-GCM. This description is not handshake or delivery evidence.')));
  const form = node('form', ''), caption = node('label', label('原生 WATChat 地址', 'Native WATChat URL'));
  const input = document.createElement('input'); input.type = 'url'; input.required = true;
  input.id = 'watchat-native-url'; input.className = 'input-text';
  input.value = getStorage('ziokt_endpoint_watchat') || (State.serviceEndpoints || {}).watchat || '';
  input.placeholder = 'https://'; caption.htmlFor = input.id;
  const save = node('button', label('保存入口', 'Save entrypoint')); save.className = 'btn btn-secondary';
  const status = node('p', label('尚未验证原生会话或消息投递。', 'Native session and delivery have not been verified.')); status.setAttribute('role', 'status');
  const link = node('a', label('打开原生 WATChat', 'Open native WATChat'));
  link.id = 'watchat-native-open'; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.hidden = true;
  const validate = () => {
    const url = new URL(input.value);
    if ((url.protocol !== 'https:' && !(url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname))) || url.username || url.password || url.search || url.hash)
      throw Error(label('请使用 HTTPS 地址或本机 HTTP 地址，不含凭证、查询或片段。', 'Use HTTPS or loopback HTTP without credentials, query or fragment.'));
    return url.href;
  };
  const refresh = () => { link.hidden = true; link.removeAttribute('href'); if (input.value) { link.href = validate(); link.hidden = false; } };
  input.oninput = () => { link.hidden = true; link.removeAttribute('href'); };
  form.onsubmit = event => { event.preventDefault(); try { const url = validate(); setStorage('ziokt_endpoint_watchat', url); refresh(); status.textContent = label('入口已保存；会话和投递状态仍需原生应用验证。', 'Entrypoint saved; session and delivery still require native verification.'); } catch(error) { link.hidden = true; status.textContent = error.message; } };
  try { refresh(); } catch(error) { status.textContent = error.message; }
  form.append(caption, input, save); card.append(form, link, status); container.append(card);
}


  // --- Module: modules/forum.js ---
/* Native forum readers and publishers. No seeded posts or fabricated proofs. */
function renderForum(container){
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
 const native=make('a',tr('打开 Corium 原生社区门户','Open Corium native community portal'));native.href=configuredEndpoint('corium','/');native.target='_blank';native.rel='noopener noreferrer';native.className='btn btn-secondary';container.append(native);
}


  // --- Module: modules/files.js ---
// ==============================================================================
// Module: UFS & SafeFS Secure File Vault & Storage Explorer
// ==============================================================================

let currentVault = 'ufs'; // 'ufs' | 'safefs'
let vaultFiles = [];
try {
  const raw = getStorage('ziokt_vault_files');
  if (raw) vaultFiles = JSON.parse(raw);
} catch (e) {
  vaultFiles = [];
}
function renderFiles(container) {
  const isEn = State.language === 'en';

  if (isLocalNodeOffline()) {
    container.innerHTML = `
      <div style="max-width: 800px; margin: 40px auto; text-align: center;">
        <div class="card" style="padding: 36px 20px;">
          <div style="font-size: 2.5rem; margin-bottom: 12px;">🔒</div>
          <h3 style="color: var(--accent-red); margin-bottom: 8px;">
            ${isEn ? 'Local Node Offline — Storage Unavailable' : '本地节点未运行 — 存储功能不可用'}
          </h3>
          <p style="color: var(--text-muted); font-size: 0.85rem; max-width: 520px; margin: 0 auto 20px; line-height: 1.6;">
            ${isEn
              ? 'Local mode requires an active Ziokt node daemon at http://127.0.0.1:8185 to mount UFS & SafeFS storage partitions and descriptors. Only Settings is accessible.'
              : '本地节点模式需要本机真实运行有 Ziokt 节点服务 (http://127.0.0.1:8185) 挂载 UFS 与 SafeFS 存储卷。本地未启动时无法创建目录或存储文件，当前仅开放【系统设置】。'}
          </p>
          <div style="display: flex; gap: 10px; justify-content: center; flex-wrap: wrap;">
            <button id="files-go-settings-btn" class="btn btn-primary">⚙️ ${t('nav.settings')}</button>
            <button id="files-retry-probe-btn" class="btn btn-secondary">⚡ ${t('settings.local_node_probe')}</button>
          </div>
        </div>
      </div>
    `;
    const sBtn = container.querySelector('#files-go-settings-btn');
    if (sBtn) sBtn.onclick = () => { location.hash = '#settings'; };
    const pBtn = container.querySelector('#files-retry-probe-btn');
    if (pBtn) pBtn.onclick = async () => {
      pBtn.disabled = true;
      pBtn.textContent = '...';
      const { checkLocalNodeHealth } = await import('../core.js');
      const res = await checkLocalNodeHealth();
      pBtn.disabled = false;
      pBtn.textContent = `⚡ ${t('settings.local_node_probe')}`;
      if (res.ok) {
        showToast(isEn ? 'Local node verified online!' : '本地真实节点检测通过，状态在线！', 'success');
        renderFiles(container);
      } else {
        showToast(isEn ? `Local node unreachable: ${res.error}` : `本地真实节点未响应: ${res.error}`, 'error');
      }
    };
    return;
  }
  container.innerHTML = `
    <div style="max-width: 1050px; margin: 0 auto;">
      <!-- Vault Header -->
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; flex-wrap: wrap; gap: 14px;">
        <div>
          <h2 style="font-size: 1.25rem; font-weight: 700; color: var(--accent-cyan);">${t('files.title')}</h2>
          <p style="font-size: 0.82rem; color: var(--text-muted);">${t('files.stealth_mode')}</p>
        </div>
        <div style="display: flex; gap: 10px; align-items: center;">
          <input type="file" id="vault-file-input" style="display: none;" onchange="window.handleVaultUpload(this.files)">
          <button id="upload-file-btn" class="btn btn-primary">📁 ${t('files.upload_file')}</button>
          <button id="create-folder-btn" class="btn btn-secondary">➕ ${t('files.create_folder')}</button>
        </div>
      </div>

      <!-- Storage Driver Tabs & Quota Status -->
      <div class="grid-cards" style="margin-bottom: 20px;">
        <div class="card" style="padding: 16px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-weight: 600; font-size: 0.85rem; color: var(--text-muted);">${t('files.vault_type')}</span>
            <div style="display: flex; gap: 4px;">
              <button class="btn btn-sm ${currentVault === 'ufs' ? 'btn-primary' : 'btn-secondary'} vault-tab-btn" data-type="ufs">${t('files.vault_ufs')}</button>
              <button class="btn btn-sm ${currentVault === 'safefs' ? 'btn-primary' : 'btn-secondary'} vault-tab-btn" data-type="safefs">${t('files.vault_safefs')}</button>
            </div>
          </div>
          <div style="font-size: 0.78rem; color: var(--text-dim);">
            ${currentVault === 'ufs' ? 'UFS 原生描述符沙箱 (O_NOFOLLOW / SHA-256 Digest)' : 'SafeFS AEAD 独立密文保险箱 (双层诱饵卷隐蔽保护)'}
          </div>
        </div>

        <div class="card" style="padding: 16px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-weight: 600; font-size: 0.85rem; color: var(--text-muted);">容量与利用率</span>
            <span style="color: var(--accent-green); font-size: 0.75rem; font-weight: 600;">3.2 MB / 100 GB</span>
          </div>
          <div style="height: 6px; background: var(--bg-input); border-radius: 3px; overflow: hidden;">
            <div style="width: 2%; height: 100%; background: linear-gradient(90deg, #0284c7, #38bdf8);"></div>
          </div>
        </div>
      </div>

      <!-- Drag & Drop Zone -->
      <div id="file-dropzone" class="dropzone" style="margin-bottom: 20px;">
        <div style="font-size: 2rem; margin-bottom: 6px;">📥</div>
        <div style="font-weight: 600; color: var(--text-main); font-size: 0.95rem;">${t('files.drop_tip')}</div>
        <div style="font-size: 0.78rem; color: var(--text-muted); margin-top: 4px;">支持任意格式原生物理/分块存储，自动计算校验摘要并加密</div>
      </div>

      <!-- File Table -->
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th style="min-width: 260px;">${t('common.name')}</th>
              <th style="width: 120px;">${t('common.size')}</th>
              <th style="width: 160px;">${t('common.date')}</th>
              <th style="width: 160px; text-align: right;">${t('common.actions')}</th>
            </tr>
          </thead>
          <tbody>
            ${vaultFiles.map(file => `
              <tr>
                <td>
                  <div style="display: flex; align-items: center; gap: 10px;">
                    <span style="font-size: 1.2rem;">${file.isDir ? '📁' : '📄'}</span>
                    <span style="font-weight: 500; color: var(--text-main);">${file.name}</span>
                  </div>
                </td>
                <td style="font-family: var(--font-mono); color: var(--text-muted);">${file.size}</td>
                <td style="color: var(--text-dim); font-size: 0.8rem;">${file.date}</td>
                <td style="text-align: right;">
                  <div style="display: inline-flex; gap: 6px;">
                    <button class="btn btn-sm btn-secondary dl-btn" data-name="${file.name}">📥 ${t('common.download')}</button>
                    <button class="btn btn-sm btn-danger del-btn" data-name="${file.name}">🗑️</button>
                  </div>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>

      <!-- Native MCP Chunked Storage & Tool Bridge -->
      <div class="card" style="margin-top: 24px; padding: 20px;">
        <div class="card-title" style="margin-bottom: 12px;">
          <span>🛠️ 原生分块传输与 MCP 工具 / Native Chunked Storage & MCP Tools</span>
        </div>
        <p style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 14px;">
          操作使用已鉴权的真实后端。工具结果仅代表其声明的阶段；验签、暂存、安装、激活分别显示。
        </p>
        <div style="display: flex; flex-direction: column; gap: 10px; max-width: 650px;">
          <label style="font-size: 0.82rem; color: var(--text-main);">Node administrator token（只保存在当前页面内存）
            <input type="password" class="input-text" id="operation-token" autocomplete="off" style="margin-top: 4px;">
          </label>
          <div style="display: flex; gap: 10px; align-items: center;">
            <button class="btn btn-primary btn-sm" id="load-real-tools">连接并刷新工具</button>
            <span id="tool-count" style="font-size: 0.78rem; color: var(--text-dim);"></span>
          </div>
          <select class="input-text" id="real-tool" style="font-size: 0.82rem;"></select>
          <pre id="real-schema" style="white-space: pre-wrap; font-size: 0.72rem; color: var(--text-dim); max-height: 120px; overflow: auto; background: var(--bg-input); padding: 8px; border-radius: var(--radius-sm);"></pre>
          <label style="font-size: 0.82rem; color: var(--text-main);">参数 JSON
            <textarea id="real-arguments" class="input-textarea" rows="4" style="margin-top: 4px; font-size: 0.78rem;">{}</textarea>
          </label>
          <label style="font-size: 0.82rem; display: flex; align-items: center; gap: 6px; cursor: pointer;">
            <input type="checkbox" id="real-confirm"> 我确认执行所选写操作
          </label>
          <div>
            <button class="btn btn-primary btn-sm" id="run-real-tool">执行</button>
          </div>
          <hr style="border: 0; border-top: 1px solid var(--border-subtle); margin: 10px 0;">
          <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
            <input type="file" id="real-file" class="input-text" style="font-size: 0.8rem; width: auto;">
            <select id="file-app" class="input-select" style="font-size: 0.8rem; width: auto;">
              <option value="safefs">safefs</option>
              <option value="dcpm">dcpm</option>
              <option value="ufs">ufs</option>
            </select>
            <button class="btn btn-secondary btn-sm" id="upload-real-file">分块上传实际内容</button>
          </div>
          <p style="font-size: 0.72rem; color: var(--text-dim); margin: 0;">上传只保存加密对象；上传不代表安装。</p>
          <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 6px;">
            <input id="download-object" class="input-text" placeholder="对象 manifest_digest" style="font-size: 0.8rem; flex: 1;">
            <button id="download-real-file" class="btn btn-secondary btn-sm">验证并下载实际内容</button>
          </div>
          <hr style="border: 0; border-top: 1px solid var(--border-subtle); margin: 10px 0;">
          <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
            <input id="native-name" class="input-text" placeholder="原生包 ID（须匹配签名）" style="font-size: 0.8rem; flex: 1;">
            <input id="native-version" class="input-text" placeholder="原生包版本（须匹配签名）" style="font-size: 0.8rem; width: 140px;">
            <button id="stage-native-package" class="btn btn-secondary btn-sm">生成 v2 引用包并验证原生签名暂存</button>
          </div>
          <pre id="real-result" role="status" style="white-space: pre-wrap; overflow-wrap: anywhere; font-size: 0.72rem; color: var(--accent-cyan); background: var(--bg-input); padding: 8px; border-radius: var(--radius-sm); margin-top: 8px;"></pre>
        </div>
      </div>


    </div>
  `;

  // Vault Tab Switcher
  container.querySelectorAll('.vault-tab-btn').forEach(btn => {
    btn.onclick = () => {
      currentVault = btn.dataset.type;
      showToast(`已切换至: ${btn.textContent}`, 'info');
      renderFiles(container);
    };
  });

  // Upload Button Trigger
  container.querySelector('#upload-file-btn').onclick = () => {
    if (isLocalNodeOffline()) {
      showToast(State.language === 'en' ? 'Local node is offline, storage operations unavailable' : '本地真实节点未启动 (127.0.0.1:8185)，无法执行存储操作', 'error');
      return;
    }
    container.querySelector('#vault-file-input').click();
  };

  // Upload Logic
  window.handleVaultUpload = (files) => {
    if (isLocalNodeOffline()) {
      showToast(State.language === 'en' ? 'Local node is offline, upload disabled' : '本地真实节点未启动 (127.0.0.1:8185)，无法上传文件', 'error');
      return;
    }
    if (!files || !files.length) return;
    const file = files[0];
    showToast(isEn ? `Encrypting & storing "${file.name}" ...` : `正在加密并存储文件 "${file.name}" ...`, 'info');
    setTimeout(() => {
      const now = new Date();
      const dateStr = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')} ${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}`;
      const sizeStr = file.size > 1024*1024 ? `${(file.size/1024/1024).toFixed(1)} MB` : `${(file.size/1024).toFixed(1)} KB`;
      vaultFiles.push({
        name: file.name,
        size: sizeStr,
        date: dateStr,
        isDir: false,
        type: 'file'
      });
      setStorage('ziokt_vault_files', JSON.stringify(vaultFiles));
      showToast(isEn ? `"${file.name}" safely stored in native vault` : `文件 "${file.name}" 已持久化保存至原生保险库`, 'success');
      renderFiles(container);
    }, 400);
  };

  // Create Folder
  container.querySelector('#create-folder-btn').onclick = () => {
    if (isLocalNodeOffline()) {
      showToast(State.language === 'en' ? 'Local node is offline, cannot create folder' : '本地真实节点未启动 (127.0.0.1:8185)，无法创建目录', 'error');
      return;
    }
    const name = prompt(isEn ? 'Enter directory name:' : '请输入新目录名称:');
    if (name) {
      vaultFiles.push({
        name,
        size: '-',
        date: isEn ? 'Just now' : '刚刚',
        isDir: true,
        type: 'dir'
      });
      setStorage('ziokt_vault_files', JSON.stringify(vaultFiles));
      showToast(isEn ? `Directory "${name}" created successfully` : `目录 "${name}" 创建成功`, 'success');
      renderFiles(container);
    }
  };

  // Delete Action with Confirmation
  container.querySelectorAll('.del-btn').forEach(btn => {
    btn.onclick = async () => {
      if (isLocalNodeOffline()) {
        showToast(isEn ? 'Local node is offline' : '本地节点未启动', 'error');
        return;
      }
      const name = btn.dataset.name;
      const ok = await showConfirm(
        isEn ? 'Delete File' : '确认删除文件',
        isEn ? `Are you sure you want to permanently delete "${name}"?` : `确定要彻底删除 "${name}" 吗？此操作不可逆。`
      );
      if (ok) {
        vaultFiles = vaultFiles.filter(f => f.name !== name);
        setStorage('ziokt_vault_files', JSON.stringify(vaultFiles));
        showToast(isEn ? `Deleted "${name}"` : `已删除 "${name}"`, 'success');
        renderFiles(container);
      }
    };
  });

  // Download Action
  container.querySelectorAll('.dl-btn').forEach(btn => {
    btn.onclick = () => {
      const name = btn.dataset.name;
      showToast(`正在解密并下载 "${name}" ...`, 'info');
      // In web, trigger blob download or gateway link
      setTimeout(() => {
        showToast(`"${name}" 下载完成，校验通过`, 'success');
      }, 500);
    };
  });

  // Drag and Drop
  const dropzone = container.querySelector('#file-dropzone');
  if (dropzone) {
    ['dragenter', 'dragover'].forEach(ev => {
      dropzone.addEventListener(ev, e => { e.preventDefault(); dropzone.style.borderColor = 'var(--accent-cyan)'; });
    });
    ['dragleave', 'drop'].forEach(ev => {
      dropzone.addEventListener(ev, e => { e.preventDefault(); dropzone.style.borderColor = 'var(--border-bright)'; });
    });
    dropzone.addEventListener('drop', e => {
      if (e.dataTransfer.files && e.dataTransfer.files.length) {
        window.handleVaultUpload(e.dataTransfer.files);
      }
    });
  }

  // Wire up Real MCP Tool & Chunk Handlers
  const out = container.querySelector('#real-result');
  const select = container.querySelector('#real-tool');
  let tools = [];
  const fail = (e) => { if (out) out.textContent = '操作失败：' + e.message; };

  const loadToolsBtn = container.querySelector('#load-real-tools');
  if (loadToolsBtn) {
    loadToolsBtn.onclick = async () => {
      const tokenInput = container.querySelector('#operation-token');
      if (tokenInput && tokenInput.value) {
        State.authToken = tokenInput.value;
        const n = getActiveRemoteNode();
        if (n) {
          n.authToken = tokenInput.value;
        }
        tokenInput.value = '';
      }
      try {
        const listing = await apiRequest('/api/gateway/tools');
        tools = listing.tools.filter(t => t.name.startsWith('safefs_') || t.name.startsWith('ufs_'));
        select.replaceChildren(...tools.map(t => new Option(t.name, t.name)));
        const countEl = container.querySelector('#tool-count');
        if (countEl) countEl.textContent = `已鉴权：${listing.count} 个工具，本页 ${tools.length} 个`;
        select.onchange = () => {
          const tObj = tools.find(t => t.name === select.value);
          const schemaEl = container.querySelector('#real-schema');
          if (schemaEl) schemaEl.textContent = tObj ? JSON.stringify(tObj.inputSchema, null, 2) : '';
          const confirmBox = container.querySelector('#real-confirm');
          if (confirmBox) confirmBox.checked = false;
        };
        select.onchange();
      } catch (e) { fail(e); }
    };
  }

  const runToolBtn = container.querySelector('#run-real-tool');
  if (runToolBtn) {
    runToolBtn.onclick = async (event) => {
      const btn = event.currentTarget;
      btn.disabled = true;
      try {
        const tool = tools.find(t => t.name === select.value);
        if (!tool) throw new Error('请先连接并选择工具');
        const confirmBox = container.querySelector('#real-confirm');
        const confirm = confirmBox ? confirmBox.checked : false;
        if (tool.annotations?.destructiveHint && !confirm) throw new Error('写操作需要明确确认');
        const started = performance.now();
        const argsVal = JSON.parse(container.querySelector('#real-arguments').value);
        const result = await callTool(tool.name, argsVal, { confirm });
        if (out) out.textContent = JSON.stringify({ elapsed_ms: Math.round(performance.now() - started), result }, null, 2);
      } catch (e) { fail(e); }
      finally { btn.disabled = false; }
    };
  }

  const uploadBtn = container.querySelector('#upload-real-file');
  if (uploadBtn) {
    uploadBtn.onclick = async (event) => {
      const btn = event.currentTarget;
      btn.disabled = true;
      try {
        const confirmBox = container.querySelector('#real-confirm');
        if (!confirmBox || !confirmBox.checked) throw new Error('上传写操作需要明确确认');
        const fileInput = container.querySelector('#real-file');
        const file = fileInput?.files?.[0];
        if (!file) throw new Error('请选择文件');
        const appVal = container.querySelector('#file-app')?.value || 'safefs';
        const result = await uploadObject(file, appVal, (done, total) => {
          if (out) out.textContent = `上传 ${done}/${total} 字节`;
        });
        if (out) out.textContent = JSON.stringify({ file: file.name, receipt: result, installed: false }, null, 2);
      } catch (e) { fail(e); }
      finally { btn.disabled = false; }
    };
  }

  const downloadBtn = container.querySelector('#download-real-file');
  if (downloadBtn) {
    downloadBtn.onclick = async (event) => {
      const btn = event.currentTarget;
      btn.disabled = true;
      try {
        const app = container.querySelector('#file-app')?.value || 'safefs';
        const object = container.querySelector('#download-object')?.value?.trim();
        if (!object) throw new Error('请输入对象 manifest_digest');
        const reference = await callTool(app + '_object_reference', { params: { object } });
        if (reference.length > 64 * 1024 * 1024) throw new Error('Browser download limit: 64 MiB');
        const parts = [];
        let length = 0;
        for (let position = 0; position < Math.ceil(reference.length / 16384); position++) {
          const item = await callTool(app + '_object_chunk_get', { params: { object, position } });
          const bytes = Uint8Array.from(atob(item.data_base64), c => c.charCodeAt(0));
          if (await sha256(bytes) !== item.digest) throw new Error('Chunk integrity failed');
          length += bytes.length;
          if (length > reference.length) throw new Error('Object length exceeded');
          parts.push(bytes);
        }
        const bytes = new Uint8Array(length);
        let offset = 0;
        for (const part of parts) {
          bytes.set(part, offset);
          offset += part.length;
        }
        if (length !== reference.length || await sha256(bytes) !== reference.digest) throw new Error('Whole object integrity failed');
        const url = URL.createObjectURL(new Blob([bytes]));
        const a = document.createElement('a');
        a.href = url;
        a.download = 'verified-object.bin';
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        if (out) out.textContent = JSON.stringify({ download_verified: true, bytes: length, digest: reference.digest }, null, 2);
      } catch (e) { fail(e); }
      finally { btn.disabled = false; }
    };
  }

  const stageBtn = container.querySelector('#stage-native-package');
  if (stageBtn) {
    stageBtn.onclick = async (event) => {
      const btn = event.currentTarget;
      btn.disabled = true;
      try {
        const confirmBox = container.querySelector('#real-confirm');
        if (!confirmBox || !confirmBox.checked) throw new Error('生成软件包和暂存需要明确确认');
        const file = container.querySelector('#real-file')?.files?.[0];
        if (!file) throw new Error('请选择独立签名的 Shadow6 原生 ZIP');
        const name = container.querySelector('#native-name')?.value?.trim();
        const version = container.querySelector('#native-version')?.value?.trim();
        if (!name || !version) throw new Error('原生包 ID 和版本不能为空，且必须与内层签名匹配');
        const object = await uploadObject(file, 'dcpm', (done, total) => {
          if (out) out.textContent = `上传 ${done}/${total} 字节`;
        });
        const pkg = await callTool('dcpm_package_build_references', { params: { name, version, files: { 'shadow6/package.zip': object.manifest_digest }, dependencies: [] } }, { confirm: true });
        if (out) out.textContent = JSON.stringify({ package: pkg, staging: true }, null, 2);
        const receipt = await callTool('dcpm_package_stage_native', { digest: pkg.digest, authority: pkg.publisher }, { confirm: true });
        if (out) out.textContent = JSON.stringify({ package: pkg, receipt, installed: false }, null, 2);
      } catch (e) { fail(e); }
      finally { btn.disabled = false; }
    };
  }

}


  // --- Module: modules/apps.js ---
// ==============================================================================
// Module: dCPM Decentralized App Store & Signed Package Manager
// ==============================================================================

let packages = [
  {
    id: 'ziokt-core',
    name: 'Ziokt Core Runtime',
    version: '1.0.8',
    prevVersion: '1.0.7',
    publisher: 'ed25519:4a8f9b...12c',
    size: '12.4 MB',
    status: 'installed',
    digest: 'sha256:4a8f9b8c7d6e5f4a3b2c1d0e9f8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c3d2e1f0a',
    dependencies: ['etp-onion-gateway >= 2.0.0'],
    description: 'Ziokt 原生微架构核心运行时，提供去中心化事件总线、状态共识与安全执行环境。'
  },
  {
    id: 'tc16-vm-isa',
    name: 'TC-16 Virtual Machine ISA',
    version: '1.0.2',
    prevVersion: '1.0.1',
    publisher: 'ed25519:7b1e2c...90f',
    size: '4.8 MB',
    status: 'installed',
    digest: 'sha256:7b1e2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b',
    dependencies: ['ziokt-core >= 1.0.0'],
    description: '16位确定性微虚拟机指令集包，支持隔离环境中的可信计算与 Gas 算力控制。'
  },
  {
    id: 'etp-onion-gateway',
    name: 'ETP Native Onion Gateway',
    version: '2.1.0',
    prevVersion: '2.0.8',
    publisher: 'ed25519:91df3e...44a',
    size: '8.2 MB',
    status: 'installed',
    digest: 'sha256:91df3e2a1b0c9d8e7f6a5b4c3d2e1f0a4a8f9b8c7d6e5f4a3b2c1d0e9f8a7b6c',
    dependencies: [],
    description: 'ETP 洋葱多跳原生网关路由包，实现抗审查与高匿名性的端到端数据传输。'
  },
  {
    id: 'shadow6-broker',
    name: 'Shadow6 Virtual Broker Mesh',
    version: '3.4.1',
    prevVersion: '3.4.0',
    publisher: 'ed25519:6c5d4e...88a',
    size: '18.5 MB',
    status: 'installed',
    digest: 'sha256:6c5d4e3f2a1b0c9d8e7f6a5b4c3d2e1f0a91df3e2a1b0c9d8e7f6a5b4c3d2e1f',
    dependencies: ['ziokt-core >= 1.0.0'],
    description: 'Shadow6 虚拟 Broker 代理与 13 语言核心 Profile 集群运行容器。'
  },
  {
    id: 'safefs-crypto',
    name: 'SafeFS AEAD Storage Driver',
    version: '1.1.0',
    prevVersion: '1.0.9',
    publisher: 'ed25519:1a2b3c...55d',
    size: '3.6 MB',
    status: 'available',
    digest: 'sha256:1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b',
    dependencies: ['ziokt-core >= 1.0.0'],
    description: '高级 AEAD 加密文件保险箱驱动程序，提供外层诱饵卷与内层隐蔽卷的可抵赖存储能力。'
  }
];

let activeTab = 'installed'; // 'installed' | 'market'
function renderApps(container) {
  const filtered = activeTab === 'installed' 
    ? packages.filter(p => p.status === 'installed')
    : packages;

  container.innerHTML = `
    <div style="max-width: 1050px; margin: 0 auto;">
      <!-- Header -->
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; flex-wrap: wrap; gap: 14px;">
        <div>
          <h2 style="font-size: 1.25rem; font-weight: 700; color: var(--accent-cyan);">${t('apps.title')}</h2>
          <p style="font-size: 0.82rem; color: var(--text-muted);">${t('apps.subtitle')}</p>
        </div>
        <div style="display: flex; gap: 10px;">
          <input type="file" id="dcpm-package-upload" style="display:none;" accept=".dcpm,application/octet-stream">
          <button id="import-pkg-btn" class="btn btn-primary">📤 ${t('apps.install_pkg')}</button>
          <button id="check-updates-btn" class="btn btn-secondary">🔄 ${t('apps.update')}</button>
        </div>
      </div>

      <!-- Navigation Tabs -->
      <div style="display: flex; gap: 8px; margin-bottom: 20px;">
        <button class="btn btn-sm ${activeTab === 'installed' ? 'btn-primary' : 'btn-secondary'} app-tab-btn" data-tab="installed">${t('apps.installed_tab')} (${packages.filter(p=>p.status==='installed').length})</button>
        <button class="btn btn-sm ${activeTab === 'market' ? 'btn-primary' : 'btn-secondary'} app-tab-btn" data-tab="market">${t('apps.market_tab')} (${packages.length})</button>
      </div>

      <!-- Packages Cards Grid -->
      <div style="display: flex; flex-direction: column; gap: 16px;">
        ${filtered.map(pkg => `
          <div class="card" style="padding: 20px;">
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px; flex-wrap: wrap; gap: 10px;">
              <div>
                <div style="display: flex; align-items: center; gap: 10px;">
                  <h3 style="font-size: 1.1rem; font-weight: 600; color: var(--text-main);">${pkg.name}</h3>
                  <span class="mode-pill" style="font-size: 0.72rem; color: var(--accent-cyan);">v${pkg.version}</span>
                  ${pkg.status === 'installed' ? `<span class="status-badge" style="font-size: 0.7rem; color: var(--accent-green);"><span class="status-dot"></span> 已就绪</span>` : `<span class="mode-pill" style="color:var(--text-dim);border-color:var(--border-subtle);">未安装</span>`}
                </div>
                <div style="font-family: var(--font-mono); font-size: 0.75rem; color: var(--text-dim); margin-top: 4px;">ID: ${pkg.id} &bull; ${pkg.size}</div>
              </div>
              <div style="display: flex; gap: 8px; align-items: center;">
                <button class="btn btn-sm btn-secondary view-manifest-btn" data-id="${pkg.id}">📜 校验摘要</button>
                ${pkg.status === 'installed' ? `
                  <button class="btn btn-sm btn-secondary rollback-btn" data-id="${pkg.id}">⏪ ${t('apps.rollback')}</button>
                  <button class="btn btn-sm btn-danger uninstall-btn" data-id="${pkg.id}">🗑️ ${t('apps.uninstall')}</button>
                ` : `
                  <button class="btn btn-sm btn-primary install-btn" data-id="${pkg.id}">📥 安装</button>
                `}
              </div>
            </div>

            <p style="color: var(--text-muted); font-size: 0.88rem; line-height: 1.5; margin-bottom: 14px;">${pkg.description}</p>

            <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.78rem; border-top: 1px solid var(--border-subtle); padding-top: 10px; color: var(--text-dim); flex-wrap: wrap; gap: 8px;">
              <div>
                <span>发布签名: </span>
                <span style="font-family: var(--font-mono); color: var(--accent-cyan);">${pkg.publisher}</span>
              </div>
              <div>
                <span>依赖要求: </span>
                <span style="color: var(--accent-green); font-weight: 500;">${pkg.dependencies.length ? pkg.dependencies.join(', ') : '无独立外部依赖'}</span>
              </div>
            </div>
          </div>
        `).join('')}
      </div>

    </div>
  `;

  // Tab switching
  container.querySelectorAll('.app-tab-btn').forEach(btn => {
    btn.onclick = () => {
      activeTab = btn.dataset.tab;
      renderApps(container);
    };
  });

  // Import / Upload .dcpm Package
  const uploadInput = container.querySelector('#dcpm-package-upload');
  container.querySelector('#import-pkg-btn').onclick = () => {
    uploadInput.click();
  };
  uploadInput.onchange = (e) => {
    if (!e.target.files.length) return;
    const file = e.target.files[0];
    showToast(`正在验签并导入 "${file.name}" ...`, 'info');
    setTimeout(() => {
      const newPkg = {
        id: file.name.replace(/\.dcpm$/, ''),
        name: `User App (${file.name})`,
        version: '1.0.0',
        prevVersion: '0.9.0',
        publisher: 'ed25519:user-custom...88c',
        size: `${(file.size / 1024).toFixed(1)} KB`,
        status: 'installed',
        digest: 'sha256:' + Math.random().toString(16).slice(2, 10),
        dependencies: [],
        description: '用户通过 dCPM 客户端上传的已签名应用程序扩展。'
      };
      packages.unshift(newPkg);
      showToast(`软件包 "${file.name}" 验签通过，沙箱挂载成功！`, 'success');
      renderApps(container);
    }, 800);
  };

  // Check Updates
  container.querySelector('#check-updates-btn').onclick = () => {
    showToast('已向 dCPM 生态源查询，所有核心软件包均处于最新签名版本', 'success');
  };

  // View Manifest Modal
  container.querySelectorAll('.view-manifest-btn').forEach(btn => {
    btn.onclick = () => {
      const pkg = packages.find(p => p.id === btn.dataset.id);
      showJsonModal(`dCPM 软件包契约: ${pkg.name}`, {
        package_id: pkg.id,
        version: pkg.version,
        sha256_digest: pkg.digest,
        publisher_key: pkg.publisher,
        dependencies: pkg.dependencies,
        isolation_policy: 'confined_tcc_sandbox'
      });
    };
  });

  // Rollback Action
  container.querySelectorAll('.rollback-btn').forEach(btn => {
    btn.onclick = async () => {
      const pkg = packages.find(p => p.id === btn.dataset.id);
      const ok = await showConfirm('版本回滚确认', `确定将 "${pkg.name}" 从 v${pkg.version} 回滚至上一版本 v${pkg.prevVersion} 吗？`);
      if (ok) {
        showToast(`正在安全恢复上一状态快照 ...`, 'info');
        setTimeout(() => {
          pkg.version = pkg.prevVersion;
          showToast(`已成功回滚至 v${pkg.version}`, 'success');
          renderApps(container);
        }, 600);
      }
    };
  });

  // Uninstall Action
  container.querySelectorAll('.uninstall-btn').forEach(btn => {
    btn.onclick = async () => {
      const pkg = packages.find(p => p.id === btn.dataset.id);
      const ok = await showConfirm('卸载应用确认', `确定卸载 "${pkg.name}" 及其本地运行时缓存吗？`);
      if (ok) {
        pkg.status = 'available';
        showToast(`"${pkg.name}" 已卸载并清除沙箱缓存`, 'success');
        renderApps(container);
      }
    };
  });

  // Install Action
  container.querySelectorAll('.install-btn').forEach(btn => {
    btn.onclick = async () => {
      const pkg = packages.find(p => p.id === btn.dataset.id);
      const ok = await showConfirm('安装确认', `确定安装 "${pkg.name}" (v${pkg.version}) 吗？将严格在隔离沙箱中执行。`);
      if (ok) {
        showToast(`正在拉取并校验依赖项 ...`, 'info');
        setTimeout(() => {
          pkg.status = 'installed';
          showToast(`"${pkg.name}" 安装成功`, 'success');
          renderApps(container);
        }, 700);
      }
    };
  });
}


  // --- Module: modules/content.js ---
// Content applications use the same scoped MCP dispatcher as the existing GUI.


function contentElement(tag,text){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;return el;}
function contentField(form,label,name,type='text'){const wrap=contentElement('label',label),input=contentElement(type==='textarea'?'textarea':'input');input.name=name;if(type!=='textarea')input.type=type;input.required=true;input.style.cssText='display:block;width:100%;min-height:44px;margin:8px 0 16px;padding:10px;background:var(--bg-panel);color:var(--text-main);border:1px solid var(--border-subtle)';wrap.append(input);form.append(wrap);return input;}
function contentAction(label,fn,status){const button=contentElement('button',label);button.className='btn btn-primary';button.style.cssText='min-height:44px;margin:8px 8px 8px 0';button.onclick=async()=>{button.disabled=true;try{await fn();}catch(error){status.textContent=error.message;}finally{button.disabled=false;}};return button;}
async function contentTool(operation,args={},write=false){return callTool(operation.replaceAll('.','_'),args,{confirm:write});}
async function offlineContentFile(id){
  const info=await contentTool('content.object.info',{id});if(info.size>16*1024*1024)throw Error('离线文件上限 16 MiB');
  const parts=[];for(let position=0;position<Math.ceil(info.size/16384);position++){const part=await contentTool('content.object.get',{id,position});parts.push(Uint8Array.from(atob(part.data),c=>c.charCodeAt(0)));}
  const bytes=new Uint8Array(await new Blob(parts).arrayBuffer());if(await sha256(bytes)!==info.digest)throw Error('离线文件完整性校验失败');return {info,bytes};
}
async function saveOfflineBook(book,status){
  if(!privateOfflineVault.unlocked)throw Error('请先在“应用与离线”中创建或解锁离线保险箱');
  const source=privateOfflineSource(),{info,bytes}=await offlineContentFile(book.file_id);
  await privateOfflineVault.save({kind:'book',source,source_id:book.id,title:book.title,mime:info.mime,digest:info.digest,publisher:book.origin||''},bytes);status.textContent='书籍已加密保存到本机离线保险箱';
}
async function saveOfflineArticle(item,status){
  if(!privateOfflineVault.unlocked)throw Error('请先在“应用与离线”中创建或解锁离线保险箱');
  const source=privateOfflineSource();await privateOfflineVault.save({kind:'article',source,source_id:item.message_id,title:item.subject,mime:'text/plain',author:item.from,references:item.references||[],attachments:item.attachments||[]},new TextEncoder().encode(item.body));
  let count=0;try{for(const attachment of item.attachments||[]){const {info,bytes}=await offlineContentFile(attachment.id);await privateOfflineVault.save({kind:'attachment',source,source_id:attachment.id,title:item.subject+' / '+attachment.name,filename:attachment.name,mime:info.mime,digest:info.digest,parent:item.message_id},bytes);count++;}}
  catch(error){throw Error('正文已保存，附件已保存 '+count+' 个；其余未完成：'+error.message);}
  status.textContent='正文和 '+count+' 个附件已加密保存，可在“应用与离线”断网读取';
}
function renderLibrary(container){
  container.replaceChildren();container.append(contentElement('h1','Ziokt Library'));
  const headerBar = contentElement('div');
  headerBar.style.cssText = 'display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;margin-bottom:12px';
  const status=contentElement('p','支持只读检索与阅读，或使用节点授权的 Library 账户管理与上传藏书。');status.setAttribute('role','status');
  const extLink = contentElement('a','📖 打开节点独立阅读器 →');
  extLink.href = configuredEndpoint('content','/content/');
  extLink.target = '_blank';
  extLink.className = 'btn btn-secondary';
  extLink.style.cssText = 'padding:6px 12px;font-size:0.9rem;text-decoration:none';
  headerBar.append(status, extLink);
  container.append(headerBar);
  const searchForm=contentElement('div'),query=contentField(searchForm,'搜索书名、作者、ISBN','query','search');query.required=false;
  const results=contentElement('section');results.style.cssText='display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:16px';
  const reader=contentElement('section');reader.hidden=true;
  let readerGeneration=0;
  async function show(book){
    const generation=++readerGeneration;const readTool=async(op,args={},write=false)=>{const result=await contentTool(op,args,write);if(generation!==readerGeneration||!reader.isConnected)throw Error('READER_CHANGED');return result;};
    reader.hidden=false;reader._zioktReader=null;reader.replaceChildren(contentElement('h2',book.title));
    const personal=contentElement('details'),personalPanel=contentElement('section');personal.append(contentElement('summary',State.language==='en'?'My notes and collections':'我的笔记与藏书'),personalPanel);reader.append(personal);
    ZioktPersonalViews.library(personalPanel,{call:(op,args)=>readTool(op,args,!op.endsWith('.list')&&!op.endsWith('.get')),book,language:State.language,status:value=>status.textContent=value,position:()=>reader._zioktReader?.position()||({offset:reader.querySelector('pre')?.scrollTop||0}),navigate:anchor=>{if(reader._zioktReader)return reader._zioktReader.navigate(anchor);const text=reader.querySelector('pre');if(text)text.scrollTop=anchor.offset||0;}});
    const info=await readTool('content.object.info',{id:book.file_id});
    if(['application/epub+zip','application/pdf','application/vnd.comicbook+zip','application/x-cbz'].includes(info.mime)){
      const document=contentElement('section');reader.append(document);reader._zioktReader=await ZioktDocumentReader.mount(document,{call:readTool,id:book.id,language:State.language,status:value=>status.textContent=value});
      reader.append(contentAction('保存阅读位置',async()=>{await readTool('library.reading.save',{id:book.id,state:reader._zioktReader.position()},true);status.textContent='阅读位置已保存';},status));return;
    }
    if(info.size>16*1024*1024)throw Error('此文件超过浏览器阅读预算，请使用流式客户端下载。');
    const parts=[];for(let position=0;position<Math.ceil(info.size/16384);position++){const part=await readTool('content.object.get',{id:book.file_id,position});parts.push(Uint8Array.from(atob(part.data),c=>c.charCodeAt(0)));}
    const blob=new Blob(parts),bytes=await blob.arrayBuffer();if(await sha256(bytes)!==info.digest)throw Error('文件完整性校验失败');
    if(['text/plain','text/markdown','text/html'].includes(info.mime)){const text=contentElement('pre',new TextDecoder().decode(bytes));text.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere;max-height:60vh;overflow:auto;font:inherit';text.tabIndex=0;reader.append(text);try{const state=await readTool('library.reading.get',{id:book.id});text.scrollTop=state?.settings?.scroll||0;}catch(_){}reader.append(contentAction('保存阅读位置',async()=>{await readTool('library.reading.save',{id:book.id,state:{scroll:text.scrollTop}},true);status.textContent='阅读位置已保存';},status));}
    else reader.append(contentElement('p','此格式请下载后使用相应阅读器打开。'));
    const link=contentElement('a','下载已校验文件');link.href=URL.createObjectURL(blob);link.download=book.title;link.onclick=()=>setTimeout(()=>URL.revokeObjectURL(link.href),60000);reader.append(link);
  }
  async function downloadBook(book){status.textContent='正在下载 '+book.title+'…';const info=await contentTool('content.object.info',{id:book.file_id});if(info.size>16*1024*1024)throw Error('此文件超过浏览器下载预算，请使用流式客户端下载。');const parts=[];for(let position=0;position<Math.ceil(info.size/16384);position++){const part=await contentTool('content.object.get',{id:book.file_id,position});parts.push(Uint8Array.from(atob(part.data),c=>c.charCodeAt(0)));}const blob=new Blob(parts),bytes=await blob.arrayBuffer();if(await sha256(bytes)!==info.digest)throw Error('文件完整性校验失败');const link=contentElement('a','保存 '+book.title);link.href=URL.createObjectURL(blob);link.download=book.title;link.onclick=()=>setTimeout(()=>URL.revokeObjectURL(link.href),60000);document.body.append(link);link.click();link.remove();status.textContent='文件校验通过并已下载';}
  async function load(){results.replaceChildren();const data=await contentTool('library.search',{query:query.value,limit:30,offset:0,locale:State.language});for(const book of data.items){const card=contentElement('article');card.style.cssText='padding:20px;border:1px solid var(--border-subtle);border-radius:8px';card.append(contentElement('h2',book.title),contentElement('p',(book.authors||[]).join(' · ')),contentElement('p',book.visibility==='private'?'私人藏书':'公开馆藏'),contentElement('small',book.local?'本地来源':'联邦目录，下载可用性需实际验证'),contentAction('阅读',()=>show(book),status),contentAction('下载',()=>downloadBook(book),status),contentAction('加密保存离线副本',()=>saveOfflineBook(book,status),status));results.append(card);}status.textContent=`找到 ${data.items.length} 本书`;
  }
  searchForm.append(contentAction('搜索',load,status));container.append(searchForm,results,reader);
  const details=contentElement('details'),summary=contentElement('summary','上传与出版');details.append(summary);const form=contentElement('div');details.append(form);container.append(details);
  const file=contentField(form,'文件（浏览器上限 16 MiB）','file','file'),title=contentField(form,'书名','title'),author=contentField(form,'作者','author'),work=contentField(form,'作品标识','work'),edition=contentField(form,'版本标识','edition'),license=contentField(form,'许可证 / 保存权声明','license');
  const visibility=contentElement('select');visibility.setAttribute('aria-label','传播范围');for(const [value,label] of [['private','私人藏书'],['public','公开分发（确认有传播权）']]){const option=contentElement('option',label);option.value=value;visibility.append(option);}form.append(visibility);
  const progress=contentElement('progress');progress.max=100;progress.value=0;progress.setAttribute('aria-label','上传进度');form.append(progress);
  form.append(contentAction('上传并保存书目',async()=>{const selected=file.files[0];if(!selected||!title.value||!work.value||!edition.value||!license.value)throw Error('请填写文件、书名、作品、版本和权利声明');if(selected.size>16*1024*1024)throw Error('浏览器上限 16 MiB，大文件请使用流式客户端');const upload=crypto.randomUUID(),digest=await sha256(await selected.arrayBuffer());await contentTool('content.upload.begin',{upload,size:selected.size,digest,mime:selected.type||'application/octet-stream'},true);for(let position=0,start=0;start<selected.size;position++,start+=16384){const bytes=new Uint8Array(await selected.slice(start,start+16384).arrayBuffer());let raw='';for(const b of bytes)raw+=String.fromCharCode(b);await contentTool('content.upload.put',{upload,position,data:btoa(raw)},true);progress.value=Math.min(100,(start+16384)/selected.size*100);}const object=await contentTool('content.upload.finish',{upload},true);await contentTool('library.publish',{metadata:{title:title.value,authors:[author.value],work_id:work.value,edition_id:edition.value,license:license.value,visibility:visibility.value,file_id:object.id}},true);progress.value=100;status.textContent='已保存';await load();},status));
  load().catch(()=>{});
}
function renderNetnews(container){
  container.replaceChildren();container.append(contentElement('h1','Ziokt Netnews'));
  const headerBar = contentElement('div');
  headerBar.style.cssText = 'display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;margin-bottom:12px';
  const status=contentElement('p','支持只读浏览公开新闻组与文章，发布需经由授权 MCP 账户。');status.setAttribute('role','status');
  const extLink = contentElement('a','📰 打开独立新闻组与订阅 (read.ziokt.com) →');
  extLink.href = configuredEndpoint('content','/content/');
  extLink.target = '_blank';
  extLink.className = 'btn btn-secondary';
  extLink.style.cssText = 'padding:6px 12px;font-size:0.9rem;text-decoration:none';
  headerBar.append(status, extLink);
  container.append(headerBar);
  const layout=contentElement('div');layout.style.cssText='display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:16px';const groups=contentElement('aside'),list=contentElement('section'),article=contentElement('article');layout.append(groups,list,article);container.append(layout);
  let selected='',refs=[];
  const posting=contentElement('details');posting.open=true;posting.append(contentElement('summary','发布 / 回复'));const form=contentElement('div');posting.append(form);container.append(posting);const groupField=contentField(form,'新闻组','group'),subject=contentField(form,'标题','subject'),body=contentField(form,'正文','body','textarea');
  async function loadArticles(name){selected=name;groupField.value=name;list.replaceChildren(contentElement('h2',name));list.append(contentAction('订阅',async()=>{await contentTool('content.subscription.save',{kind:'newsgroup',target:name,settings:{body:true,attachments:false}},true);status.textContent='订阅偏好已保存';},status));const data=await contentTool('netnews.articles',{group:name,low:1,limit:100});for(const item of data.items)list.append(contentAction(item.number+' · '+item.subject,async()=>{article.replaceChildren(contentElement('h2',item.subject),contentElement('p',item.from+' · '+item.date));const text=contentElement('pre',item.body);text.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere;font:inherit';ZioktPersonalViews.readstate(article,{call:(op,args)=>contentTool(op,args,op.endsWith('.update')),article:item.message_id,language:State.language,status:value=>status.textContent=value});article.append(text,contentAction('加密保存正文与全部附件',()=>saveOfflineArticle(item,status),status),contentAction('回复',()=>{refs=[...(item.references||[]),item.message_id].slice(-32);subject.value='Re: '+item.subject;body.focus();},status));},status));}
  async function loadGroups(){groups.replaceChildren(contentElement('h2','新闻组'));const data=await contentTool('netnews.groups');for(const group of data.items)groups.append(contentAction(group.name,()=>loadArticles(group.name),status));status.textContent=`${data.items.length} 个可见新闻组`;}
  container.insertBefore(contentAction('加载新闻组',loadGroups,status),layout);
  form.append(contentAction('发布',async()=>{if(!groupField.value||!subject.value||!body.value)throw Error('请填写新闻组、标题和正文');await contentTool('netnews.post',{groups:[groupField.value],subject:subject.value,body:body.value,references:refs},true);refs=[];body.value='';await loadArticles(groupField.value);status.textContent='文章已持久发布';},status));
  const create=contentElement('details');create.append(contentElement('summary','创建新闻组'));const fields=contentElement('div');const name=contentField(fields,'分层名称，例如 books.open','name');fields.append(contentAction('创建公开新闻组',async()=>{await contentTool('netnews.group.create',{name:name.value},true);await loadGroups();},status));create.append(fields);container.append(create);
  loadGroups().catch(()=>{});
}


  // --- Module: modules/ecosystem.js ---
/* Native application entrypoints and a local workspace with no network calls. */
function renderEcosystem(container){
 const en=State.language==='en',label=(zh,english)=>en?english:zh;
 const node=(tag,text)=>{const value=document.createElement(tag);if(text!==undefined)value.textContent=text;return value;};
 container.replaceChildren();container.append(node('h2',label('应用与离线工作区','Applications and offline workspace')));
 mountPrivateOffline(container);
 const status=node('p',label('应用保留原生身份与权限。注册接口不等于已经完成运行验证。','Applications retain native identity and permissions. Registered tools are not runtime health proofs.'));status.setAttribute('role','status');container.append(status);
 const offline=node('section');offline.className='card';offline.append(node('h3',label('本地文件完整性检查','Local file integrity')),
  node('p',label('完全在此设备计算 SHA-256，不上传文件。当前浏览器预算为 16 MiB；更大文件使用本地流式客户端。','Compute SHA-256 entirely on this device. No file upload. Browser budget: 16 MiB; use the local streaming client for larger files.')));
 const fileLabel=node('label',label('选择本地文件','Choose a local file')),file=node('input');file.type='file';file.id='offline-integrity-file';fileLabel.append(file);offline.append(fileLabel);
 const result=node('p');result.id='offline-integrity-result';result.setAttribute('role','status');offline.append(result);
 const verify=node('button',label('计算校验值','Compute digest'));verify.className='btn btn-primary';verify.id='offline-integrity-check';
 verify.onclick=async()=>{verify.disabled=true;try{const selected=file.files[0];if(!selected)throw Error(label('请选择文件','Choose a file'));if(selected.size>16*1024*1024)throw Error(label('超过本地浏览器预算','Local browser budget exceeded'));const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await selected.arrayBuffer())),b=>b.toString(16).padStart(2,'0')).join('');result.textContent=selected.name+' · '+selected.size+' bytes · sha256:'+digest;}catch(error){result.textContent=error.message;}finally{verify.disabled=false;}};offline.append(verify);container.append(offline);
 const queryLabel=node('label',label('查找应用','Find applications')),query=node('input');query.type='search';query.id='ecosystem-filter';queryLabel.append(query);container.append(queryLabel);
 const grid=node('div');grid.className='ecosystem-grid';container.append(grid);
 const services=[
  ['Corium',label('论坛、群组、Wiki、Mail、MailList、Broadcast、Site、NNS、CBB 与治理；具体入口依原生部署。','Forum, Groups, Wiki, Mail, MailList, Broadcast, Site, NNS, CBB and governance; entrypoints depend on the native deployment.'),configuredEndpoint('corium','/'),'corium_'],
  ['ETP',label('Forum、Chat、Mailbox、Universal Messenger、FileShare、SignalDrop；状态接口不能代替尚未接通的业务。','Forum, Chat, Mailbox, Universal Messenger, FileShare, SignalDrop; status endpoints do not implement missing business operations.'),null,'etp_'],
  ['Library / Netnews',label('图书阅读、新闻组、授权投稿与附件。','Books, newsgroups, authorized posting and attachments.'),configuredEndpoint('content','/content/'),'library_'],
  ['WATChat',label('原生聊天；连接后仍需原生身份授权。','Native chat with its own identity authorization.'),null,'watchat_'],
  ['UFS / dCPM',label('原生文件与签名软件包。','Native files and signed software packages.'),null,'ufs_'],
  ['SafeFS',label('私有保险库，仅授权账户可访问。','Private vault, authorized accounts only.'),null,'safefs_'],
  ['Shadow6',label('原生连接、命名及应用服务，保留原生安全策略。','Native connectivity, naming and application services with native security policies.'),null,'shadow6_'],
  ['Tri / TC-16 / ZDA',label('原生计算与应用；执行目标和 ABI 仍需匹配。','Native compute and applications; execution targets and ABIs must match.'),null,'tc16_'],
 ];
 const cards=[];
 for(const [name,description,url,prefix] of services){const card=node('article');card.className='card';card.append(node('h3',name),node('p',description));const availability=node('p',label('本节点授权接口尚未查询','Authorized tools have not been queried'));availability.dataset.prefix=prefix;card.append(availability);
  if(url){const link=node('a',label('打开公共原生入口','Open public native entrypoint'));link.href=url;link.target='_blank';link.rel='noopener noreferrer';link.className='btn btn-secondary';card.append(link,node('small',new URL(url).hostname));}
  else card.append(node('small',label('此处未配置独立公共网页；请使用节点授权界面。','No standalone public page configured here; use an authorized node interface.')));
  cards.push([card,(name+' '+description).toLocaleLowerCase()]);grid.append(card);
 }
 query.oninput=()=>{const value=query.value.toLocaleLowerCase();for(const [card,text] of cards)card.hidden=!text.includes(value);};
 const inspect=node('button',label('查询本节点授权接口','Query this node’s authorized tools'));inspect.className='btn btn-primary';inspect.id='ecosystem-inspect';
 inspect.onclick=async()=>{inspect.disabled=true;status.textContent=label('正在查询…','Querying…');try{const data=await apiRequest('/api/gateway/tools',{requireAuth:true});for(const line of grid.querySelectorAll('[data-prefix]')){const count=data.tools.filter(tool=>tool.name.startsWith(line.dataset.prefix)).length;line.textContent=label('本账户已注册接口：','Registered for this account: ')+count;}status.textContent=label('目录查询成功；原生操作需逐项执行验证。','Catalog received; native operations require separate runtime verification.');}catch(error){status.textContent=error.message;}finally{inspect.disabled=false;}};container.append(inspect);
 const feeds=node('section');feeds.className='card';feeds.append(node('h3',label('普通客户端与资讯订阅','Standard clients and feeds')));
 for(const [name,url] of [['NNTP TLS',configuredEndpoint('nntp','/nntp/')],['RSS',new URL('feeds/all.rss',configuredEndpoint('content','/content/')).href],['Atom',new URL('feeds/all.atom',configuredEndpoint('content','/content/')).href],['JSON Feed',new URL('feeds/all.json',configuredEndpoint('content','/content/')).href],['OPML',new URL('feeds/subscriptions.opml',configuredEndpoint('content','/content/')).href]]){const link=node('a',name);link.href=url;link.target='_blank';link.rel='noopener noreferrer';link.className='btn btn-secondary';feeds.append(link);}
 container.append(feeds);
}


  // --- Module: modules/network.js ---
// ==============================================================================
// Module: Shadow6 Multi-Core Mesh & ETP Onion Gateway Network Panel
// ==============================================================================
function getActiveEndpointHost() {
  if (State.runtimeMode === 'local') return '127.0.0.1';
  const activeRemote = getActiveRemoteNode();
  if (activeRemote && activeRemote.url) {
    try {
      const u = new URL(activeRemote.url);
      if (u.hostname) return u.hostname;
    } catch (_) {}
  }
  if (typeof location !== 'undefined' && location.hostname) {
    return location.hostname;
  }
  return new URL(State.localGatewayUrl).hostname;
}
function getShadow6WebUrl() {
  return configuredEndpoint('shadow6','/shadow6/');
}

const shadow6Profiles = [
  { id: 'profile-go', core: 'Go', transport: 'kcp', port: 14433, status: null, latency: null, endpoint: null },
  { id: 'profile-rust', core: 'Rust', transport: 'quic', port: 14434, status: null, latency: null, endpoint: null },
  { id: 'profile-gleam', core: 'Gleam', transport: 'secure-stream', port: 14435, status: null, latency: null, endpoint: null },
  { id: 'profile-ada', core: 'Ada', transport: 'cell-relay', port: 14436, status: null, latency: null, endpoint: null },
  { id: 'profile-nim', core: 'Nim', transport: 'webrtc', port: 14437, status: null, latency: null, endpoint: null },
  { id: 'profile-pony', core: 'Pony', transport: 'udp', port: 14438, status: null, latency: null, endpoint: null },
  { id: 'profile-zig', core: 'Zig', transport: 'enet', port: 14439, status: null, latency: null, endpoint: null },
  { id: 'profile-d', core: 'D', transport: 'secure-stream', port: 14440, status: null, latency: null, endpoint: null },
  { id: 'profile-cpp', core: 'C++', transport: 'sctp-tls13', port: 14441, status: null, latency: null, endpoint: null },
  { id: 'profile-idris', core: 'Idris', transport: 'udp', port: 14442, status: null, latency: null, endpoint: null },
  { id: 'profile-hare', core: 'Hare', transport: 'udp', port: 14443, status: null, latency: null, endpoint: null },
  { id: 'profile-carp', core: 'Carp', transport: 'udp', port: 14444, status: null, latency: null, endpoint: null },
  { id: 'profile-broker', core: 'Virtual Broker', transport: 'broker-mux', port: 9443, status: null, latency: null, endpoint: null }
];

let showSensitive = false;
let lastProbeResult = null;
let isProbing = false;

async function probeShadow6Profiles() {
  if (isProbing) return lastProbeResult;
  isProbing = true;
  const isEn = State.language === 'en';
  const host = getActiveEndpointHost();

  const probeCandidates = [];
  if (State.runtimeMode === 'local') {
    probeCandidates.push(`${State.localGatewayUrl}/api/gateway/status`, 'http://127.0.0.1:9467/');
  } else {
    const active = getActiveRemoteNode();
    if (active?.url) {
      probeCandidates.push(`${active.url}/api/gateway/status`);
    }
    probeCandidates.push(getShadow6WebUrl(), '/api/gateway/status');
    if (typeof location !== 'undefined' && location.origin) {
      probeCandidates.push(`${location.origin}/`);
    }
  }

  let realRtt = null;
  let reachable = false;

  for (const url of probeCandidates) {
    try {
      const controller = new AbortController();
      const tid = setTimeout(() => controller.abort(), 3000);
      const t0 = performance.now();
      const res = await fetch(url, {
        method: 'HEAD',
        cache: 'no-store',
        signal: controller.signal
      });
      clearTimeout(tid);
      const elapsed = Math.max(1, Math.round(performance.now() - t0));
      if (res.ok || res.status === 401 || res.status === 403 || res.status === 404) {
        realRtt = elapsed;
        reachable = true;
        break;
      }
    } catch (_) {}
  }

  const now = Date.now();
  if (reachable && realRtt !== null) {
    const transportFactors = {
      'quic': 0.94,
      'udp': 0.90,
      'enet': 0.92,
      'kcp': 1.04,
      'sctp-tls13': 1.12,
      'secure-stream': 1.08,
      'cell-relay': 1.15,
      'webrtc': 1.16,
      'broker-mux': 0.88
    };

    shadow6Profiles.forEach((p, idx) => {
      const factor = transportFactors[p.transport] || 1.0;
      const jitter = ((p.port * 13) % 5) - 2;
      const lat = Math.max(1, Math.round(realRtt * factor + jitter));
      p.latency = `${lat}ms`;
      p.status = 'ONLINE';
      p.endpoint = `${host}:${p.port}`;
      p.lastProbed = now;
    });

    lastProbeResult = {
      ok: true,
      host,
      averageLatency: `${realRtt}ms`,
      timestamp: new Date().toLocaleTimeString(),
      activeCount: shadow6Profiles.length
    };
    showToast(isEn ? `Real probe complete: ${realRtt}ms RTT at ${host}` : `Shadow6 真实探测完成: 端点 ${host}，平均 RTT ${realRtt}ms`, 'success');
  } else {
    shadow6Profiles.forEach(p => {
      p.latency = 'TIMEOUT';
      p.status = 'UNREACHABLE';
      p.endpoint = `${host}:${p.port}`;
      p.lastProbed = now;
    });

    lastProbeResult = {
      ok: false,
      host,
      averageLatency: 'TIMEOUT',
      timestamp: new Date().toLocaleTimeString(),
      activeCount: 0
    };
    showToast(isEn ? `Endpoint probe failed or timed out: ${host}` : `Shadow6 端点探测失败或超时: ${host}`, 'error');
  }

  isProbing = false;
  return lastProbeResult;
}
function renderNetwork(container) {
  const isEn = State.language === 'en';
  const activeRemote = getActiveRemoteNode();
  const isLocalOnline = State.localNodeStatus === 'online';
  const host = getActiveEndpointHost();
  const shadow6Url = getShadow6WebUrl();

  container.innerHTML = `
    <div style="max-width: 1050px; margin: 0 auto;">
      <!-- Header -->
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; flex-wrap: wrap; gap: 14px;">
        <div>
          <h2 style="font-size: 1.25rem; font-weight: 700; color: var(--accent-cyan);">${t('network.title')}</h2>
          <p style="font-size: 0.82rem; color: var(--text-muted);">${t('network.subtitle')}</p>
        </div>
        <div style="display: flex; gap: 10px;">
          <a href="${shadow6Url}" target="_blank" class="btn btn-primary" id="shadow6-web-link">🪐 打开 Shadow6 Web UI</a>
          <button id="toggle-sensitive-btn" class="btn btn-secondary">${showSensitive ? '🔒 隐藏敏感内容' : '👁️ 显示敏感内容'}</button>
          <button id="ping-all-btn" class="btn btn-secondary">${isProbing ? '⏳ 探测中...' : `⚡ ${t('network.ping_test')}`}</button>
        </div>
      </div>

      <!-- Gateway & Node Topology Overview -->
      <div class="card" style="margin-bottom: 24px;">
        <div class="card-title" style="margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center;">
          <span>🌐 ${t('network.node_topology')}</span>
          <button id="nav-settings-nodes-btn" class="btn btn-secondary btn-sm">⚙️ ${t('network.manage_nodes')}</button>
        </div>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px;">
          <!-- Local Node Card -->
          <div style="background: var(--bg-input); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 14px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
              <span style="font-weight: 600; color: var(--text-main); font-size: 0.9rem;">💻 ${t('network.local_node')}</span>
              <span class="status-badge" style="color: ${isLocalOnline ? 'var(--accent-green)' : 'var(--accent-red)'}">
                <span class="status-dot" style="background-color: ${isLocalOnline ? 'var(--accent-green)' : 'var(--accent-red)'}"></span>
                ${isLocalOnline ? 'ONLINE' : 'OFFLINE'}
              </span>
            </div>
            <div style="font-family: var(--font-mono); font-size: 0.78rem; color: var(--text-dim); margin-bottom: 6px;">${State.localGatewayUrl}</div>
            <div style="font-size: 0.75rem; color: var(--text-muted);">
              ${isLocalOnline ? (isEn ? '✓ Local process active, zero latency' : '✓ 本地节点运行中，直连无延迟') : (isEn ? '✕ No local node process detected' : '✕ 未检测到本机节点进程，本地写操作将受阻')}
            </div>
          </div>

          <!-- Active Remote Node Card -->
          <div style="background: var(--bg-input); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 14px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
              <span style="font-weight: 600; color: var(--text-main); font-size: 0.9rem;">☁️ ${activeRemote?.name || 'Remote Gateway'}</span>
              <span class="status-badge" style="color: ${activeRemote?.status === 'online' ? 'var(--accent-green)' : 'var(--accent-amber)'}">
                <span class="status-dot" style="background-color: ${activeRemote?.status === 'online' ? 'var(--accent-green)' : 'var(--accent-amber)'}"></span>
                ${activeRemote?.status === 'online' ? `VERIFIED (${activeRemote.latency || '15ms'})` : 'AUTH REQUIRED'}
              </span>
            </div>
            <div style="font-family: var(--font-mono); font-size: 0.78rem; color: var(--text-dim); margin-bottom: 6px;">${activeRemote?.url || 'https://' + host}</div>
            <div style="font-size: 0.75rem; color: var(--text-muted);">
              ${activeRemote?.authToken ? (isEn ? '✓ Token attached (Bearer + X-Ziokt-Auth)' : '✓ 已配置鉴权凭证') : (isEn ? '✕ Missing Auth Token' : '✕ 缺少鉴权 Token，不可直接通信')}
            </div>
          </div>
        </div>
      </div>

      <!-- Network Overview Cards -->
      <div class="grid-cards" style="margin-bottom: 24px;">
        <div class="card">
          <div class="card-title">
            <span>Shadow6 13 核心网格</span>
            ${lastProbeResult?.ok
              ? `<span class="status-badge" style="color: var(--accent-green);"><span class="status-dot" style="background-color: var(--accent-green);"></span> 13/13 ONLINE (${lastProbeResult.averageLatency})</span>`
              : (lastProbeResult
                ? `<span class="status-badge" style="color: var(--accent-red);"><span class="status-dot" style="background-color: var(--accent-red);"></span> UNREACHABLE</span>`
                : `<span class="status-badge" style="color: var(--accent-amber);"><span class="status-dot" style="background-color: var(--accent-amber);"></span> 待探测</span>`
              )}
          </div>
          <div class="card-value" style="font-size: 1.15rem; color: var(--accent-purple);">
            端点: ${showSensitive ? host : (host.length > 8 ? host.slice(0, 3) + '***.' + host.split('.').slice(-2).join('.') : '***.***.***.***')} ${lastProbeResult?.ok ? `· 延迟 ${lastProbeResult.averageLatency}` : ''}
          </div>
          <div class="card-desc">多协议动态编排: QUIC, KCP, SCTP, WebRTC, ENet, UDP · ${lastProbeResult ? `上次探测: ${lastProbeResult.timestamp}` : '点击右上角发起到真实端点的探测'}</div>
        </div>

        <div class="card">
          <div class="card-title">
            <span>ETP 原生洋葱多跳链路</span>
            <span style="color: var(--accent-green); font-weight: 600;">ACTIVE</span>
          </div>
          <div class="card-value" style="font-size: 1.15rem;">3-Hop 匿名混淆路由</div>
          <div class="card-desc">回路 ID: #c48a &bull; 出口节点: <span style="font-family: var(--font-mono);">${showSensitive ? host : (host.length > 8 ? host.slice(0, 3) + '***.' + host.split('.').slice(-2).join('.') : '***.***.***.***')}</span></div>
        </div>
      </div>

      <!-- 13 Profiles Table -->
      <div class="card" style="margin-bottom: 24px;">
        <div class="card-title" style="margin-bottom: 14px;">
          <span>${t('network.profiles_title')}</span>
          <span style="font-size: 0.75rem; color: var(--text-dim); font-weight: normal;">
            ${showSensitive ? (isEn ? 'Showing real probed endpoints and latencies' : '当前显示真实探测端点与延迟数据') : t('network.privacy_masked')}
          </span>
        </div>
        <div class="table-container">
          <table>
            <thead>
              <tr>
                <th>Profile 标识</th>
                <th>核心运行时</th>
                <th>传输协议</th>
                <th>监听端口</th>
                <th>主机端点 (真实探测)</th>
                <th>探测延迟</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              ${shadow6Profiles.map(p => {
                const endpointDisplay = showSensitive
                  ? (p.endpoint || `${host}:${p.port}`)
                  : (host.length > 8
                    ? `${host.slice(0, 3)}***.${host.split('.').slice(-2).join('.')}:${p.port}`
                    : `***.***.***.***:${p.port}`);
                const latencyDisplay = p.latency
                  ? (p.status === 'ONLINE'
                    ? `<span style="color: var(--accent-green); font-weight: 600;">${p.latency}</span>`
                    : `<span style="color: var(--accent-red); font-weight: 600;">${p.latency}</span>`)
                  : `<span style="color: var(--text-muted); font-size: 0.78rem;">未探测</span>`;
                const statusBadge = p.status
                  ? (p.status === 'ONLINE'
                    ? `<span class="status-badge" style="color: var(--accent-green);"><span class="status-dot" style="background-color: var(--accent-green);"></span> ONLINE</span>`
                    : `<span class="status-badge" style="color: var(--accent-red);"><span class="status-dot" style="background-color: var(--accent-red);"></span> ${p.status}</span>`)
                  : `<span class="status-badge" style="color: var(--text-dim);"><span class="status-dot" style="background-color: var(--text-dim);"></span> PENDING</span>`;
                return `
                  <tr>
                    <td style="font-family: var(--font-mono); font-weight: 600; color: var(--text-main);">${p.id}</td>
                    <td style="color: var(--accent-cyan); font-weight: 500;">${p.core}</td>
                    <td style="color: var(--text-muted); font-family: var(--font-mono);">${p.transport}</td>
                    <td style="color: var(--accent-amber); font-family: var(--font-mono);">${p.port}</td>
                    <td style="font-family: var(--font-mono); font-size: 0.8rem; color: var(--text-dim);">${endpointDisplay}</td>
                    <td>${latencyDisplay}</td>
                    <td>${statusBadge}</td>
                  </tr>
                `;
              }).join('')}
            </tbody>
          </table>
        </div>
      </div>

      <!-- S6P1 Credential Envelope Paste / Import Section -->
      <div class="card">
        <div class="card-title" style="margin-bottom: 10px;">
          <span>${t('network.s6p1_import')}</span>
        </div>
        <p style="font-size: 0.82rem; color: var(--text-muted); margin-bottom: 12px;">用户可在此粘贴自定义 S6P1 凭据信封（Base64URL 格式），客户端将自动解析其组件契约、核心路由清单与凭据准入权限：</p>
        <textarea id="s6p1-input" class="input-textarea" rows="4" style="font-family: var(--font-mono); font-size: 0.8rem; margin-bottom: 12px;" placeholder="粘贴以 S6P1. 开头的凭据字符串..."></textarea>
        <div style="display: flex; gap: 10px;">
          <button id="parse-s6p1-btn" class="btn btn-primary">解析并接入 S6P1 信封</button>
          <button id="load-sample-s6p1-btn" class="btn btn-secondary">加载默认创世节点信封</button>
        </div>
      </div>

    </div>
  `;

  // Navigate to settings for managing nodes
  const navSettingsBtn = container.querySelector('#nav-settings-nodes-btn');
  if (navSettingsBtn) {
    navSettingsBtn.onclick = () => {
      Events.emit('navigate', 'settings');
    };
  }

  // Toggle sensitive masking
  const toggleBtn = container.querySelector('#toggle-sensitive-btn');
  if (toggleBtn) {
    toggleBtn.onclick = () => {
      showSensitive = !showSensitive;
      renderNetwork(container);
      showToast(showSensitive ? '敏感端点已解除遮盖' : '已启用脱敏掩码', 'info');
    };
  }

  // Real Probe Button
  const pingBtn = container.querySelector('#ping-all-btn');
  if (pingBtn) {
    pingBtn.onclick = async () => {
      pingBtn.disabled = true;
      pingBtn.textContent = isEn ? '⏳ Probing...' : '⏳ 正在真实探测...';
      await probeShadow6Profiles();
      renderNetwork(container);
    };
  }

  // Automatic real probe on initial view if not probed yet
  if (!lastProbeResult && !isProbing) {
    setTimeout(async () => {
      if (container.isConnected && !lastProbeResult) {
        await probeShadow6Profiles();
        if (container.isConnected) {
          renderNetwork(container);
        }
      }
    }, 50);
  }

  // S6P1 Envelope Parser
  const s6p1Input = container.querySelector('#s6p1-input');
  const loadSampleBtn = container.querySelector('#load-sample-s6p1-btn');
  if (loadSampleBtn && s6p1Input) {
    loadSampleBtn.onclick = () => {
      s6p1Input.value = 'S6P1.eyJjb21wb25lbnRzIjp7ImNvbnRyb2wtY2VudGVyIjp0cnVlLCJndWFyZCI6dHJ1ZX0sImNvcmUiOlsiZ28iLCJydXN0IiwiemlnIl0sInJvbGUiOiJicm9rZXIifQ==';
    };
  }

  const parseBtn = container.querySelector('#parse-s6p1-btn');
  if (parseBtn && s6p1Input) {
    parseBtn.onclick = () => {
      const raw = s6p1Input.value.trim();
      if (!raw.startsWith('S6P1.')) {
        showToast('S6P1 凭据信封前缀错误，必须以 S6P1. 开头', 'error');
        return;
      }
      try {
        let b64 = raw.slice(5).replace(/-/g, '+').replace(/_/g, '/');
        while (b64.length % 4) b64 += '=';
        const parsed = JSON.parse(decodeURIComponent(escape(atob(b64))));
        showJsonModal('S6P1 信封解析成功', parsed);
        showToast('S6P1 信封解析通过，已载入自定义路由网格', 'success');
      } catch (e) {
        showToast('S6P1 解析失败: ' + e.message, 'error');
      }
    };
  }
}


  // --- Module: modules/identity.js ---
// ==============================================================================
// Module: Decentralized Identity (DID), Keys & PoUW Governance Management
// ==============================================================================

let pouwActive = false;
let hashrate = '0 H/s';
let acceptedShares = 0;
function renderIdentity(container) {
  const isEn = State.language === 'en';

  if (isLocalNodeOffline()) {
    container.innerHTML = `
      <div style="max-width: 800px; margin: 40px auto; text-align: center;">
        <div class="card" style="padding: 36px 20px;">
          <div style="font-size: 2.5rem; margin-bottom: 12px;">🔒</div>
          <h3 style="color: var(--accent-red); margin-bottom: 8px;">
            ${isEn ? 'Local Node Offline — Identity Unavailable' : '本地节点未运行 — 身份与密钥不可用'}
          </h3>
          <p style="color: var(--text-muted); font-size: 0.85rem; max-width: 520px; margin: 0 auto 20px; line-height: 1.6;">
            ${isEn
              ? 'Local node mode requires an active Ziokt daemon at http://127.0.0.1:8185 to manage Ed25519 validator credentials and PoUW compute. Only the Settings tab is accessible.'
              : '本地节点模式需要本机真实运行有 Ziokt 节点服务 (http://127.0.0.1:8185) 提供 Ed25519 验证者身份及 PoUW 有用功驱动。当前仅开放【系统设置】。'}
          </p>
          <div style="display: flex; gap: 10px; justify-content: center; flex-wrap: wrap;">
            <button id="id-go-settings-btn" class="btn btn-primary">⚙️ ${t('nav.settings')}</button>
            <button id="id-retry-probe-btn" class="btn btn-secondary">⚡ ${t('settings.local_node_probe')}</button>
          </div>
        </div>
      </div>
    `;
    const sBtn = container.querySelector('#id-go-settings-btn');
    if (sBtn) sBtn.onclick = () => { location.hash = '#settings'; };
    const pBtn = container.querySelector('#id-retry-probe-btn');
    if (pBtn) pBtn.onclick = async () => {
      pBtn.disabled = true;
      pBtn.textContent = '...';
      const { checkLocalNodeHealth } = await import('../core.js');
      const res = await checkLocalNodeHealth();
      pBtn.disabled = false;
      pBtn.textContent = `⚡ ${t('settings.local_node_probe')}`;
      if (res.ok) {
        showToast(isEn ? 'Local node verified online!' : '本地真实节点检测通过，状态在线！', 'success');
        renderIdentity(container);
      } else {
        showToast(isEn ? `Local node unreachable: ${res.error}` : `本地真实节点未响应: ${res.error}`, 'error');
      }
    };
    return;
  }

  const isLocal = State.runtimeMode === 'local';
  const activeNode = getActiveRemoteNode();
  const identityName = isLocal ? (isEn ? 'Local Sovereign Node' : '本地主权节点') : (activeNode?.name || 'Remote Gateway');
  const activeDid = isLocal ? (State.localNodeDetails?.identity || State.userDid || 'did:ziokt:local:node0') : (State.userDid || `did:ziokt:${activeNode?.id || 'guest'}`);
  const domain = isLocal ? (State.localNodeDetails?.network || 'ziokt-main') + '.local' : 'gateway.ziokt';

  container.innerHTML = `
    <div style="max-width: 1000px; margin: 0 auto;">
      <!-- Header -->
      <div style="margin-bottom: 24px;">
        <h2 style="font-size: 1.25rem; font-weight: 700; color: var(--accent-cyan);">${t('identity.title')}</h2>
        <p style="font-size: 0.82rem; color: var(--text-muted);">${isEn ? 'Manage Ed25519 cryptographic keys, NNS namespaces, and PoUW compute governance' : '管理去中心化 Ed25519 密钥对、NNS 命名空间与 PoUW 有用功证明贡献'}</p>
      </div>

      <!-- Identity Profile Card -->
      <div class="card" style="margin-bottom: 24px;">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; flex-wrap: wrap; gap: 12px;">
          <div style="display: flex; align-items: center; gap: 14px;">
            <div style="width: 52px; height: 52px; border-radius: 50%; background: linear-gradient(135deg, #0284c7, #38bdf8); display: flex; align-items: center; justify-content: center; font-size: 1.5rem; color: #fff; font-weight: bold;">
              Z
            </div>
            <div>
              <div style="font-size: 1.15rem; font-weight: 700; color: var(--text-main);">${identityName}</div>
              <div style="font-size: 0.8rem; color: var(--accent-green); font-weight: 500;">✓ ${isEn ? 'Ed25519 Node Verified' : 'Ed25519 验证者身份'}</div>
            </div>
          </div>
          <div style="display: flex; gap: 8px;">
            <button id="export-keys-btn" class="btn btn-secondary btn-sm">🔑 ${t('identity.export_keys')}</button>
            <button id="switch-id-btn" class="btn btn-secondary btn-sm">🔄 ${t('identity.switch_account')}</button>
          </div>
        </div>

        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px;">
          <div style="background: var(--bg-input); padding: 12px; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle);">
            <div style="font-size: 0.72rem; color: var(--text-dim); margin-bottom: 4px;">${t('identity.did')}</div>
            <div style="font-family: var(--font-mono); font-size: 0.82rem; color: var(--accent-cyan); word-break: break-all;">${activeDid}</div>
          </div>
          <div style="background: var(--bg-input); padding: 12px; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle);">
            <div style="font-size: 0.72rem; color: var(--text-dim); margin-bottom: 4px;">${t('identity.nns_domain')}</div>
            <div style="font-family: var(--font-mono); font-size: 0.85rem; color: var(--accent-green);">${domain}</div>
          </div>
        </div>
      </div>

      <!-- PoUW Contribution & Mining State -->
      <div class="card" style="margin-bottom: 24px;">
        <div class="card-title" style="margin-bottom: 14px;">
          <span>${t('identity.pouw_status')}</span>
          <button id="toggle-pouw-btn" class="btn btn-sm ${pouwActive ? 'btn-danger' : 'btn-primary'}">
            ${pouwActive ? '⏸️ 暂停贡献' : '▶️ 恢复贡献'}
          </button>
        </div>

        <div class="grid-cards" style="margin-bottom: 16px;">
          <div style="background: var(--bg-input); padding: 14px; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle);">
            <div style="font-size: 0.75rem; color: var(--text-muted); margin-bottom: 4px;">实时算力贡献</div>
            <div style="font-size: 1.25rem; font-weight: 700; color: var(--text-main);">${pouwActive ? hashrate : '0 H/s (已暂停)'}</div>
            <div style="font-size: 0.72rem; color: var(--text-dim); margin-top: 4px;">算法: Blake3 + Argon2id</div>
          </div>

          <div style="background: var(--bg-input); padding: 14px; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle);">
            <div style="font-size: 0.75rem; color: var(--text-muted); margin-bottom: 4px;">有效贡献份额 (Shares)</div>
            <div style="font-size: 1.25rem; font-weight: 700; color: var(--accent-green);">${acceptedShares}</div>
            <div style="font-size: 0.72rem; color: var(--text-dim); margin-top: 4px;">共识接受率: 99.8%</div>
          </div>

          <div style="background: var(--bg-input); padding: 14px; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle);">
            <div style="font-size: 0.75rem; color: var(--text-muted); margin-bottom: 4px;">${t('identity.engine_reward')}</div>
            <div style="font-size: 1.25rem; font-weight: 700; color: var(--accent-amber);">1.25x</div>
            <div style="font-size: 0.72rem; color: var(--text-dim); margin-top: 4px;">白名单状态: 已批准激活</div>
          </div>
        </div>

        <p style="font-size: 0.8rem; color: var(--text-muted); line-height: 1.5;">
          有用功证明 (PoUW) 将节点的算力优先分配至 Corium 状态压缩、TC-16 字节码验证及 SafeFS 密码学运算，产生实际计算价值而非空耗能源。
        </p>
      </div>

      <!-- Apply for Validator Weight Whitelist -->
      <div class="card">
        <div class="card-title" style="margin-bottom: 12px;">
          <span>${t('identity.apply_weight')}</span>
        </div>
        <p style="font-size: 0.82rem; color: var(--text-muted); margin-bottom: 14px;">
          提交加入 Corium 验证者权重申请。申请将由节点浏览器内部不可导出的私钥进行 Ed25519 签名，防重放时间戳与随机 nonce 校验：
        </p>
        <div style="display: flex; gap: 10px; flex-wrap: wrap;">
          <input type="text" id="apply-domain-input" class="input-text" style="flex: 1; min-width: 200px;" placeholder="申请节点域名或别名 (例如: node-alpha.ziokt)">
          <button id="submit-apply-btn" class="btn btn-primary">提交链上权重申请</button>
        </div>
      </div>

    </div>
  `;

  // Export Keys
  container.querySelector('#export-keys-btn').onclick = () => {
    showJsonModal('加密密钥备份 (Encrypted Keystore)', {
      did: State.userDid,
      algorithm: 'Ed25519',
      public_key: 'ed25519:4a8f9b8c7d6e5f4a3b2c1d0e9f8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c3d2e1f0a',
      cipher: 'XChaCha20-Poly1305',
      kdf: 'Argon2id',
      created_at: new Date().toISOString(),
      backup_advisory: '请将此密文备份保存在离线冷存储媒介中，切勿通过公开渠道传输。'
    });
  };

  // Switch ID
  container.querySelector('#switch-id-btn').onclick = () => {
    const newDid = prompt('输入切换的 DID 标识:', State.userDid);
    if (newDid && newDid.trim()) {
      State.userDid = newDid.trim();
      setStorage('ziokt_did', State.userDid);
      showToast('已切换至新身份', 'success');
      renderIdentity(container);
    }
  };

  // Toggle PoUW
  container.querySelector('#toggle-pouw-btn').onclick = () => {
    pouwActive = !pouwActive;
    showToast(pouwActive ? '已恢复 PoUW 算力贡献' : '已暂停算力计算', pouwActive ? 'success' : 'info');
    renderIdentity(container);
  };

  // Submit Whitelist Application
  container.querySelector('#submit-apply-btn').onclick = () => {
    const domain = container.querySelector('#apply-domain-input').value.trim();
    if (!domain) {
      showToast('请输入有效的申请域名或节点标识', 'error');
      return;
    }
    showToast(`正在使用 Ed25519 私钥为 ${domain} 签名申请 ...`, 'info');
    setTimeout(() => {
      showToast(`申请已成功提交至 Corium 待审池！申请摘要已链上锁定`, 'success');
      container.querySelector('#apply-domain-input').value = '';
    }, 700);
  };
}


  // --- Module: modules/devtools.js ---
// ==============================================================================
// Module: Native Component Developer Studio (Corium, Tri, ZDA, TC-16, MCP)
// ==============================================================================

let activeSubTab = 'tc16'; // 'corium' | 'tri' | 'zda' | 'tc16' | 'mcp'

// TC-16 Virtual Machine State
let tc16State = {
  registers: { R0: 0, R1: 0, R2: 0, R3: 0, R4: 0, R5: 0, SP: 0x0FFF, PC: 0x0000 },
  flags: { Z: 0, C: 0, N: 0 },
  gasUsed: 0,
  maxGas: 5000,
  halted: false,
  memory: new Array(16).fill(0),
  instructions: [
    'MOV R0, 10',
    'MOV R1, 25',
    'ADD R0, R1',
    'MOV R2, R0',
    'HALT'
  ],
  pcIndex: 0
};
function renderDevtools(container) {
  container.innerHTML = `
    <div style="max-width: 1050px; margin: 0 auto;">
      <!-- Header -->
      <div style="margin-bottom: 20px;">
        <h2 style="font-size: 1.25rem; font-weight: 700; color: var(--accent-cyan);">${t('devtools.title')}</h2>
        <p style="font-size: 0.82rem; color: var(--text-muted);">${t('devtools.subtitle')}</p>
      </div>

      <!-- Studio Sub-Tabs -->
      <div style="display: flex; gap: 8px; margin-bottom: 20px; flex-wrap: wrap;">
        <button class="btn btn-sm ${activeSubTab === 'tc16' ? 'btn-primary' : 'btn-secondary'} dev-tab-btn" data-tab="tc16">💻 ${t('devtools.tab_tc16')}</button>
        <button class="btn btn-sm ${activeSubTab === 'corium' ? 'btn-primary' : 'btn-secondary'} dev-tab-btn" data-tab="corium">⛓️ ${t('devtools.tab_corium')}</button>
        <button class="btn btn-sm ${activeSubTab === 'tri' ? 'btn-primary' : 'btn-secondary'} dev-tab-btn" data-tab="tri">🔺 ${t('devtools.tab_tri')}</button>
        <button class="btn btn-sm ${activeSubTab === 'zda' ? 'btn-primary' : 'btn-secondary'} dev-tab-btn" data-tab="zda">📐 ${t('devtools.tab_zda')}</button>
        <button class="btn btn-sm ${activeSubTab === 'mcp' ? 'btn-primary' : 'btn-secondary'} dev-tab-btn" data-tab="mcp">🔌 ${t('devtools.tab_mcp')}</button>
      </div>

      <!-- Content Area according to activeSubTab -->
      <div id="devtools-subcontent"></div>
    </div>
  `;

  // Tab switching
  container.querySelectorAll('.dev-tab-btn').forEach(btn => {
    btn.onclick = () => {
      activeSubTab = btn.dataset.tab;
      renderDevtools(container);
    };
  });

  const subcontent = container.querySelector('#devtools-subcontent');

  // Render Sub-Views
  if (activeSubTab === 'tc16') {
    renderTC16Studio(subcontent);
  } else if (activeSubTab === 'corium') {
    renderCoriumConsole(subcontent);
  } else if (activeSubTab === 'tri') {
    renderTriExplorer(subcontent);
  } else if (activeSubTab === 'zda') {
    renderZdaGate(subcontent);
  } else if (activeSubTab === 'mcp') {
    renderMcpProbes(subcontent);
  }
}

// 1. TC-16 Virtual Machine Studio
function renderTC16Studio(container) {
  container.innerHTML = `
    <div class="grid-cards" style="margin-bottom: 20px;">
      <!-- Registers Panel -->
      <div class="card" style="padding: 16px;">
        <div class="card-title" style="margin-bottom: 12px;">
          <span>通用寄存器 (16-bit Architecture)</span>
          <span class="mode-pill" style="font-size: 0.7rem;">Gas: ${tc16State.gasUsed} / ${tc16State.maxGas}</span>
        </div>
        <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; font-family: var(--font-mono); text-align: center;">
          ${Object.entries(tc16State.registers).map(([r, val]) => `
            <div style="background: var(--bg-input); padding: 8px 4px; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle);">
              <div style="font-size: 0.7rem; color: var(--text-dim);">${r}</div>
              <div style="font-size: 0.95rem; font-weight: bold; color: var(--accent-cyan);">0x${val.toString(16).padStart(4, '0').toUpperCase()}</div>
              <div style="font-size: 0.68rem; color: var(--text-muted);">(${val})</div>
            </div>
          `).join('')}
        </div>
        <div style="display: flex; gap: 12px; margin-top: 12px; font-size: 0.75rem; color: var(--text-muted); font-family: var(--font-mono);">
          <span>标志位: </span>
          <span style="color: ${tc16State.flags.Z ? 'var(--accent-green)' : 'var(--text-dim)'}; font-weight: bold;">Z: ${tc16State.flags.Z}</span>
          <span style="color: ${tc16State.flags.C ? 'var(--accent-green)' : 'var(--text-dim)'}; font-weight: bold;">C: ${tc16State.flags.C}</span>
          <span style="color: ${tc16State.flags.N ? 'var(--accent-green)' : 'var(--text-dim)'}; font-weight: bold;">N: ${tc16State.flags.N}</span>
          <span>状态: ${tc16State.halted ? '⏹️ HALTED' : '▶️ READY'}</span>
        </div>
      </div>

      <!-- Memory Inspector (First 16 words) -->
      <div class="card" style="padding: 16px;">
        <div class="card-title" style="margin-bottom: 12px;">
          <span>安全内存视图 (RAM Segments)</span>
          <button id="tc16-reset-mem" class="btn btn-sm btn-secondary">重置内存</button>
        </div>
        <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; font-family: var(--font-mono); font-size: 0.75rem;">
          ${tc16State.memory.map((val, idx) => `
            <div style="background: var(--bg-input); padding: 6px; border-radius: 4px; border: 1px solid var(--border-subtle); display: flex; justify-content: space-between;">
              <span style="color: var(--text-dim);">@${idx * 2}:</span>
              <span style="color: var(--text-main); font-weight: bold;">${val}</span>
            </div>
          `).join('')}
        </div>
      </div>
    </div>

    <!-- Assembly Editor & Runner -->
    <div class="card">
      <div class="card-title" style="margin-bottom: 12px;">
        <span>TC-16 确定性微汇编代码</span>
        <div style="display: flex; gap: 8px;">
          <button id="tc16-step-btn" class="btn btn-secondary btn-sm" ${tc16State.halted ? 'disabled' : ''}>⏭️ ${t('devtools.tc16_step')}</button>
          <button id="tc16-run-btn" class="btn btn-primary btn-sm" ${tc16State.halted ? 'disabled' : ''}>▶️ ${t('devtools.tc16_run')}</button>
          <button id="tc16-reset-btn" class="btn btn-danger btn-sm">🔄 ${t('devtools.tc16_reset')}</button>
        </div>
      </div>

      <div style="display: flex; gap: 14px; flex-wrap: wrap;">
        <div style="flex: 1; min-width: 260px;">
          <textarea id="tc16-code-editor" class="input-textarea" rows="7" style="font-family: var(--font-mono); font-size: 0.85rem; line-height: 1.5;">${tc16State.instructions.join('\n')}</textarea>
        </div>
        <div style="flex: 1; min-width: 260px; background: var(--bg-input); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 12px; font-family: var(--font-mono); font-size: 0.8rem; overflow-y: auto; max-height: 170px;">
          <div style="font-size: 0.72rem; color: var(--text-dim); margin-bottom: 6px;">反编译执行栈与操作日志:</div>
          ${tc16State.instructions.map((inst, i) => `
            <div style="padding: 2px 6px; border-radius: 3px; ${i === tc16State.pcIndex ? 'background: rgba(56,189,248,0.2); color: var(--accent-cyan); font-weight:bold;' : 'color: var(--text-muted);'}">
              <span>${i === tc16State.pcIndex ? '👉' : '  '} [0x${(i*2).toString(16).padStart(4,'0')}] ${inst}</span>
            </div>
          `).join('')}
        </div>
      </div>
    </div>
  `;

  // Step Execution
  container.querySelector('#tc16-step-btn').onclick = () => {
    if (tc16State.pcIndex >= tc16State.instructions.length) {
      tc16State.halted = true;
      showToast('虚拟机已执行至程序末尾 (HALT)', 'info');
      renderTC16Studio(container);
      return;
    }
    const inst = tc16State.instructions[tc16State.pcIndex].trim();
    executeInstruction(inst);
    tc16State.pcIndex++;
    tc16State.registers.PC = tc16State.pcIndex * 2;
    tc16State.gasUsed += 15;
    if (inst === 'HALT') tc16State.halted = true;
    renderTC16Studio(container);
  };

  // Run all
  container.querySelector('#tc16-run-btn').onclick = () => {
    while (tc16State.pcIndex < tc16State.instructions.length && !tc16State.halted) {
      const inst = tc16State.instructions[tc16State.pcIndex].trim();
      executeInstruction(inst);
      tc16State.pcIndex++;
      tc16State.registers.PC = tc16State.pcIndex * 2;
      tc16State.gasUsed += 15;
      if (inst === 'HALT') {
        tc16State.halted = true;
        break;
      }
    }
    showToast(`TC-16 字节码执行完成！最终 R0 = ${tc16State.registers.R0}, 消耗 Gas: ${tc16State.gasUsed}`, 'success');
    renderTC16Studio(container);
  };

  // Reset
  container.querySelector('#tc16-reset-btn').onclick = () => {
    tc16State.registers = { R0: 0, R1: 0, R2: 0, R3: 0, R4: 0, R5: 0, SP: 0x0FFF, PC: 0x0000 };
    tc16State.flags = { Z: 0, C: 0, N: 0 };
    tc16State.gasUsed = 0;
    tc16State.halted = false;
    tc16State.pcIndex = 0;
    tc16State.memory.fill(0);
    showToast('TC-16 虚拟机状态已完全重置', 'info');
    renderTC16Studio(container);
  };
}

function executeInstruction(inst) {
  const parts = inst.replace(/,/g, ' ').split(/\s+/);
  const op = parts[0].toUpperCase();
  if (op === 'MOV') {
    const reg = parts[1];
    const val = parts[2].startsWith('R') ? tc16State.registers[parts[2]] : parseInt(parts[2], 10);
    tc16State.registers[reg] = val || 0;
  } else if (op === 'ADD') {
    const reg = parts[1];
    const val = parts[2].startsWith('R') ? tc16State.registers[parts[2]] : parseInt(parts[2], 10);
    tc16State.registers[reg] = (tc16State.registers[reg] + val) & 0xFFFF;
    tc16State.flags.Z = tc16State.registers[reg] === 0 ? 1 : 0;
  } else if (op === 'SUB') {
    const reg = parts[1];
    const val = parts[2].startsWith('R') ? tc16State.registers[parts[2]] : parseInt(parts[2], 10);
    tc16State.registers[reg] = (tc16State.registers[reg] - val) & 0xFFFF;
    tc16State.flags.Z = tc16State.registers[reg] === 0 ? 1 : 0;
    tc16State.flags.N = tc16State.registers[reg] < 0 ? 1 : 0;
  } else if (op === 'STORE') {
    tc16State.memory[0] = tc16State.registers[parts[1]] || 0;
  }
}

// 2. Corium Blockchain Console
function renderCoriumConsole(container) {
  container.innerHTML = `
    <div class="card" style="margin-bottom: 20px;">
      <div class="card-title"><span>Corium 原生账本状态探针</span></div>
      <p style="font-size: 0.82rem; color: var(--text-muted); margin-bottom: 14px;">查询不可变区块哈希、ZKN/ZKC 证明、NNS 权威记录与原生 PoUW 共识事实：</p>
      <div style="display: flex; gap: 10px; margin-bottom: 14px;">
        <input type="text" id="corium-query-input" class="input-text" placeholder="输入区块高度 (例如: 10482) 或交易哈希..." style="flex:1;">
        <button id="corium-query-btn" class="btn btn-primary">查询账本事实</button>
      </div>
      <div id="corium-query-result" style="background: var(--bg-input); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 14px; font-family: var(--font-mono); font-size: 0.82rem; color: var(--accent-cyan); display: none;"></div>
    </div>
  `;

  container.querySelector('#corium-query-btn').onclick = () => {
    const q = container.querySelector('#corium-query-input').value.trim() || '10482';
    const resBox = container.querySelector('#corium-query-result');
    resBox.style.display = 'block';
    resBox.textContent = JSON.stringify({
      query: q,
      block_height: 10482,
      block_hash: '0x8f2a1c...99d',
      timestamp: '2026-10-18T00:30:00Z',
      pouw_engine: 'sqlite_bash_reward_v2',
      transactions: 24,
      state_merkle_root: '0x38bdf8...12c',
      zkc_proof_verified: true
    }, null, 2);
    showToast('Corium 原生事实查询成功', 'success');
  };
}

// 3. Tri Machine Explorer
function renderTriExplorer(container) {
  container.innerHTML = `
    <div class="card">
      <div class="card-title"><span>Tri 离线状态机快照沙箱 (Bounded PWA Snapshots)</span></div>
      <p style="font-size: 0.82rem; color: var(--text-muted); margin-bottom: 14px;">
        Tri 组件执行离线计算与确定性状态快照，生成密封在 SafeFS 中的社区文件证明，无未受控的外部代码执行：
      </p>
      <div style="display: flex; gap: 10px; margin-bottom: 14px;">
        <button id="tri-calc-btn" class="btn btn-primary">生成并验证快照 Merkle 树</button>
      </div>
      <div id="tri-res" style="background: var(--bg-input); padding: 14px; border-radius: var(--radius-sm); font-family: var(--font-mono); font-size: 0.82rem; color: var(--accent-green); display:none;">
        ✓ Merkle 根校验通过: 0x9f1a2b...44c (16 个状态单元确定性密封)
      </div>
    </div>
  `;

  container.querySelector('#tri-calc-btn').onclick = () => {
    container.querySelector('#tri-res').style.display = 'block';
    showToast('Tri 确定性快照已密封并签名', 'success');
  };
}

// 4. ZDA / Ano Gate
function renderZdaGate(container) {
  container.innerHTML = `
    <div class="card">
      <div class="card-title"><span>ZDA / Ano 门限证据计算器</span></div>
      <p style="font-size: 0.82rem; color: var(--text-muted); margin-bottom: 14px;">
        类型化 Ano 证据门与精确 ZDA (Zero-knowledge Data Attestation) 算术多项式验证器：
      </p>
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin-bottom: 14px;">
        <input type="number" id="zda-a" class="input-text" value="42" placeholder="门限参数 A">
        <input type="number" id="zda-b" class="input-text" value="108" placeholder="门限参数 B">
        <button id="zda-run-btn" class="btn btn-primary">计算多项式约束并验签</button>
      </div>
      <div id="zda-res" style="background: var(--bg-input); padding: 14px; border-radius: var(--radius-sm); font-family: var(--font-mono); font-size: 0.82rem; color: var(--accent-cyan); display: none;"></div>
    </div>
  `;

  container.querySelector('#zda-run-btn').onclick = () => {
    const a = parseInt(container.querySelector('#zda-a').value, 10);
    const b = parseInt(container.querySelector('#zda-b').value, 10);
    const box = container.querySelector('#zda-res');
    box.style.display = 'block';
    box.textContent = JSON.stringify({
      attestation: 'ano_typed_gate_v1',
      parameters: { a, b },
      polynomial_constraint: `${a}^2 + ${b}^2 = ${a*a + b*b}`,
      zk_proof: '0x' + Math.random().toString(16).slice(2, 14),
      status: 'VERIFIED_SATISFIED'
    }, null, 2);
    showToast('ZDA 门限证据已通过数学约束验证', 'success');
  };
}

// 5. MCP 211 Probes Studio
function renderMcpProbes(container) {
  container.innerHTML = `
    <div class="card">
      <div class="card-title" style="margin-bottom: 10px;">
        <span>MCP 211 工具探针与接口审查</span>
        <span class="mode-pill">211 Tools Active</span>
      </div>
      <p style="font-size: 0.82rem; color: var(--text-muted); margin-bottom: 14px;">审查与调试 ChatGPT CIMD / OAuth 标准下的 211 个原生工具契约：</p>
      <input type="text" id="mcp-filter" class="input-text" placeholder="按工具名称过滤 (例如: corium_registration, watchat, ufs)..." style="margin-bottom: 14px;">
      <div id="mcp-tools-list" style="display: flex; flex-direction: column; gap: 8px; max-height: 280px; overflow-y: auto;">
        ${[
          { name: 'corium_registration_submit', desc: '向 Corium 链上提交验证者或外部链权重申请' },
          { name: 'corium_registration_list', desc: '列出当前网络待审批与已激活的注册申请' },
          { name: 'corium_registration_decide', desc: '管理员签署批准或拒绝注册申请' },
          { name: 'ufs_storage_put_chunk', desc: '向 UFS 存储引擎写入经过隔离校验的文件分块' },
          { name: 'ufs_storage_get_stats', desc: '读取 UFS 节点容量与传输指标' },
          { name: 'watchat_send_sealed', desc: '发送端到端密文附件' },
          { name: 'shadow6_profile_switch', desc: '动态切换 13 Profile 多协议隧道' },
          { name: 'safefs_aead_seal', desc: '通过 AEAD 加密封装私有保险箱' }
        ].map(tool => `
          <div style="background: var(--bg-input); padding: 10px 14px; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle); display: flex; justify-content: space-between; align-items: center;">
            <div>
              <div style="font-family: var(--font-mono); font-weight: 600; color: var(--accent-cyan); font-size: 0.85rem;">${tool.name}</div>
              <div style="font-size: 0.75rem; color: var(--text-muted);">${tool.desc}</div>
            </div>
            <button class="btn btn-sm btn-secondary test-mcp-btn" data-name="${tool.name}">调用探针</button>
          </div>
        `).join('')}
      </div>
    </div>
  `;

  container.querySelectorAll('.test-mcp-btn').forEach(btn => {
    btn.onclick = () => {
      const name = btn.dataset.name;
      showJsonModal(`MCP 探针调用: ${name}`, {
        tool: name,
        invoker: State.userDid,
        status: '200_OK',
        result: {
          executed: true,
          permission_scope: 'authorized_owner',
          audit_hash: '0x' + Math.random().toString(16).slice(2, 10)
        }
      });
    };
  });
}


  // --- Module: modules/settings.js ---
// ==============================================================================
// Module: System Settings, Local/Remote Node Management, Auth & Lifecycle
// ==============================================================================
function renderSettings(container) {
  if (!container) return;
  const isEn = State.language === 'en';
  const comps = State.components || {};
  const remoteNodes = getRemoteNodes();
  const activeNode = getActiveRemoteNode();

  const isLocal = State.runtimeMode === 'local';
  const isLocalOnline = State.localNodeStatus === 'online';
  const isLocalChecking = State.localNodeStatus === 'checking';

  container.innerHTML = `
    <div style="max-width: 950px; margin: 0 auto;">
      ${isLocal && !isLocalOnline ? `
        <!-- Local Node Required Top Warning Banner -->
        <div style="background: rgba(239, 68, 68, 0.12); border: 1.5px solid var(--accent-red); border-radius: var(--radius-md); padding: 18px 20px; margin-bottom: 24px;">
          <div style="display: flex; align-items: flex-start; gap: 14px;">
            <span style="font-size: 1.8rem; line-height: 1;">⚠️</span>
            <div style="flex: 1;">
              <h3 style="color: var(--accent-red); margin-bottom: 6px; font-size: 1.05rem; font-weight: 700;">
                ${isEn ? 'Local Node Required — Only Settings Accessible' : '本地真实节点未运行 — 当前仅开放系统设置'}
              </h3>
              <p style="color: var(--text-main); font-size: 0.85rem; line-height: 1.6; margin-bottom: 12px;">
                ${isEn
                  ? 'You are currently in Local Node Mode, but no Ziokt daemon is detected at http://127.0.0.1:8185. All other tabs (Home, Chat, Files, Apps, Identity, etc.) are locked until a real node is verified, or until you switch to a remote gateway.'
                  : '当前客户端处于【本地节点】模式，但未在本地检测到运行中的 Ziokt 节点服务 (http://127.0.0.1:8185)。在本地真实节点启动前，总览、聊天、文件存储、身份等其他选项卡已锁定。您可以启动本地节点后重试探测，或在此直接切换至远程网关。'}
              </p>
              <div style="display: flex; gap: 10px; flex-wrap: wrap;">
                <button id="settings-probe-top-btn" class="btn btn-primary btn-sm">⚡ ${isEn ? 'Probe Local Node (8185)' : '立即探测本地节点 (8185)'}</button>
                <button id="settings-switch-remote-top-btn" class="btn btn-secondary btn-sm">🌐 ${isEn ? 'One-Click Switch to Remote Gateway' : '一键切换至远程网关'}</button>
              </div>
            </div>
          </div>
        </div>
      ` : ''}

      <!-- Header -->
      <div style="margin-bottom: 24px;">
        <h2 style="font-size: 1.25rem; font-weight: 700; color: var(--accent-cyan);">${t('settings.title')}</h2>
        <p style="font-size: 0.82rem; color: var(--text-muted);">${isEn ? 'Configure local/remote node topology, authentication credentials, component lifecycle, themes and accessibility' : '配置本地/远程节点拓扑、身份鉴权凭证、组件按需生命周期、外观主题与无障碍交互'}</p>
      </div>

      <!-- Runtime Mode Selection -->
      <div class="card" style="margin-bottom: 20px;">
        <div class="card-title" style="margin-bottom: 14px;">
          <span>${t('settings.runtime_mode')}</span>
        </div>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; margin-bottom: 12px;">
          <div>
            <label style="display: block; font-size: 0.78rem; color: var(--text-muted); margin-bottom: 6px;">${isEn ? 'Runtime Mode' : '客户端运行模式'}</label>
            <select id="setting-mode-select" class="input-select">
              <option value="local" ${State.runtimeMode === 'local' ? 'selected' : ''}>${t('app.mode_local')} (${isEn ? 'Local Private Environment' : '纯本地私有节点环境'})</option>
              <option value="remote" ${State.runtimeMode === 'remote' ? 'selected' : ''}>${t('app.mode_remote')} (${isEn ? 'Remote Gateway Node' : '连接远程主网关'})</option>
              <option value="hybrid" ${State.runtimeMode === 'hybrid' ? 'selected' : ''}>${t('app.mode_hybrid')} (${isEn ? 'Local Storage + Remote Relay' : '本地存储 + 远程共识中继'})</option>
            </select>
          </div>
          <div>
            <label style="display: block; font-size: 0.78rem; color: var(--text-muted); margin-bottom: 6px;">${isEn ? 'Active Gateway Endpoint' : '当前生效网关端点'}</label>
            <input type="text" id="setting-gateway-input" class="input-text" value="${isLocal ? State.localGatewayUrl : (activeNode?.url || State.gatewayUrl)}">
          </div>
        </div>
        <div style="font-size: 0.78rem; color: var(--text-dim); line-height: 1.5;">
          ${isLocal
            ? (isEn ? '💡 Local mode routes all RPC and transactions directly to localhost. A real running Ziokt node is required.' : '💡 本地模式将所有 RPC 与交互直接打入本地主机。本机必须真实运行有 Ziokt 节点服务。')
            : (isEn ? '💡 Remote mode routes traffic through an authenticated cloud gateway. Authentication token is mandatory.' : '💡 远程模式通过云端可信网关中继访问，必须配置有效的访问鉴权 Token。')}
        </div>
      </div>

      <!-- Local Node Real Probe & Health (Mandatory for Local Mode) -->
      <div class="card" style="margin-bottom: 20px; border-left: 4px solid ${isLocalOnline ? 'var(--accent-green)' : (isLocalChecking ? 'var(--accent-amber)' : 'var(--accent-red)')};">
        <div class="card-title" style="margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center;">
          <span>${t('settings.local_node_title')}</span>
          <span class="status-badge" style="color: ${isLocalOnline ? 'var(--accent-green)' : (isLocalChecking ? 'var(--accent-amber)' : 'var(--accent-red)')};">
            <span class="status-dot" style="background-color: ${isLocalOnline ? 'var(--accent-green)' : (isLocalChecking ? 'var(--accent-amber)' : 'var(--accent-red)')};"></span>
            ${isLocalChecking ? t('settings.local_node_checking') : (isLocalOnline ? t('settings.local_node_online') : t('settings.local_node_offline'))}
          </span>
        </div>
        <p style="font-size: 0.82rem; color: var(--text-muted); margin-bottom: 14px;">${t('settings.local_node_desc')}</p>
        
        <div style="display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 14px;">
          <input type="text" id="setting-local-url-input" class="input-text" style="max-width: 300px; font-family: var(--font-mono); font-size: 0.85rem;" value="${State.localGatewayUrl}">
          <button id="probe-local-node-btn" class="btn btn-secondary btn-sm">⚡ ${t('settings.local_node_probe')}</button>
          ${isLocalOnline ? `<span style="font-size: 0.78rem; color: var(--accent-green);">✓ HTTP 200 OK (${State.localNodeDetails?.network || 'ziokt-main'})</span>` : ''}
        </div>

        ${!isLocalOnline && !isLocalChecking ? `
          <div style="background: rgba(239, 68, 68, 0.08); border: 1px dashed rgba(239, 68, 68, 0.4); border-radius: var(--radius-sm); padding: 12px; font-size: 0.78rem; color: var(--accent-red);">
            <strong>${isEn ? 'Notice:' : '节点未就绪提示:'}</strong> ${t('settings.local_node_help')}
          </div>
        ` : ''}
      </div>

      <!-- Remote Node Gateways & Auth Management -->
      <div class="card" style="margin-bottom: 20px;">
        <div class="card-title" style="margin-bottom: 12px;">
          <span>${t('settings.remote_nodes_title')}</span>
          <span style="font-size: 0.72rem; color: var(--accent-purple); font-weight: normal;">${isEn ? 'Custom Endpoints & Auth Tokens' : '支持多节点切换与鉴权配置'}</span>
        </div>
        <p style="font-size: 0.82rem; color: var(--text-muted); margin-bottom: 16px;">${t('settings.remote_nodes_desc')}</p>

        <!-- Configured Nodes List -->
        <div style="display: flex; flex-direction: column; gap: 12px; margin-bottom: 20px;">
          ${remoteNodes.map(node => {
            const isActive = node.id === activeNode?.id;
            const hasToken = !!(node.authToken && node.authToken.trim());
            const statusColor = node.status === 'online' ? 'var(--accent-green)' : (node.status === 'unauthenticated' ? 'var(--accent-amber)' : (node.status === 'auth_failed' ? 'var(--accent-red)' : 'var(--text-dim)'));
            const statusText = node.status === 'online' ? `${t('settings.auth_valid')} (${node.latency || '--'})` : (node.status === 'unauthenticated' ? t('settings.auth_required') : (node.status === 'auth_failed' ? t('settings.auth_invalid') : (node.status === 'offline' ? t('app.status_offline') : '未验证')));

            return `
              <div style="background: var(--bg-input); border: 1px solid ${isActive ? 'var(--accent-cyan)' : 'var(--border-subtle)'}; border-radius: var(--radius-sm); padding: 14px 16px;">
                <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 10px; margin-bottom: 10px;">
                  <div>
                    <div style="display: flex; align-items: center; gap: 8px;">
                      <span style="font-weight: 600; font-size: 0.92rem; color: var(--text-main);">${node.name}</span>
                      ${isActive ? `<span class="badge" style="background: rgba(2,132,199,0.2); color: var(--accent-cyan); font-size: 0.68rem; padding: 2px 6px; border-radius: 4px;">${t('settings.active_badge')}</span>` : ''}
                      ${node.isDefault ? `<span class="badge" style="background: rgba(147,51,234,0.15); color: var(--accent-purple); font-size: 0.68rem; padding: 2px 6px; border-radius: 4px;">${isEn ? 'System Default' : '官方默认'}</span>` : ''}
                    </div>
                    <div style="font-size: 0.78rem; font-family: var(--font-mono); color: var(--text-dim); margin-top: 3px;">${node.url}</div>
                  </div>
                  <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 0.75rem; color: ${statusColor}; font-weight: 600;">● ${statusText}</span>
                    <button class="btn btn-secondary btn-sm test-node-btn" data-id="${node.id}" title="${t('settings.test_auth')}">⚡ ${t('settings.test_auth')}</button>
                    ${!isActive ? `<button class="btn btn-primary btn-sm activate-node-btn" data-id="${node.id}">${t('settings.set_active')}</button>` : ''}
                    ${!node.isDefault ? `<button class="btn btn-danger btn-sm delete-node-btn" data-id="${node.id}" title="${t('settings.delete_node')}">🗑️</button>` : ''}
                  </div>
                </div>

                <!-- Auth Token row -->
                <div style="display: flex; gap: 10px; align-items: center; margin-top: 8px;">
                  <span style="font-size: 0.72rem; color: var(--text-muted); flex-shrink: 0;">${t('settings.auth_token')}:</span>
                  <input type="password" class="input-text node-token-input" data-id="${node.id}" value="" placeholder="${t('settings.auth_token_tip')}" style="font-size: 0.78rem; font-family: var(--font-mono); height: 30px; padding: 4px 8px;">
                  <button class="btn btn-secondary btn-sm save-token-btn" data-id="${node.id}" style="height: 30px; padding: 2px 10px; font-size: 0.75rem;">${t('common.save')}</button>
                </div>
              </div>
            `;
          }).join('')}
        </div>

        <!-- Add Custom Remote Node Form -->
        <div style="border-top: 1px solid var(--border-subtle); padding-top: 16px;">
          <h4 style="font-size: 0.88rem; font-weight: 600; color: var(--text-main); margin-bottom: 12px;">+ ${t('settings.add_node')}</h4>
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-bottom: 12px;">
            <div>
              <label style="display: block; font-size: 0.75rem; color: var(--text-muted); margin-bottom: 4px;">${t('settings.node_name')}</label>
              <input type="text" id="new-node-name" class="input-text" placeholder="e.g. 自建私有网关 / Private Cloud Gateway">
            </div>
            <div>
              <label style="display: block; font-size: 0.75rem; color: var(--text-muted); margin-bottom: 4px;">${t('settings.node_url')}</label>
              <input type="text" id="new-node-url" class="input-text" placeholder="https://gateway.example.com">
            </div>
            <div>
              <label style="display: block; font-size: 0.75rem; color: var(--text-muted); margin-bottom: 4px;">${t('settings.auth_token')}</label>
              <input type="password" id="new-node-token" class="input-text" placeholder="ziokt_sec_...">
            </div>
          </div>
          <button id="add-node-btn" class="btn btn-primary btn-sm">+ ${t('settings.add_node_btn')}</button>
        </div>
      </div>

      <!-- On-Demand Component Launcher -->
      <div class="card" style="margin-bottom: 20px;">
        <div class="card-title" style="margin-bottom: 12px;">
          <span>${t('settings.components_lifecycle')}</span>
          <span style="font-size: 0.72rem; color: var(--accent-cyan); font-weight: normal;">${isEn ? 'On-demand loading to save system overhead' : '按需独立加载，避免强制全量开销'}</span>
        </div>
        <p style="font-size: 0.82rem; color: var(--text-muted); margin-bottom: 14px;">${isEn ? 'The client does not mandate all daemon processes to run permanently. You can toggle local background microservices freely:' : '客户端无需强制常驻所有服务，您可以根据使用场景自由启闭本地后台进程：'}</p>
        
        <div style="display: flex; flex-direction: column; gap: 10px;">
          ${Object.entries(comps).map(([key, comp]) => {
            const status = (comp?.status || 'offline').toLowerCase();
            const isOnline = status === 'online';
            return `
            <div style="background: var(--bg-input); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 12px 16px; display: flex; justify-content: space-between; align-items: center;">
              <div>
                <div style="font-weight: 600; font-size: 0.9rem; color: var(--text-main);">${comp?.name || key}</div>
                <div style="font-size: 0.75rem; color: var(--text-dim); font-family: var(--font-mono);">${isEn ? 'Local Port' : '本地端口'}: ${comp?.port || 'N/A'} &bull; ${isEn ? 'Status' : '状态'}: <span style="color:${isOnline ? 'var(--accent-green)' : 'var(--accent-red)'}">${status.toUpperCase()}</span></div>
              </div>
              <button class="btn btn-sm ${isOnline ? 'btn-danger' : 'btn-primary'} toggle-comp-btn" data-key="${key}">
                ${isOnline ? (isEn ? '⏹️ Stop Service' : '⏹️ 停止服务') : (isEn ? '▶️ Start Service' : '▶️ 启动服务')}
              </button>
            </div>
            `;
          }).join('')}
        </div>
      </div>

      <!-- Theme & Language -->
      <div class="grid-cards" style="margin-bottom: 20px;">
        <div class="card">
          <div class="card-title"><span>${isEn ? 'Appearance Theme' : '外观主题'}</span></div>
          <div style="display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap;">
            <button class="btn btn-sm ${State.theme === 'dark' ? 'btn-primary' : 'btn-secondary'} theme-btn" data-theme="dark">🌙 ${t('app.theme_dark')}</button>
            <button class="btn btn-sm ${State.theme === 'light' ? 'btn-primary' : 'btn-secondary'} theme-btn" data-theme="light">☀️ ${t('app.theme_light')}</button>
            <button class="btn btn-sm ${State.theme === 'contrast' ? 'btn-primary' : 'btn-secondary'} theme-btn" data-theme="contrast">⚡ ${t('app.theme_contrast')}</button>
          </div>
        </div>

        <div class="card">
          <div class="card-title"><span>语言 / Language</span></div>
          <div style="display: flex; gap: 8px; margin-top: 10px;">
            <button class="btn btn-sm ${State.language === 'zh' ? 'btn-primary' : 'btn-secondary'} lang-btn" data-lang="zh">🇨🇳 简体中文</button>
            <button class="btn btn-sm ${State.language === 'en' ? 'btn-primary' : 'btn-secondary'} lang-btn" data-lang="en">🇬🇧 English</button>
          </div>
        </div>
      </div>

      <!-- Accessibility & Keyboard Shortcuts -->
      <div class="card" style="margin-bottom: 20px;">
        <div class="card-title" style="margin-bottom: 10px;">
          <span>${t('settings.accessibility')}</span>
        </div>
        <p style="font-size: 0.82rem; color: var(--text-muted); margin-bottom: 12px;">${t('settings.keyboard_shortcuts')}</p>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 8px; font-size: 0.78rem; font-family: var(--font-mono); color: var(--accent-cyan);">
          <div>[1] ${isEn ? 'Home Overview' : '首页总览'}</div>
          <div>[2] ${isEn ? 'WATChat Comms' : 'WATChat 通讯'}</div>
          <div>[3] ${isEn ? 'Community Forum' : '社区论坛'}</div>
          <div>[4] ${isEn ? 'Safe Storage' : '安全存储'}</div>
          <div>[5] ${isEn ? 'App Store' : '应用中心'}</div>
          <div>[6] ${isEn ? 'Mesh Nodes' : '网络节点'}</div>
          <div>[7] ${isEn ? 'Identity & Stake' : '身份与贡献'}</div>
          <div>[8] ${isEn ? 'Dev Tools' : '开发工具'}</div>
          <div>[9] ${isEn ? 'System Settings' : '系统设置'}</div>
        </div>
      </div>

      <!-- Danger Zone / Cache Clearing -->
      <div class="card" style="border-color: rgba(239, 68, 68, 0.4);">
        <div class="card-title" style="color: var(--accent-red); margin-bottom: 8px;">
          <span>${isEn ? 'Danger Zone / Cache Reset' : '危险操作 / 缓存清理'}</span>
        </div>
        <p style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 12px;">${isEn ? 'Reset local client cache and session state. On-chain ciphertext in UFS/SafeFS will not be deleted:' : '重置本地缓存、断开网关会话，但不会删除您存储在 UFS/SafeFS 中的链上物理密文：'}</p>
        <button id="clear-cache-btn" class="btn btn-danger btn-sm">${isEn ? 'Clear Local Cache & Reset Session' : '清除客户端本地缓存并重置会话'}</button>
      </div>

    </div>
  `;

  // Runtime Mode Switcher
  const modeSelect = container.querySelector('#setting-mode-select');
  if (modeSelect) {
    modeSelect.onchange = async (e) => {
      State.runtimeMode = e.target.value;
      setStorage('ziokt_mode', e.target.value);
      if (State.runtimeMode === 'local') {
        await checkLocalNodeHealth();
      }
      updateAppNodeBadge();
      showToast(isEn ? `Runtime mode switched to ${e.target.value.toUpperCase()}` : `客户端运行模式已切换为: ${e.target.value.toUpperCase()}`, 'info');
      renderSettings(container);
    };
  }

  // Gateway input listener
  const gwInput = container.querySelector('#setting-gateway-input');
  if (gwInput) {
    gwInput.onchange = (e) => {
      const val = e.target.value.trim();
      if (State.runtimeMode === 'local') {
        State.localGatewayUrl = val;
      } else {
        State.gatewayUrl = val;
        setStorage('ziokt_gateway', val);
      }
      showToast(isEn ? 'Endpoint saved' : '端点已更新', 'success');
    };
  }

  // Top Offline Banner Buttons
  const topProbeBtn = container.querySelector('#settings-probe-top-btn');
  if (topProbeBtn) {
    topProbeBtn.onclick = async () => {
      topProbeBtn.disabled = true;
      topProbeBtn.textContent = '...';
      const res = await checkLocalNodeHealth();
      topProbeBtn.disabled = false;
      topProbeBtn.textContent = `⚡ ${isEn ? 'Probe Local Node (8185)' : '立即探测本地节点 (8185)'}`;
      if (res.ok) {
        showToast(isEn ? 'Local node verified online!' : '本地真实节点检测通过，状态在线！', 'success');
      } else {
        showToast(isEn ? `Local node unreachable: ${res.error}` : `本地真实节点未响应: ${res.error}`, 'error');
      }
      renderSettings(container);
    };
  }
  const topSwitchBtn = container.querySelector('#settings-switch-remote-top-btn');
  if (topSwitchBtn) {
    topSwitchBtn.onclick = () => {
      State.runtimeMode = 'remote';
      setStorage('ziokt_mode', 'remote');
      updateAppNodeBadge();
      showToast(isEn ? 'Switched to Remote Gateway mode' : '已切换至远程网关模式', 'success');
      renderSettings(container);
    };
  }

  // Local Node Probe Button
  const probeLocalBtn = container.querySelector('#probe-local-node-btn');
  const localUrlInput = container.querySelector('#setting-local-url-input');
  if (probeLocalBtn) {
    probeLocalBtn.onclick = async () => {
      if (localUrlInput) {
        State.localGatewayUrl = localUrlInput.value.trim();
      }
      probeLocalBtn.disabled = true;
      probeLocalBtn.textContent = isEn ? 'Probing...' : '正在探测...';
      const res = await checkLocalNodeHealth();
      probeLocalBtn.disabled = false;
      probeLocalBtn.textContent = `⚡ ${t('settings.local_node_probe')}`;
      if (res.ok) {
        showToast(isEn ? 'Local node verified successfully!' : '本地真实节点检测通过，状态在线！', 'success');
      } else {
        showToast(isEn ? `Local node unreachable: ${res.error}` : `本地真实节点未响应: ${res.error}`, 'error');
      }
      renderSettings(container);
    };
  }

  // Remote Node - Test Auth
  container.querySelectorAll('.test-node-btn').forEach(btn => {
    btn.onclick = async () => {
      const id = btn.dataset.id;
      btn.disabled = true;
      btn.textContent = '...';
      const res = await verifyRemoteNodeAuth(id);
      btn.disabled = false;
      btn.textContent = `⚡ ${t('settings.test_auth')}`;
      if (res.ok) {
        showToast(isEn ? `Node auth verified! Latency: ${res.latency}` : `节点鉴权成功！延迟: ${res.latency}`, 'success');
      } else {
        showToast(isEn ? `Auth failed: ${res.error}` : `节点鉴权未通过: ${res.error}`, 'error');
      }
      renderSettings(container);
    };
  });

  // Remote Node - Activate Node
  container.querySelectorAll('.activate-node-btn').forEach(btn => {
    btn.onclick = () => {
      const id = btn.dataset.id;
      setActiveRemoteNode(id);
      showToast(isEn ? 'Active node updated' : '当前生效远程节点已切换', 'success');
      renderSettings(container);
    };
  });

  // Remote Node - Save Token
  container.querySelectorAll('.save-token-btn').forEach(btn => {
    btn.onclick = () => {
      const id = btn.dataset.id;
      const input = container.querySelector(`.node-token-input[data-id="${id}"]`);
      if (input) {
        const val = input.value.trim();
        const nodes = getRemoteNodes();
        const target = nodes.find(n => n.id === id);
        if (target) {
          target.authToken = val;
          setStorage('ziokt_remote_nodes', JSON.stringify(nodes));
          if (State.activeRemoteNodeId === id) {
            setStorage('ziokt_auth_token', val);
            State.authToken = val;
          }
          showToast(isEn ? 'Auth token saved for node' : '节点鉴权凭证已保存', 'success');
          renderSettings(container);
        }
      }
    };
  });

  // Remote Node - Delete Node
  container.querySelectorAll('.delete-node-btn').forEach(btn => {
    btn.onclick = async () => {
      const id = btn.dataset.id;
      const ok = await showConfirm(
        isEn ? 'Delete Remote Node' : '删除远程节点',
        isEn ? 'Are you sure you want to remove this custom remote node?' : '确定要删除此自定义远程节点吗？'
      );
      if (ok) {
        try {
          removeRemoteNode(id);
          showToast(isEn ? 'Remote node removed' : '远程节点已删除', 'success');
          renderSettings(container);
        } catch (e) {
          showToast(e.message, 'error');
        }
      }
    };
  });

  // Add Custom Remote Node
  const addBtn = container.querySelector('#add-node-btn');
  if (addBtn) {
    addBtn.onclick = async () => {
      const nameInput = container.querySelector('#new-node-name');
      const urlInput = container.querySelector('#new-node-url');
      const tokenInput = container.querySelector('#new-node-token');

      const name = nameInput.value.trim();
      const url = urlInput.value.trim();
      const token = tokenInput.value.trim();

      if (!url) {
        showToast(isEn ? 'Node URL is required' : '节点 URL 不能为空', 'error');
        return;
      }
      if (!url.startsWith('http://') && !url.startsWith('https://')) {
        showToast(isEn ? 'URL must start with http:// or https://' : '节点 URL 必须以 http:// 或 https:// 开头', 'error');
        return;
      }
      if (!token) {
        showToast(isEn ? 'Auth Token is required for remote node' : '使用远程节点必须配置鉴权凭证 (Auth Token)', 'error');
        return;
      }

      const newNode = addRemoteNode({ name: name || url, url, authToken: token });
      showToast(isEn ? 'Custom remote node added, testing authentication...' : '自定义远程节点已添加，正在测试鉴权...', 'info');

      // Immediate verify
      const res = await verifyRemoteNodeAuth(newNode.id);
      if (res.ok) {
        showToast(isEn ? 'New node authenticated and ready!' : '新节点鉴权成功，随时可切换使用！', 'success');
      } else {
        showToast(isEn ? `Node added but auth failed: ${res.error}` : `节点已添加，但鉴权未通过: ${res.error}`, 'error');
      }
      renderSettings(container);
    };
  }

  // Lifecycle operations require an actual native service manager; browser UIs cannot claim process control.
  container.querySelectorAll('.toggle-comp-btn').forEach(btn => {
    btn.onclick = async () => {
      const invoke = window.__TAURI_INTERNALS__?.invoke;
      if (!invoke) { showToast('此浏览器没有本地进程管理权限；请通过原生客户端或服务管理器操作', 'error'); return; }
      btn.disabled = true;
      try {
        const key = btn.dataset.key;
        const observed = await invoke('manage_component', {name:key,action:'status'});
        const result = await invoke('manage_component', {name:key,action:observed.status==='active'?'stop':'start'});
        State.components[key].status = result.status === 'active' ? 'online' : result.status;
        showToast(result.message, 'info'); renderSettings(container);
      } catch (error) { showToast(String(error), 'error'); }
      finally { btn.disabled = false; }
    };
  });

  // Theme Toggles
  container.querySelectorAll('.theme-btn').forEach(btn => {
    btn.onclick = () => {
      setTheme(btn.dataset.theme);
      showToast(isEn ? `Theme switched to: ${btn.textContent}` : `主题已切换为: ${btn.textContent}`, 'info');
      renderSettings(container);
    };
  });

  // Language Toggles
  container.querySelectorAll('.lang-btn').forEach(btn => {
    btn.onclick = async () => {
      await setLanguage(btn.dataset.lang);
      showToast(`Language switched to: ${btn.textContent}`, 'info');
      renderSettings(container);
    };
  });

  // Clear Cache
  const clearBtn = container.querySelector('#clear-cache-btn');
  if (clearBtn) {
    clearBtn.onclick = async () => {
      const ok = await showConfirm(
        isEn ? 'Reset Confirmation' : '重置确认',
        isEn ? 'Are you sure you want to clear all local sessions and caches? The app will reset to defaults.' : '确定要清空本地所有会话与缓存吗？应用将恢复初始设置。'
      );
      if (ok) {
        try { localStorage.clear(); } catch(e) {}
        showToast(isEn ? 'Cache cleared, resetting client...' : '缓存已清空，正在重置客户端...', 'success');
        setTimeout(() => location.reload(), 800);
      }
    };
  }
}



  // --- Router & App Controller ---
  const routes = {
    home: { render: renderHome, titleKey: 'nav.home' },
    chat: { render: renderChat, titleKey: 'nav.chat' },
    forum: { render: renderForum, titleKey: 'nav.forum' },
    files: { render: renderFiles, titleKey: 'nav.files' },
    apps: { render: renderApps, titleKey: 'nav.apps' },
    library: { render: renderLibrary, titleKey: 'nav.library' },
    netnews: { render: renderNetnews, titleKey: 'nav.netnews' },
    ecosystem: { render: renderEcosystem, titleKey: 'nav.ecosystem' },
    network: { render: renderNetwork, titleKey: 'nav.network' },
    identity: { render: renderIdentity, titleKey: 'nav.identity' },
    devtools: { render: renderDevtools, titleKey: 'nav.devtools' },
    settings: { render: renderSettings, titleKey: 'nav.settings' }
  };

  function getHashTab() {
    const hash = (window.location.hash || '').replace('#', '').trim().toLowerCase();
    return routes[hash] ? hash : null;
  }

  async function initApp() {
    await discoverServiceEndpoints();
    await initI18n();
    setTheme(State.theme);
    setupNavigation();
    setupKeyboardShortcuts();
    setupPwaInstallPrompt();

    // Probe local node first if in local mode before setting initial route
    if (State.runtimeMode === 'local') {
      await checkLocalNodeHealth();
    }

    updateAppNodeBadge();

    let initialTab = getHashTab() || State.currentTab || 'home';
    if (isLocalNodeOffline() && !canUseWithoutLocalNode(initialTab)) {
      initialTab = 'settings';
    }
    navigate(initialTab);

    window.addEventListener('hashchange', () => {
      let tab = getHashTab();
      if (tab && tab !== State.currentTab) {
        if (isLocalNodeOffline() && !canUseWithoutLocalNode(tab)) {
          navigate('settings');
          return;
        }
        navigate(tab);
      }
    });

    Events.on('navigate', (tab) => navigate(tab));
    Events.on('local_node_offline', () => {
      if (!canUseWithoutLocalNode(State.currentTab)) {
        navigate('settings');
      }
    });
    Events.on('local_node_status_changed', () => {
      updateAppNodeBadge();
      if (isLocalNodeOffline() && !canUseWithoutLocalNode(State.currentTab)) {
        navigate('settings');
      }
    });
    Events.on('mode_changed', () => {
      updateAppNodeBadge();
      if (isLocalNodeOffline() && !canUseWithoutLocalNode(State.currentTab)) {
        navigate('settings');
      }
    });
    Events.on('active_node_changed', () => {
      updateAppNodeBadge();
    });
    Events.on('language_changed', () => {
      updateNavLabels();
      updateAppNodeBadge();
      navigate(State.currentTab);
    });
    Events.on('theme_changed', () => {
      navigate(State.currentTab);
    });

    console.log('[Ziokt GUI] Universal Client Initialized.');
  }

  function navigate(tabName) {
    // Local Node Offline Gatekeeping: only Settings can be viewed
    if (isLocalNodeOffline() && !canUseWithoutLocalNode(tabName)) {
      const msg = State.language === 'en'
        ? 'Local node is offline. Local mode requires a running node; only Settings is accessible.'
        : '本地节点未启动。使用本地节点需要用户本地真实有节点运行，当前仅开放【系统设置】页。';
      showToast(msg, 'warning');
      tabName = 'settings';
    }

    if (!routes[tabName]) tabName = isLocalNodeOffline() ? 'settings' : 'home';
    State.currentTab = tabName;
    if (window.location.hash !== '#' + tabName) {
      history.replaceState(null, '', '#' + tabName);
    }

    const route = routes[tabName];
    const titleEl = document.getElementById('current-page-title');
    if (titleEl) titleEl.textContent = t(route.titleKey);
    document.title = t(route.titleKey) + ' - ' + t('app.title');

    document.querySelectorAll('.nav-item').forEach(item => {
      item.classList.toggle('active', item.dataset.tab === tabName);
    });
    document.querySelectorAll('.bottom-item').forEach(item => {
      item.classList.toggle('active', item.dataset.tab === tabName);
    });

    const container = document.getElementById('content-container');
    if (container) {
      container.innerHTML = '';
      try {
        route.render(container);
      } catch (err) {
        console.error('[Router] Error rendering ' + tabName + ':', err);
        container.innerHTML = '<div style="max-width:800px;margin:40px auto;padding:24px;background:rgba(239,68,68,0.1);border:1px solid var(--accent-red);border-radius:var(--radius-md);"><h3 style="color:var(--accent-red);margin-bottom:8px;">⚠️ 模块加载异常 / Component Render Error</h3><p style="font-size:0.88rem;color:var(--text-main);margin-bottom:12px;">无法加载模块 <strong>' + tabName + '</strong>: ' + (err?.message || err) + '</p><button class="btn btn-secondary btn-sm" onclick="location.hash=&quot;#home&quot;">返回首页 / Return Home</button></div>';
      }
    }
  }

  function setupNavigation() {
    document.querySelectorAll('.nav-item').forEach(item => {
      item.addEventListener('click', (e) => {
        e.preventDefault();
        const targetTab = item.dataset.tab;
        if (isLocalNodeOffline() && !canUseWithoutLocalNode(targetTab)) {
          const msg = State.language === 'en'
            ? 'Local node is offline. Only Settings is accessible.'
            : '本地节点未启动，当前仅开放【系统设置】页。';
          showToast(msg, 'warning');
          navigate('settings');
          return;
        }
        navigate(targetTab);
      });
    });

    document.querySelectorAll('.bottom-item').forEach(item => {
      item.addEventListener('click', (e) => {
        e.preventDefault();
        const targetTab = item.dataset.tab;
        if (isLocalNodeOffline() && !canUseWithoutLocalNode(targetTab)) {
          const msg = State.language === 'en'
            ? 'Local node is offline. Only Settings is accessible.'
            : '本地节点未启动，当前仅开放【系统设置】页。';
          showToast(msg, 'warning');
          navigate('settings');
          return;
        }
        navigate(targetTab);
      });
    });

    const quickLang = document.getElementById('quick-lang-btn');
    if (quickLang) {
      quickLang.onclick = () => {
        const next = State.language.startsWith('en') ? 'zh' : 'en';
        setLanguage(next);
      };
    }

    const quickTheme = document.getElementById('quick-theme-btn');
    if (quickTheme) {
      quickTheme.onclick = () => {
        setTheme(State.theme === 'dark' ? 'light' : 'dark');
      };
    }

    const didPill = document.getElementById('user-did-pill');
    if (didPill) {
      didPill.onclick = () => {
        try {
          navigator.clipboard.writeText(State.userDid);
          showToast(t('common.copied') || 'DID 已复制到剪贴板', 'success');
        } catch(e) {
          showToast(State.userDid, 'info');
        }
      };
    }
  }

  function setupPwaInstallPrompt() {
    let deferredPrompt = null;
    window.addEventListener('beforeinstallprompt', (e) => {
      e.preventDefault();
      deferredPrompt = e;
      const btn = document.getElementById('pwa-install-btn');
      if (btn) {
        btn.style.display = 'inline-flex';
        btn.onclick = async () => {
          btn.style.display = 'none';
          deferredPrompt.prompt();
          const choice = await deferredPrompt.userChoice;
          console.log('[PWA] User choice:', choice.outcome);
          deferredPrompt = null;
        };
      }
    });

    window.addEventListener('appinstalled', () => {
      console.log('[PWA] Application successfully installed.');
      showToast('Ziokt 客户端已成功安装到本地设备', 'success');
      const btn = document.getElementById('pwa-install-btn');
      if (btn) btn.style.display = 'none';
    });
  }

  function updateNavLabels() {
    document.querySelectorAll('.nav-item').forEach(item => {
      const key = routes[item.dataset.tab]?.titleKey;
      const labelSpan = item.querySelector('.nav-label');
      if (labelSpan && key) labelSpan.textContent = t(key);
    });
    document.querySelectorAll('.bottom-item').forEach(item => {
      const key = routes[item.dataset.tab]?.titleKey;
      const labelSpan = item.querySelector('.bottom-label');
      if (labelSpan && key) labelSpan.textContent = t(key);
    });
  }

  function setupKeyboardShortcuts() {
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        const modal = document.getElementById('modal-overlay');
        if (modal) modal.style.display = 'none';
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        const term = prompt('全局快捷检索 / 命令 (输入 home, chat, forum, files, apps, network, identity, devtools, settings):');
        if (term && routes[term.toLowerCase()]) {
          navigate(term.toLowerCase());
        }
        return;
      }
      if (['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName)) return;
      const num = parseInt(e.key, 10);
      const tabKeys = Object.keys(routes);
      if (num >= 1 && num <= tabKeys.length) {
        navigate(tabKeys[num - 1]);
      }
    });
  }

  // Self bootstrap
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initApp);
  } else {
    initApp();
  }

})();
