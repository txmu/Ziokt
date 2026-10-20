'use strict';
const assert=require('node:assert/strict'),cp=require('node:child_process'),readline=require('node:readline'),fs=require('node:fs');
const pw=require('../ci/browser/node_modules/playwright');
(async()=>{
 const child=cp.spawn(process.env.PYTHON||'python3',['ci/gui_fixture.py'],{stdio:['ignore','pipe','inherit']});
 let browser;
 try {
  const lines=readline.createInterface({input:child.stdout});
  const fixture=await new Promise((resolve,reject)=>{lines.once('line',line=>resolve(JSON.parse(line)));child.once('exit',code=>reject(Error('fixture exit '+code)));});
  browser=await pw.chromium.launch({headless:true});
  const page=await browser.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(origin=>{localStorage.setItem('ziokt_mode','remote');localStorage.setItem('ziokt_remote_nodes',JSON.stringify([{id:'ci',url:origin,name:'Loopback fixture'}]));localStorage.setItem('ziokt_active_node_id','ci');},fixture.origin);
  for(const [width,height] of [[192,240],[320,568],[390,664],[1440,900]]) {
   await page.setViewportSize({width,height});
   await page.goto(fixture.origin+'/gateway-assets/gui/index.html#ecosystem');
   await page.locator('#ecosystem-inspect').waitFor();
   const result=await page.evaluate(()=>{
    const scroller=document.querySelector('#content-container');scroller.scrollTop=scroller.scrollHeight;
    const last=scroller.lastElementChild.getBoundingClientRect(),box=scroller.getBoundingClientRect();
    return {width:innerWidth,documentWidth:document.documentElement.scrollWidth,client:scroller.clientHeight,top:scroller.scrollTop,total:scroller.scrollHeight,lastBottom:last.bottom,bottom:box.bottom};
   });
   assert(result.client>0,JSON.stringify(result));
   assert(result.top+result.client>=result.total-2,JSON.stringify(result));
   assert(result.lastBottom<=result.bottom+2,JSON.stringify(result));
   assert(result.documentWidth<=width,JSON.stringify(result));
  }
  const html=cp.execFileSync(process.env.PYTHON||'python3',['-c',"import sys;sys.path.insert(0,'tests');from test_gateway_observation import ObservationTests;print(ObservationTests().render('shadow6'))"],{encoding:'utf8'});
  await page.route('**/s6-ui-test',route=>route.fulfill({contentType:'text/html',body:html}));
  await page.route('**/api/gateway/public-address',route=>route.fulfill({json:{ok:true,address:'8.8.8.8'}}));
  await page.goto(fixture.origin+'/s6-ui-test');
  await page.waitForFunction(()=>document.querySelector('#s6p1-schema-tag').textContent.includes('(v1)'));
  const envelope=await page.evaluate(()=>parseS6P1Envelope(document.querySelector('#s6p1-textarea').value));
  assert.equal(envelope.routes.length,13);assert.equal(envelope.core.length,12);assert.deepEqual(envelope.components,{});
  const token=await page.locator('#s6p1-textarea').inputValue();
  // Optional local native source verification; CI without Shadow6 still runs UI checks.
  if(fs.existsSync('/home/admin/Shadow6/Public6/join_code.py')) {
   cp.execFileSync(process.env.PYTHON||'python3',['-c',"import sys;sys.path[:0]=['/home/admin/Shadow6/Public6','/home/admin/Shadow6'];from join_code import unpack_protocol;v=unpack_protocol(sys.stdin.read());assert len(v['routes'])==13"],{input:token});
   console.log('PASS native Shadow6 unpack_protocol accepts the UI-generated envelope (controlled IP observation)');
  }
  const hostile={...envelope,routes:[{core:'go',transport:'kcp',host:'<img src=x onerror=alert(1)>',port:14433}]};
  await page.evaluate(value=>{document.querySelector('#s6p1-textarea').value='S6P1.'+btoa(JSON.stringify(value)).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');handleParseS6P1();},hostile);
  assert.equal(await page.locator('#s6p1-routes-tbody img').count(),0);
  assert((await page.locator('#s6p1-routes-tbody').innerText()).includes('<img'));
  await page.evaluate(value=>{value.credentials={fraction:1.5};document.querySelector('#s6p1-textarea').value='S6P1.'+btoa(JSON.stringify(value)).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');handleParseS6P1();},envelope);
  assert((await page.locator('#s6p1-schema-tag').innerText()).startsWith('ERROR:'));
  assert.deepEqual(errors,[]);
  console.log('PASS real Chromium: 192/320/390/1440px viewport, bottom reachable, no document overflow; viewport emulation, not physical-device certification');
 } finally {if(browser)await browser.close();child.kill('SIGTERM');}
})().catch(error=>{console.error(error);process.exitCode=1;});
