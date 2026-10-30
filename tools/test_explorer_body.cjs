'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../ziokt/explorer/app.js'),'utf8');
const body=source.slice(source.indexOf('async function bodyJSON('),source.indexOf('\nasync function api('));
(async()=>{
 for(const decoder of [TextDecoder,undefined]){
  const read=vm.runInNewContext(body+';bodyJSON',{TextDecoder:decoder,Response,Uint8Array,Number,JSON,Error});
  const expected={text:'中文🧬'},bytes=new TextEncoder().encode(JSON.stringify(expected));
  const stream=new ReadableStream({start(c){for(const b of bytes)c.enqueue(Uint8Array.of(b));c.close()}});
  assert.equal((await read(new Response(stream))).text,expected.text);
  let cancelled=false;
  const oversized=new ReadableStream({start(c){c.enqueue(new Uint8Array(1048577))},cancel(){cancelled=true}});
  await assert.rejects(read(new Response(oversized)),/RESPONSE_TOO_LARGE/);assert.equal(cancelled,true);assert.equal(oversized.locked,false);
  await assert.rejects(read(new Response('{broken')),SyntaxError);
  for(const length of [null,'-1','1048577'])await assert.rejects(read({body:null,headers:{get:()=>length},text:async()=>'{"ok":true}'}),/RESPONSE_TOO_LARGE/);
 }
 console.log('PASS explorer decoding: native/fallback UTF-8 chunk boundaries, size limit, cancellation, malformed JSON, missing/invalid lengths');
})().catch(e=>{console.error(e);process.exitCode=1});
