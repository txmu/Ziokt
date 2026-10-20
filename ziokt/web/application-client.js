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
