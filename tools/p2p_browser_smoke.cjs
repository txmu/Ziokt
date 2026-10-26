'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),http=require('node:http'),path=require('node:path');
const {chromium}=require('../ci/browser/node_modules/playwright');
(async()=>{
  let browser,reads=0;
  const nodes=Array.from({length:70},(_,index)=>({id:'node-'+index,label:'Peer '+index,component:'corium',state:'observed'}));
  const server=http.createServer((req,res)=>{
    if(req.url.startsWith('/api/p2p/')){
      res.setHeader('Content-Type','application/json');
      if(req.url.startsWith('/api/p2p/config'))return res.end(JSON.stringify({schema:'ziokt.p2p-browser.v1',components:['corium'],authentication_required:false}));
      reads++;return res.end(JSON.stringify({schema:'ziokt.p2p-topology.v1',nodes,edges:[{source:'node-0',target:'node-1'}],sources:[{id:'observer-a',component:'corium',state:'available',adapter:'signed',evidence:{clock_offset_ms:100,clock_uncertainty_ms:10}}],cbb:[],observed_at:Math.floor(Date.now()/1000),privacy:{addresses_visible:false,identities_visible:false},coverage:{configured_observers:3,verified_observers:2}}));
    }
    const name=req.url==='/p2p/'?'index.html':req.url.slice('/p2p/'.length);
    if(!['index.html','app.js','style.css'].includes(name)){res.writeHead(404);return res.end()}
    res.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(path.join(__dirname,'../ziokt/p2p',name)));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  try{
    browser=await chromium.launch({headless:true});
    for(const width of [390,1280]){
      const page=await browser.newPage({viewport:{width,height:900},locale:'zh-CN'});const errors=[];page.on('pageerror',error=>errors.push(error.message));
      await page.clock.install();await page.goto('http://127.0.0.1:'+server.address().port+'/p2p/');await page.waitForFunction(()=>document.querySelectorAll('#nodes button').length===70);
      assert.equal(await page.locator('a[href="https://fendou.ziokt.com/"]').count(),1);
      assert.equal(await page.locator('#graph .graph-item').count(),70);
      assert.match(await page.locator('#coverage').textContent(),/2\/3/);
      await page.locator('#nodes button').first().click();assert.match(await page.locator('#detail').textContent(),/node-0/);
      const before=reads;await page.clock.fastForward(15000);await page.waitForFunction(()=>!document.querySelector('#load').disabled);assert.ok(reads>before);
      await page.locator('#auto-refresh').uncheck();const paused=reads;await page.clock.fastForward(15000);assert.equal(reads,paused);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
      assert.deepEqual(errors,[]);await page.close();
    }
    console.log('P2P browser: mobile/desktop, 70 visible nodes, observer coverage, contribution link, auto-refresh and pause passed');
  }finally{if(browser)await browser.close();await new Promise(resolve=>server.close(resolve))}
})().catch(error=>{console.error(error);process.exitCode=1});
