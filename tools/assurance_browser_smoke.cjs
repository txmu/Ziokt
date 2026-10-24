/* Public scope rendering test; the API response is a fixture, not node-health evidence. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const http=require('node:http');
const path=require('node:path');
const {chromium}=require('../ci/browser/node_modules/playwright');
let available=true;
const scope={schema:'ziokt.gateway.v1',build:{source_commit:'a'.repeat(40)},native_entrypoint_digest:'sha256:'+'b'.repeat(64),
  assurance:{schema:'ziokt.assurance-scope.v1',privacy:{mainnet_feature_enabled:true,independently_audited:false},
    consensus:{operational_state:'safety_hold',safety_hold:{reason_code:'HISTORY_PROVENANCE_UNVERIFIED',first_unverified_height:51}}}};
const server=http.createServer((req,res)=>{
  if(req.url==='/api/gateway/status'){
    res.writeHead(available?200:503,{'Content-Type':'application/json'});
    return res.end(JSON.stringify(available?scope:{error:'unavailable'}));
  }
  const name=req.url.slice(1);
  if(!['assurance.html','assurance.css','assurance.js'].includes(name)){res.writeHead(404);return res.end();}
  res.setHeader('Content-Type',name.endsWith('.html')?'text/html; charset=utf-8':name.endsWith('.css')?'text/css':'text/javascript');
  res.end(fs.readFileSync(path.join(__dirname,'../gateway/gui',name)));
});
(async()=>{
  let browser;
  try{
    await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
    browser=await chromium.launch({headless:true,args:['--no-sandbox']});
    const page=await browser.newPage();const errors=[];page.on('pageerror',error=>errors.push(error.message));
    for(const width of [390,1280]){
      await page.setViewportSize({width,height:900});
      await page.goto(`http://127.0.0.1:${server.address().port}/assurance.html`);
      await page.waitForFunction(()=>document.querySelector('#load-status').textContent.includes('已取得'));
      assert.match(await page.locator('#consensus-state').textContent(),/安全暂停.*51/);
      assert.match(await page.locator('#privacy').textContent(),/未提供证据/);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    }
    available=false;await page.reload();
    await page.waitForFunction(()=>document.querySelector('#load-status').textContent.includes('无法确认'));
    assert.equal(await page.locator('#revision').textContent(),'未确认');assert.deepEqual(errors,[]);
    console.log('PASS assurance UI: mobile/desktop hold, audit distinction, no overflow, unavailable API fails visibly');
  }finally{if(browser)await browser.close();server.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
