'use strict';
const assert=require('node:assert/strict'),cp=require('node:child_process'),readline=require('node:readline'),crypto=require('node:crypto');
let pw;try{pw=require('../ci/browser/node_modules/playwright')}catch(_){pw=require('../.runtime/browser/node_modules/playwright')}
(async()=>{let browser;const child=cp.spawn(process.env.PYTHON||'python3',['ci/gui_fixture.py'],{stdio:['ignore','pipe','inherit']});
try{
 const lines=readline.createInterface({input:child.stdout});const fixture=await new Promise((resolve,reject)=>{lines.once('line',line=>resolve(JSON.parse(line)));child.once('exit',code=>reject(new Error('fixture exit '+code)))});
 const engine=process.env.BROWSER||'chromium';browser=await pw[engine].launch({headless:true});
 const page=await browser.newPage({viewport:{width:390,height:844}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(origin=>{localStorage.setItem('ziokt_mode','remote');localStorage.setItem('ziokt_remote_nodes',JSON.stringify([{id:'ci',url:origin,name:'CI real gateway'}]));localStorage.setItem('ziokt_active_node_id','ci')},fixture.origin);
 await page.goto(fixture.origin+'/gateway-assets/gui/index.html#files');
 await page.locator('#operation-token').fill(fixture.token);await page.locator('#load-real-tools').click();await page.waitForFunction(()=>document.querySelector('#real-tool').options.length>0);
 const data=crypto.randomBytes(25000);await page.locator('#real-file').setInputFiles({name:'actual.bin',mimeType:'application/octet-stream',buffer:data});await page.locator('#real-confirm').check();await page.locator('#upload-real-file').click();
 await page.waitForFunction(()=>document.querySelector('#real-result').textContent.includes('manifest_digest'));
 const report=JSON.parse(await page.locator('#real-result').innerText());assert.equal(report.receipt.length,data.length);assert.equal(report.receipt.digest,'sha256:'+crypto.createHash('sha256').update(data).digest('hex'));assert.equal(report.installed,false);
 const stored=await page.evaluate(()=>JSON.stringify(localStorage));assert(!stored.includes(fixture.token),'owner credential persisted to browser storage');
 const chunks=[];for(let i=0;i<2;i++){const r=await fetch(fixture.origin+'/api/gateway/tools/call',{method:'POST',headers:{Authorization:'Bearer '+fixture.token,'Content-Type':'application/json'},body:JSON.stringify({name:'safefs_object_chunk_get',arguments:{params:{object:report.receipt.manifest_digest,position:i}}})});assert.equal(r.status,200);const v=await r.json();assert.equal(v.isError,false);chunks.push(Buffer.from(v.structuredContent.data_base64,'base64'));}assert.deepEqual(Buffer.concat(chunks),data);
 assert.deepEqual(errors,[]);console.log('PASS '+engine+': mobile GUI click -> real authenticated chunk upload -> independent content verification; credentials memory-only');
}finally{if(browser)await browser.close();child.kill('SIGTERM');}})().catch(e=>{console.error(e);process.exitCode=1});
