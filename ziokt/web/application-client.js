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
    const bar=node('div'),select=node('select'),body=node('pre'),pageStatus=node('p'),navigation=node('select');
    select.setAttribute('aria-label',label('EPUB 章节','EPUB chapter'));navigation.setAttribute('aria-label',label('EPUB 目录','EPUB table of contents'));
    body.tabIndex=0;body.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere;font:inherit';pageStatus.setAttribute('role','status');
    const action=(text,fn)=>{const button=node('button',text);button.type='button';button.style.minHeight='44px';button.onclick=async()=>{button.disabled=true;try{await fn();}catch(error){status(error.message);}finally{button.disabled=false;}};return button;};
    const previous=action(label('上一页','Previous page'),async()=>{if(offset>0)await load(chapter,Math.max(0,offset-16384));else if(chapter>0)await load(chapter-1,0);});
    const following=action(label('下一页','Next page'),async()=>{if(next!==null)await load(chapter,next);else if(chapter+1<chapterCount)await load(chapter+1,0);});
    const more=action(label('更多章节与目录','More chapters and navigation'),async()=>{manifestOffset+=64;await inventory();});
    bar.append(select,navigation,previous,following,more);container.replaceChildren(bar,pageStatus,body);
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
