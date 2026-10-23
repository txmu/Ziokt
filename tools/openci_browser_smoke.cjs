// Real local Controller and browser; no fixture API responses or production credentials.
const {spawn}=require('node:child_process'),readline=require('node:readline'),assert=require('node:assert/strict'),fs=require('node:fs/promises');
const pw=require(process.env.PLAYWRIGHT_NODE_PATH||'playwright');
const script=String.raw`
import tempfile,json,hashlib,secrets,threading,signal
from pathlib import Path
from openci.controller import Controller,Server,handler
with tempfile.TemporaryDirectory(prefix='openci-browser-') as area:
 root=Path(area);token=secrets.token_hex(32);config=root/'config.json'
 value={'principals':{'owner':{'role':'admin','projects':[],'token_sha256':hashlib.sha256(token.encode()).hexdigest()}}};config.write_text(json.dumps(value));config.chmod(0o600)
 controller=Controller(root/'state',config);server=Server(('127.0.0.1',0),handler(controller));origin='http://127.0.0.1:'+str(server.server_port);value['public_origin']=origin;config.write_text(json.dumps(value))
 stop=threading.Event();signal.signal(signal.SIGTERM,lambda *_:stop.set());thread=threading.Thread(target=server.serve_forever);thread.start();print(json.dumps({'origin':origin,'token':token}),flush=True)
 try:stop.wait()
 finally:server.shutdown();server.server_close();thread.join();controller.close()
`;
(async()=>{const child=spawn(process.env.PYTHON||'python3',['-u','-c',script],{stdio:['ignore','pipe','inherit']});let browser;
try{const lines=readline.createInterface({input:child.stdout});const first=await new Promise((resolve,reject)=>{lines.once('line',resolve);child.once('exit',()=>reject(Error('controller exited before ready')))});const {origin,token}=JSON.parse(first);browser=await pw.chromium.launch({headless:true});const context=await browser.newContext({viewport:{width:390,height:844}}),page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));await page.goto(origin);await page.locator('#token').fill(token);await page.locator('#login button').first().click();await page.locator('#operator').waitFor({state:'visible'});await page.locator('#invite input[name=projects]').fill('browser-project');const download=page.waitForEvent('download');await page.locator('#invite button').click();const file=await download;const invite=JSON.parse(await fs.readFile(await file.path(),'utf8'));assert.equal(invite.controller_origin,origin);assert.deepEqual(invite.caps.projects,['browser-project']);assert.equal(invite.caps.pool,'community');assert.equal(await page.evaluate(()=>localStorage.length),0);assert.equal(await page.locator('#token').inputValue(),'');assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await page.locator('#logout').click();await page.locator('#operator').waitFor({state:'hidden'});assert.deepEqual(errors,[]);await context.close();console.log('PASS real OpenCI operator login, scoped invitation download, mobile layout and sensitive state cleanup');}
finally{if(browser)await browser.close();child.kill('SIGTERM');await new Promise(resolve=>child.once('exit',resolve));}})().catch(error=>{console.error(error);process.exitCode=1});
