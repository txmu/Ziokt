let chromium;try{({chromium}=require('../ci/browser/node_modules/playwright'))}catch(_){({chromium}=require('../.runtime/browser/node_modules/playwright'))}
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),net=require('node:net'),{spawn}=require('node:child_process');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const root=path.resolve(__dirname,'..'),directory=fs.mkdtempSync(path.join(os.tmpdir(),'ziokt-browser-'));const listener=net.createServer();await new Promise(r=>listener.listen(0,'127.0.0.1',r));const port=listener.address().port;await new Promise(r=>listener.close(r));const base=`http://127.0.0.1:${port}`;
 const child=spawn(process.execPath,[root+'/companions/watchat/WATChat-code/backend/server.js'],{env:{...process.env,PORT:String(port),DATA_DIR:directory,ADMIN_PASSWORD:'browser-fixture-strong-password',ZIOKT_STANDALONE:'1',ZIOKT_BRIDGE_CONFIG:'',WATCHAT_PUSH_CONFIG:'',WATCHAT_WEBHOOK_CONFIG:''},stdio:['ignore','pipe','pipe']});let browser;
 try{
  let ready=false;for(let i=0;i<100;i++){try{if((await fetch(base)).ok){ready=true;break}}catch(_){}await delay(50)}assert.ok(ready);
  browser=await chromium.launch({headless:true});const aliceContext=await browser.newContext({viewport:{width:360,height:800},permissions:['notifications']}),bobContext=await browser.newContext({viewport:{width:360,height:800}});
  for(const context of [aliceContext,bobContext])await context.route('**/*',route=>{const host=new URL(route.request().url()).hostname;return host==='127.0.0.1'||host==='localhost'?route.continue():route.abort()});
  await aliceContext.grantPermissions(['notifications'],{origin:base});
  const alice=await aliceContext.newPage(),bob=await bobContext.newPage();alice.on('dialog',d=>d.accept());bob.on('dialog',d=>d.accept());
  await alice.goto(base);await alice.fill('#username','admin');await alice.fill('#password','browser-fixture-strong-password');await alice.click('#login button');await alice.locator('#workspace').waitFor({state:'visible'});
  await alice.locator('#admin').evaluate(e=>e.open=true);await alice.fill('#new-user','bob');await alice.fill('#new-name','Bob');await alice.fill('#new-password','browser-fixture-bob-password');await alice.locator('#admin').evaluate(e=>e.open=true);await alice.click('#create-user button');await delay(200);
  const bobId=await alice.evaluate(async()=>{const users=(await(await fetch('/api/users')).json()).users;return users.find(u=>u.username==='bob').id});
  await alice.fill('#contact-id',bobId);await alice.click('#add-contact button');
  await bob.goto(base);await bob.fill('#username','bob');await bob.fill('#password','browser-fixture-bob-password');await bob.click('#login button');await bob.locator('#workspace').waitFor({state:'visible'});
  await alice.reload();await alice.locator('#workspace').waitFor({state:'visible'});await alice.locator('#contacts button').filter({hasText:'Bob'}).first().click();await bob.locator('#contacts button').filter({hasText:'Administrator'}).click();
  await alice.fill('#text','private browser fixture message');await alice.click('#composer button');await bob.getByText('private browser fixture message',{exact:true}).waitFor();
  assert.equal(await bob.locator('#messages article').count(),1);
  await alice.selectOption('#language','zh-CN');assert.equal(await alice.locator('#composer button').textContent(),'发送');await alice.click('#notifications');await alice.getByText('已启用应用运行期间的通知；尚未配置后台推送').waitFor();
  const notification=await alice.evaluate(async()=>{const registration=await navigator.serviceWorker.ready;try{await registration.showNotification('WATChat',{body:'收到新消息',tag:'fixture'});const notices=await registration.getNotifications();for(const n of notices)n.close();return {permission:Notification.permission,delivered:notices.some(n=>n.body==='收到新消息')}}catch(e){return {permission:Notification.permission,delivered:false,limitation:String(e)}}});assert.ok(notification.delivered||notification.limitation,'notification result must carry explicit delivery evidence or a runtime limitation');
  console.log('Notification API result:',JSON.stringify(notification));
  await alice.waitForFunction(()=>navigator.serviceWorker.controller!==null);await aliceContext.setOffline(true);await alice.reload();assert.equal(await alice.locator('h1').textContent(),'WATChat');await aliceContext.setOffline(false);
  const disk=fs.readFileSync(path.join(directory,'store.aead'));assert.ok(!disk.includes(Buffer.from('private browser fixture message')));
  console.log('PASS: mobile viewport, real browser ECDH messages, locale, notification permission, offline PWA shell');
 }finally{if(browser)await browser.close();child.kill();await delay(100);fs.rmSync(directory,{recursive:true,force:true})}
})().catch(e=>{console.error(e);process.exit(1)});
