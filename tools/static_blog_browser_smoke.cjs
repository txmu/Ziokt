const {spawn}=require('node:child_process');
const {once}=require('node:events');
const assert=require('node:assert/strict');
let pw;try{pw=require('../ci/browser/node_modules/playwright')}catch(_){pw=require('../.runtime/browser/node_modules/playwright')}
(async()=>{
 const child=spawn(process.env.PYTHON||'python3',['ci/static_blog_fixture.py'],{cwd:require('node:path').resolve(__dirname,'..'),stdio:['pipe','pipe','inherit']});
 let browser;
 try{
  const line=await new Promise((resolve,reject)=>{let text='';child.stdout.on('data',data=>{text+=data;if(text.includes('\n'))resolve(text.split('\n')[0]);});child.on('exit',code=>reject(Error('fixture exited '+code)));setTimeout(()=>reject(Error('fixture deadline')),15000).unref();});
  const {port}=JSON.parse(line);browser=await pw.chromium.launch({headless:true});const page=await browser.newPage();const errors=[];page.on('pageerror',error=>errors.push(error.message));
  const response=await page.goto(`http://127.0.0.1:${port}/`);assert.equal(response.status(),200);
  await page.waitForFunction(()=>document.title==='Real blog ready');await page.click('#search');await page.waitForFunction(()=>document.querySelector('#result').textContent==='Actual search result');
  assert.equal(await page.getAttribute('body','data-count'),'1');await page.reload();await page.waitForFunction(()=>document.body.dataset.count==='2');
  const denied=await page.request.get(`http://127.0.0.1:${port}/api/gateway/tools`);assert.equal(denied.status(),404);assert.deepEqual(errors,[]);
  console.log('PASS: verified static JS, ESM import, actual JSON search, persistent storage and absent admin API');
 }finally{if(browser)await browser.close();child.stdin.end();if(child.exitCode===null)await once(child,'exit');}
})().catch(error=>{console.error(error);process.exitCode=1;});
