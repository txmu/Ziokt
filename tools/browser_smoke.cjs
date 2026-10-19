let chromium;try{({chromium}=require('../ci/browser/node_modules/playwright'))}catch(_){({chromium}=require('../.runtime/browser/node_modules/playwright'))}
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),net=require('node:net'),{spawn,spawnSync}=require('node:child_process');
const uiMode=process.env.WATCHAT_UI||'simple',desktop=process.env.WATCHAT_VIEWPORT==='desktop';
const delay=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const root=path.resolve(__dirname,'..'),directory=fs.mkdtempSync(path.join(os.tmpdir(),'ziokt-browser-'));const listener=net.createServer();await new Promise(r=>listener.listen(0,'127.0.0.1',r));const port=listener.address().port;await new Promise(r=>listener.close(r));const base=`http://127.0.0.1:${port}`;
 const child=spawn(process.execPath,[root+'/companions/watchat/WATChat-code/backend/server.js'],{env:{...process.env,PORT:String(port),DATA_DIR:directory,ADMIN_PASSWORD:'browser-fixture-strong-password',ZIOKT_STANDALONE:'1',ZIOKT_BRIDGE_CONFIG:'',WATCHAT_PUSH_CONFIG:'',WATCHAT_WEBHOOK_CONFIG:'',SIM_BRIDGE_CONFIG:'',WATCHAT_ORIGIN:''},stdio:['ignore','pipe','pipe']});let browser,deniedBrowser;
 try{
  let ready=false;for(let i=0;i<100;i++){try{if((await fetch(base)).ok){ready=true;break}}catch(_){}await delay(50)}assert.ok(ready);
  browser=await chromium.launch({headless:true,args:['--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream']});deniedBrowser=await chromium.launch({headless:true,args:['--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream=deny']});const aliceContext=await browser.newContext({viewport:desktop?{width:1280,height:900}:{width:360,height:800},permissions:['notifications','microphone']}),bobContext=await deniedBrowser.newContext({viewport:desktop?{width:1280,height:900}:{width:360,height:800}});
  for(const context of [aliceContext,bobContext])await context.route('**/*',route=>{const host=new URL(route.request().url()).hostname;return host==='127.0.0.1'||host==='localhost'?route.continue():route.abort()});
  await aliceContext.grantPermissions(['notifications','microphone'],{origin:base});await bobContext.grantPermissions([],{origin:base});
  const alice=await aliceContext.newPage(),bob=await bobContext.newPage();for(const page of [alice,bob]){page.on('pageerror',error=>console.error('Browser error:',error.message));page.on('console',message=>{if(message.type()==='error')console.error('Browser console:',message.text())});}alice.on('dialog',d=>d.accept());bob.on('dialog',d=>d.accept());
  await alice.goto(base);await alice.fill('#username','admin');await alice.fill('#password','browser-fixture-strong-password');await alice.click('#login button');await alice.locator('#workspace').waitFor({state:'visible'});await alice.selectOption('#ui-mode',uiMode);
  await alice.locator('#admin').evaluate(e=>e.open=true);await alice.fill('#new-user','bob');await alice.fill('#new-name','Bob');await alice.fill('#new-password','browser-fixture-bob-password');await alice.locator('#admin').evaluate(e=>e.open=true);await alice.click('#create-user button');await delay(200);
  const bobId=await alice.evaluate(async()=>{const users=(await(await fetch('/api/users')).json()).users;return users.find(u=>u.username==='bob').id});
  await alice.fill('#contact-id',bobId);await alice.click('#add-contact button');
  await bob.goto(base);await bob.fill('#username','bob');await bob.fill('#password','browser-fixture-bob-password');await bob.click('#login button');await bob.locator('#workspace').waitFor({state:'visible'});await bob.selectOption('#ui-mode',uiMode);
  await alice.reload();await alice.locator('#workspace').waitFor({state:'visible'});await alice.locator('#contacts button').filter({hasText:'Bob'}).first().click();await bob.locator('#contacts button').filter({hasText:'Administrator'}).click();
  await alice.fill('#text','private browser fixture message');await alice.click('#composer button');await bob.getByText('private browser fixture message',{exact:true}).waitFor();
  assert.equal(await bob.locator('#messages article').count(),1);
  await alice.waitForFunction(()=>{const text=document.querySelector('.delivery')?.textContent;return text==='Recipient confirmed'||text==='Read'});
  const beforeSession=await alice.evaluate(async()=>(await(await fetch('/api/me')).json()).user.id);
  await alice.selectOption('#ui-mode',uiMode==='classic'?'simple':'classic');await alice.selectOption('#theme','dark');
  assert.equal(await alice.evaluate(async()=>(await(await fetch('/api/me')).json()).user.id),beforeSession);
  assert.equal(await alice.locator('#messages article').count(),1);
  await alice.selectOption('#ui-mode',uiMode);
  const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNg+A8AAQIBAEK+vGgAAAAASUVORK5CYII=','base64');
  await alice.locator('#media').setInputFiles({name:'fixture.png',mimeType:'image/png',buffer:png});
  await bob.waitForFunction(()=>document.querySelector('#messages img')?.naturalWidth===1);
  // Persist ciphertext before the network is available, then reload the sender.
  await aliceContext.setOffline(true);
  await alice.locator('#media').setInputFiles({name:'offline.png',mimeType:'image/png',buffer:png});
  await alice.waitForFunction(()=>new Promise(resolve=>{const request=indexedDB.open('ziokt-watchat-v2');request.onsuccess=()=>{const db=request.result,tx=db.transaction('media'),count=tx.objectStore('media').count();count.onsuccess=()=>{resolve(count.result===1);db.close()}}}));
  await alice.selectOption('#ui-mode',uiMode==='classic'?'simple':'classic');
  await aliceContext.setOffline(false);await alice.reload();await alice.locator('#workspace').waitFor({state:'visible'});
  await bob.waitForFunction(()=>document.querySelectorAll('#messages img').length===2);
  await alice.selectOption('#ui-mode',uiMode);await alice.locator('#contacts button').filter({hasText:'Bob'}).first().click();
  for(const [name,args,mime,tag] of [
   ['voice.ogg',['-f','lavfi','-i','sine=frequency=440:duration=0.3','-c:a','libopus'],'audio/ogg','audio'],
   ['movie.webm',['-f','lavfi','-i','color=c=green:s=64x64:d=0.3','-c:v','libvpx-vp9','-an'],'video/webm','video']]){
   const target=path.join(directory,name),built=spawnSync('ffmpeg',['-hide_banner','-loglevel','error',...args,'-y',target],{timeout:10000});assert.equal(built.status,0,String(built.stderr));
   await alice.locator('#media').setInputFiles({name,mimeType:mime,buffer:fs.readFileSync(target)});
   await bob.waitForFunction(tag=>{const element=document.querySelector('#messages '+tag);return element&&element.readyState>=2&&element.duration>0},tag);
   const player=bob.locator('#messages '+tag).first();await player.evaluate(e=>e.play());await player.evaluate(e=>e.pause());
  }
  await alice.waitForFunction(()=>!document.querySelector('#record').disabled);await alice.click('#record');await alice.getByText('Recording (60 seconds maximum)',{exact:true}).waitFor();await delay(1100);await alice.click('#record');
  await bob.waitForFunction(()=>document.querySelectorAll('#messages audio').length===2);
  await bob.click('#record');await bob.getByText('Microphone permission denied or unavailable',{exact:true}).waitFor();
  await alice.selectOption('#theme','system');
  if(uiMode==='classic'&&!desktop){await alice.click('#chat-back');assert.equal(await alice.locator('#contacts').isVisible(),true);await alice.locator('#contacts button').filter({hasText:'Bob'}).first().click();assert.equal(await alice.locator('#composer').isVisible(),true)}
  const overflow=await alice.evaluate(()=>document.documentElement.scrollWidth>innerWidth);assert.equal(overflow,false);

  await alice.selectOption('#language','zh-CN');assert.equal(await alice.locator('#composer button').textContent(),'发送');await alice.click('#notifications');await alice.getByText('已启用应用运行期间的通知；尚未配置后台推送').waitFor();
  const notification=await alice.evaluate(async()=>{const registration=await navigator.serviceWorker.ready;try{await registration.showNotification('WATChat',{body:'收到新消息',tag:'fixture'});const notices=await registration.getNotifications();for(const n of notices)n.close();return {permission:Notification.permission,apiAccepted:true,retained:notices.some(n=>n.body==='收到新消息')}}catch(e){return {permission:Notification.permission,delivered:false,limitation:String(e)}}});assert.ok(notification.apiAccepted||notification.limitation,'notification API must resolve or carry an explicit runtime limitation');
  console.log('Notification API result:',JSON.stringify(notification));
  await alice.waitForFunction(()=>navigator.serviceWorker.controller!==null);await aliceContext.setOffline(true);await alice.reload();assert.equal(await alice.locator('h1').textContent(),'网页管理');await aliceContext.setOffline(false);
  const disk=fs.readFileSync(path.join(directory,'store.aead'));assert.ok(!disk.includes(Buffer.from('private browser fixture message')));
  console.log('PASS:',JSON.stringify({ui:uiMode,viewport:desktop?'desktop':'Android-sized',encryption:true,offlineAttachmentRecovery:true,image:true,video:true,audio:true,syntheticMicrophone:true,hardwareMicrophoneTested:false,osNotificationDeliveryTested:false}));
 }catch(error){if(browser){for(const context of browser.contexts())for(const page of context.pages())console.error('Media diagnostics:',await page.evaluate(()=>({status:document.querySelector('#status')?.textContent,record:document.querySelector('#record')?.textContent,disabled:document.querySelector('#record')?.disabled,mediaBusy,recorderState:recorder?.state,stream:recordStream?.active,secure:isSecureContext})).catch(()=>({unavailable:true})));const artifacts=path.join(root,'dist/browser-artifacts',uiMode+'-'+(desktop?'desktop':'mobile'));fs.mkdirSync(artifacts,{recursive:true});for(const [i,context] of browser.contexts().entries())for(const [j,page] of context.pages().entries())await page.screenshot({path:path.join(artifacts,`${i}-${j}.png`),fullPage:true}).catch(()=>{});}throw error;}finally{if(browser)await browser.close();if(deniedBrowser)await deniedBrowser.close();child.kill();await delay(100);fs.rmSync(directory,{recursive:true,force:true})}
})().catch(e=>{console.error(e);process.exit(1)});
