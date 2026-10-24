/* Read-only browser checks for URL locale, history restoration and fictional examples. */
'use strict';
const assert=require('node:assert/strict'),cp=require('node:child_process'),readline=require('node:readline');
const {chromium}=require('../ci/browser/node_modules/playwright');
(async()=>{
 let browser,child;
 try {
  let origin=process.env.ZIOKT_LOCALE_ORIGIN;
  if(!origin){
   child=cp.spawn(process.env.PYTHON||'python3',['ci/gateway_browser_fixture.py'],{stdio:['ignore','pipe','inherit']});
   const lines=readline.createInterface({input:child.stdout});
   origin=await new Promise((resolve,reject)=>{lines.once('line',line=>resolve(JSON.parse(line).origin));child.once('exit',code=>reject(Error('Fixture exited '+code)));});
  }
  browser=await chromium.launch({headless:true});
  const context=await browser.newContext({locale:'zh-CN',viewport:{width:390,height:844}});
  await context.addCookies([{name:'ziokt_lang',value:'zh-CN',url:origin}]);
  await context.addInitScript(()=>localStorage.setItem('ziokt_lang','zh-CN'));
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  const select=page.locator('#ziokt-top-bar select');
  async function check(locale){
   await select.waitFor();assert.equal(await select.inputValue(),locale);
   assert.equal(await page.locator('html').getAttribute('lang'),locale);
   assert.equal(await select.locator('option:checked').getAttribute('value'),locale);
   assert.equal(await select.evaluate(el=>el.selectedOptions[0].defaultSelected),true);
   const links=page.locator('nav[aria-label="Unified client"]');
   assert.equal(await links.locator('a').nth(0).innerText(),locale==='en-US'?'Ziokt Web App':'Ziokt Web 应用');
   assert.equal(await links.locator('a').nth(1).innerText(),locale==='en-US'?'Platform Downloads':'各平台软件下载');
  }
  await page.goto(origin+'/app/overview?lang=en-US');await check('en-US');
  await select.selectOption('zh-CN');await page.waitForURL('**lang=zh-CN');await check('zh-CN');
  await page.goBack();await check('en-US');
  // Model a browser restoring a stale form value as a cached page is shown.
  await select.evaluate(el=>{el.value='zh-CN';window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}));});
  await check('en-US');
  await select.evaluate(el=>{window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}));el.value='zh-CN';});
  await page.waitForFunction(()=>document.querySelector('#ziokt-top-bar select').value==='en-US');
  await check('en-US');
  await page.reload();await check('en-US');
  for(const mode of ['panoramic','simple']){
   await page.goto(origin+'/app/overview?lang=en-US&ui='+mode);await check('en-US');
  }
  for(const locale of ['en-US','zh-CN']){
   await page.goto(origin+'/app/shadow6?lang='+locale+'&ui=panoramic');await check(locale);
   const notice=page.locator('#s6p1-example-notice');await notice.waitFor();assert.equal(await notice.count(),1);
   assert.match(await notice.innerText(),locale==='en-US'?/IP addresses and ports.*fictional/:/IP 地址与端口均为虚构/);
   await page.waitForFunction(()=>document.querySelector('#s6p1-raw-json').textContent.includes('example:fictional'));
   const sample=JSON.parse(await page.locator('#s6p1-raw-json').textContent());assert.equal(sample.routes.length,13);
   sample.routes.forEach((route,index)=>{assert.equal(route.host,'192.0.2.1');assert.equal(route.port,24000+index)});
   // User-supplied values remain intact and are escaped in the rendered table.
   const custom={...sample,purpose:'custom',routes:[{core:'go',transport:'kcp',host:'<img src=x onerror=alert(1)>',port:32123}]};
   const encoded='S6P1.'+Buffer.from(JSON.stringify(custom)).toString('base64url');
   await page.locator('#s6p1-textarea').fill(encoded);await page.evaluate(()=>handleParseS6P1());
   assert.deepEqual(JSON.parse(await page.locator('#s6p1-raw-json').textContent()),custom);
   assert.equal(await page.locator('#s6p1-routes-tbody img').count(),0);
   await page.evaluate(()=>handleLoadSampleS6P1());
   assert.equal(JSON.parse(await page.locator('#s6p1-raw-json').textContent()).purpose,'example:fictional');
  }
  assert.deepEqual(errors,[]);
  console.log('PASS '+origin+': bilingual links, URL locale over saved Chinese preference, initial/default selection, history/pageshow/reload, both views, fictional sample endpoints, unchanged escaped custom imports');
 }finally{if(browser)await browser.close();if(child)child.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exitCode=1});
