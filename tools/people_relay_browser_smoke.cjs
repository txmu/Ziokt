'use strict';
const assert=require('node:assert/strict'),{spawn}=require('node:child_process'),readline=require('node:readline');
let playwright;try{playwright=require('../ci/browser/node_modules/playwright')}catch(_){playwright=require('../.runtime/browser/node_modules/playwright')}
(async()=>{
 const fixture=spawn(process.env.PYTHON||'python3',['ci/people_relay_fixture.py',...(process.env.DIRECT_RELAY==='1'?['--direct']:[])],{stdio:['pipe','pipe','inherit']});
 const lines=readline.createInterface({input:fixture.stdout}),messages=[];let ready;
 const first=new Promise(resolve=>ready=resolve);lines.on('line',line=>{messages.push(JSON.parse(line));if(ready){ready(messages[0]);ready=null}});
 let browser;try{
  const setup=await Promise.race([first,new Promise((_,reject)=>setTimeout(()=>reject(Error('Fixture startup deadline')),15000))]);
  const engine=process.env.BROWSER||'chromium';if(!['chromium','firefox','webkit'].includes(engine))throw Error('Unsupported browser');browser=await playwright[engine].launch({headless:true});const context=await browser.newContext({locale:'zh-CN',viewport:{width:390,height:844}});
  await context.addInitScript(()=>{Object.defineProperty(window,'crypto',{configurable:true,get:()=>undefined});Object.defineProperty(navigator,'serviceWorker',{configurable:true,get:()=>undefined});window.Worker=undefined;window.fetch=undefined});
  const page=await context.newPage(),forwarded=[],errors=[];page.on('pageerror',error=>errors.push(error.message));
  page.on('request',request=>{if(request.url().endsWith('/write'))forwarded.push(JSON.parse(request.postData()).arguments.frame)});
  const configured=page.waitForResponse(r=>r.url().endsWith('/api/people/config'));await page.goto(setup.origin);await configured;
  await page.selectOption('#latitude','60');assert.equal(await page.locator('#latitude-ratio').textContent(),'50.0%');
  for(const width of [192,320,390,1280]){
   await page.setViewportSize({width,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'horizontal overflow at '+width);
   await page.locator('footer').scrollIntoViewIfNeeded();assert.ok(await page.locator('footer').isVisible());
  }
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:'/tmp/people-help-geography-390.png',fullPage:true});
  await page.locator('.connection-settings summary').click();if(setup.invitation)await page.fill('#help-invitation',JSON.stringify(setup.invitation));
  await page.getByRole('button',{name:'一键人民助力',exact:true}).click();
  if(setup.direct){
   await page.waitForFunction(()=>document.getElementById('status').textContent.includes('等待真实任务'),{},{timeout:30000});
   assert.ok(forwarded.length>2);
   await context.setOffline(true);await page.getByText('网络已断开，等待网络恢复',{exact:true}).waitFor();
   const paused=forwarded.length;await page.waitForTimeout(500);assert.equal(forwarded.length,paused);
   await context.setOffline(false);await page.waitForFunction(()=>document.getElementById('status').textContent.includes('等待真实任务'));
   await page.locator('#start').click();await context.setOffline(true);await context.setOffline(false);assert.equal(await page.locator('#start').getAttribute('aria-pressed'),'false');
  }else await page.getByText('本次网络协作已完成；尚未结算链上贡献。',{exact:true}).waitFor({timeout:30000});
  assert.ok(forwarded.length>2);for(const frame of forwarded){const raw=Buffer.from(frame.data,'base64');assert.ok(!raw.includes('GEOGRAPHY-PRIVATE-TLS-LESSON'));assert.ok(!raw.includes('GEOGRAPHY-PRIVATE-TLS-ANSWER'))}
  assert.deepEqual(errors,[]);assert.equal(await page.locator('#start').getAttribute('aria-pressed'),'false');
  await browser.close();browser=null;fixture.stdin.end('\n');
  const exit=await new Promise(resolve=>fixture.on('exit',resolve));assert.equal(exit,0);assert.equal(messages.at(-1).inner_mtls,true);
  console.log('PASS: actual endpoint mTLS via two authenticated HTTP relay halves; WebCrypto/SW/Worker/fetch disabled; geography interaction; 192/320/390/1280px scrolling; no plaintext application records in browser frames. Native Shadow6 and Android hardware are separate CI requirements.');
 }finally{if(browser)await browser.close();fixture.stdin.end('\n');if(fixture.exitCode===null)fixture.kill()}
})().catch(error=>{console.error(error);process.exitCode=1});
