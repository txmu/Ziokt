'use strict';
const engines=require('../ci/browser/node_modules/playwright');
const http=require('node:http'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
(async()=>{
 const root=path.resolve('gui/src');let server,browser;
 const data=Buffer.from('Ziokt original offline integrity fixture'),digest=crypto.createHash('sha256').update(data).digest('hex');
 try{
  server=http.createServer((request,response)=>{
   const url=new URL(request.url,'http://localhost');
   if(url.pathname==='/api/private'){response.setHeader('Content-Type','application/json');response.setHeader('Cache-Control','no-store');response.end(JSON.stringify({private:'must-never-enter-shell-cache'}));return;}
   const file=path.resolve(root,'.'+url.pathname.replace(/^\/gateway-assets\/gui/,''));
   if(!file.startsWith(root+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){response.writeHead(404);response.end();return;}
   response.setHeader('Content-Type',({'.html':'text/html','.js':'application/javascript','.css':'text/css','.json':'application/json','.png':'image/png','.svg':'image/svg+xml'})[path.extname(file)]||'application/octet-stream');
   response.setHeader('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'");response.end(fs.readFileSync(file));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const port=server.address().port,origin='http://127.0.0.1:'+port;
  const engine=process.env.BROWSER||'chromium';browser=await engines[engine].launch({headless:true});const evidence=[];
  for(const prefix of ['','/gateway-assets/gui']){
   const context=await browser.newContext({viewport:{width:390,height:844}});
   await context.addInitScript(()=>{localStorage.setItem('ziokt_mode','remote');localStorage.setItem('ziokt_lang','en');});
   const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));
   const url=origin+prefix+'/index.html#ecosystem';await page.goto(url);
   await page.locator('#offline-integrity-check').waitFor();
   await page.evaluate(async()=>{await navigator.serviceWorker.ready;if(!navigator.serviceWorker.controller)await new Promise(resolve=>navigator.serviceWorker.addEventListener('controllerchange',resolve,{once:true}));await fetch('/api/private',{headers:{Authorization:'Bearer offline-test-only'}});await(await caches.open('another-application-cache')).put('/unrelated',new Response('keep'));});
   // Playwright WebKit #42775 breaks SW navigation under setOffline even for
   // literal cached responses. Stop the real listener instead; do not skip it.
   if(engine==='webkit')await new Promise(resolve=>server.close(resolve));else await context.setOffline(true);
   await page.reload();await page.locator('#offline-integrity-check').waitFor();
   await page.locator('#offline-integrity-file').setInputFiles({name:'offline.txt',mimeType:'text/plain',buffer:data});await page.locator('#offline-integrity-check').click();await page.locator('#offline-integrity-result').filter({hasText:digest}).waitFor();
   const cache=await page.evaluate(async()=>{const names=await caches.keys(),name=names.find(key=>key.startsWith('ziokt-gui-shell-'));return {names,urls:(await(await caches.open(name)).keys()).map(request=>request.url)};});
   assert(cache.names.includes('another-application-cache'));assert(cache.urls.every(url=>!url.includes('/api/')&&!url.includes('private')));
   const failed=await page.evaluate(async()=>{try{await fetch('/api/private');return false;}catch{return true;}});assert(failed,'API unexpectedly fell back to cached private data');
   await page.locator('#ecosystem-filter').fill('SafeFS');assert.equal(await page.locator('.ecosystem-grid article:visible').count(),1);
   await page.locator('#private-offline-password').fill('test-passphrase-at-least-12-chars');
   await page.locator('#private-offline-unlock').click();
   await page.locator('#private-offline-status').filter({hasText:/已解锁|Unlocked/}).waitFor();
   const saved=await page.evaluate(async()=>{
    await window.privateOfflineVault.save({kind:'book',title:'Offline Test Book',source:'https://ziokt.com/test',source_id:'test-book-1'},new TextEncoder().encode('Private offline text content that must be encrypted'));
    return await window.privateOfflineVault.list();
   });
   assert.equal(saved.length,1);assert.equal(saved[0].title,'Offline Test Book');
   const rawDb=await page.evaluate(async()=>{
    return new Promise(resolve=>{
     const req=indexedDB.open('ziokt-private-offline-v1');
     req.onsuccess=()=>{
      const db=req.result,tx=db.transaction(['entries','blobs'],'readonly'),out=[];
      tx.objectStore('entries').openCursor().onsuccess=e=>{const c=e.target.result;if(c){out.push(c.value);c.continue();}else resolve(out);};
     };
    });
   });
   assert(!JSON.stringify(rawDb).includes('Private offline text content'),'Plaintext leaked into IndexedDB');
   await page.locator('#private-offline-refresh').click();
   await page.locator('#private-offline-list article').filter({hasText:'Offline Test Book'}).waitFor();
   await page.locator('#private-offline-lock').click();
   await page.locator('#private-offline-status').filter({hasText:/已锁定|Locked/}).waitFor();
   await page.locator('#private-offline-clear').click();
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'mobile horizontal overflow');assert.deepEqual(errors,[]);
   evidence.push({prefix:prefix||'/',offline_reload:true,offline_mechanism:engine==='webkit'?'actual origin listener stopped':'browser network offline',local_digest:true,no_private_api_cache:true,unrelated_cache_preserved:true,strict_csp:true});await context.close();
   if(engine==='webkit')await new Promise(resolve=>server.listen(port,'127.0.0.1',resolve));
  }
  // WebKit's offline emulation rejects file:// navigation before the document
  // loads. Block HTTP(S) explicitly for that engine and record the mechanism.
  const context=await browser.newContext();
  const standaloneMechanism=engine==='webkit'?'all HTTP(S) requests aborted':'browser network offline';
  if(engine==='webkit')await context.route(/^https?:/,route=>route.abort('internetdisconnected'));
  else await context.setOffline(true);
  await context.addInitScript(()=>{localStorage.setItem('ziokt_mode','remote');localStorage.setItem('ziokt_lang','en');});
  const page=await context.newPage();await page.goto(pathToFileURL(path.join(root,'index.html')).href+'#ecosystem');await page.locator('#offline-integrity-file').setInputFiles({name:'local.txt',mimeType:'text/plain',buffer:data});await page.locator('#offline-integrity-check').click();await page.locator('#offline-integrity-result').filter({hasText:digest}).waitFor();await context.close();
  console.log(JSON.stringify({schema:'ziokt.gui-offline-evidence.v1',browser:engine,pwa:evidence,standalone_file_without_network:true,standalone_mechanism:standaloneMechanism,native_airgap_process_policy:'separate test_airgap.py; browser offline is not an OS sandbox',status:'passed'}));
 }finally{if(browser)await browser.close();if(server)await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);process.exitCode=1;});
