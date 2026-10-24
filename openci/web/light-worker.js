/* One translation unit, fixed memory, no host files and no task-code execution. */
'use strict';
onmessage=async event=>{
  try{
    const {target,source,prefix,files}=event.data;
    if(!['x86_64','aarch64'].includes(target)||!['','/openci'].includes(prefix)||typeof source!=='string'||source.includes('\0')||new TextEncoder().encode(source).length>131072)throw Error('INPUT_LIMIT');
    const response=await fetch(prefix+'/compiler/'+target+'.wasm',{cache:'no-store',credentials:'omit',redirect:'error'});
    if(!response.ok||Number(response.headers.get('Content-Length'))>8*1024*1024)throw Error('COMPILER_UNAVAILABLE');
    const binary=await response.arrayBuffer();
    const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',binary)),b=>b.toString(16).padStart(2,'0')).join('');
    if(hash!==files[target+'.wasm'])throw Error('COMPILER_INTEGRITY');
    importScripts(prefix+'/compiler/'+target+'.js');
    const logs=[];const compiler=await createOpenCITcc({wasmBinary:new Uint8Array(binary),printErr:value=>{if(logs.join('\n').length<4096)logs.push(String(value).slice(0,512))},print:()=>{}});
    const code=compiler.ccall('openci_compile','number',['string'],[source]);
    if(code!==0)throw Error('C_COMPILE_REJECTED: '+logs.join('\n'));
    const object=compiler.FS.readFile('/output.o');
    if(object.length<64||object.length>1048576||object[0]!==127||object[1]!==69||object[2]!==76||object[3]!==70||(object[18]|object[19]<<8)!==(target==='x86_64'?62:183))throw Error('OBJECT_ARCH_MISMATCH');
    postMessage({object:object.buffer},[object.buffer]);
  }catch(error){postMessage({error:String(error.message).slice(0,4096)})}
};
