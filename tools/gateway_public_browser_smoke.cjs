'use strict';
// Explicit operator-only deployment smoke. The administrator credential is never logged.
const fs=require('node:fs'),assert=require('node:assert/strict');
let pw;try{pw=require('../ci/browser/node_modules/playwright')}catch(_){pw=require('../.runtime/browser/node_modules/playwright')}
(async()=>{
 const [portal,issuer,tokenFile]=process.argv.slice(2);assert(portal&&issuer&&tokenFile,'portal HTTPS origin, issuer HTTPS origin and private token file required');
 for(const origin of [portal,issuer]){const u=new URL(origin);assert.equal(u.origin,origin);assert.equal(u.protocol,'https:');}
 const info=fs.lstatSync(tokenFile);assert(info.isFile()&&(info.mode&0o777)===0o600,'private regular token file required');
 const browser=await pw.chromium.launch({headless:true});
 try{
  const page=await browser.newPage({viewport:{width:390,height:844}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(portal+'/app/explorer/blockchain?lang=en-US');await page.locator('#mcp-connect').click();
  await page.waitForURL(url=>url.origin===issuer&&url.pathname==='/oauth/authorize');
  assert.equal(new URL(page.url()).searchParams.get('redirect_uri'),portal+'/gateway-assets/oauth-callback.html');
  await page.locator('input[name="admin_token"]').fill(fs.readFileSync(tokenFile,'utf8').trim());
  await page.getByRole('button',{name:'Approve scopes'}).click();await page.waitForURL(portal+'/app/explorer/blockchain?lang=en-US').catch(async error=>{console.error('callback diagnosis',new URL(page.url()).origin+new URL(page.url()).pathname,await page.locator('body').innerText());throw error;});
  await page.locator('#mcp-form').waitFor();await page.locator('#mcp-tool').selectOption('corium_registration_list');
  await page.locator('#mcp-arguments').fill(JSON.stringify({status:'approved'}));await page.locator('#mcp-form button').click();
  await page.waitForFunction(()=>document.querySelector('#mcp-result').textContent.includes('registrations'));
  assert(!JSON.parse(await page.locator('#mcp-result').innerText()).isError);
  await page.locator('#mcp-disconnect').click();await page.locator('#mcp-connect').waitFor();assert.deepEqual(errors,[]);
  console.log('PASS public TLS browser: portal -> canonical MCP OAuth PKCE -> exact callback CORS -> owner registry read -> revoke');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
