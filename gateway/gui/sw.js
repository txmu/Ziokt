/* Only the fixed public GUI shell is cached. Never cache API data or credentials. */
const CACHE_NAME = 'ziokt-gui-shell-v2-d1b9609071bc0989d36c';
const PREFIX = 'ziokt-gui-shell-';
const STATIC_ASSETS = ['./index.html','./app.js','./bootstrap.js','./style.css','./manifest.json','./icons/icon-192.png','./icons/icon-512.png','./icons/icon.svg','./i18n/zh.json','./i18n/en.json','./i18n/zh-CN.json','./i18n/en-US.json'];
const SHELL = new URL('./index.html',self.registration.scope).href;
const NAVIGATIONS = new Set([new URL(self.registration.scope).pathname,new URL(SHELL).pathname]);
const ALLOWED = new Set(STATIC_ASSETS.map(path=>new URL(path,self.registration.scope).href));
self.addEventListener('install',event=>event.waitUntil((async()=>{
 const cache=await caches.open(CACHE_NAME);
 try {
  await cache.addAll([...ALLOWED].map(url=>new Request(url,{credentials:'omit',redirect:'error',cache:'reload'})));
  await self.skipWaiting();
 } catch(error) {await caches.delete(CACHE_NAME);throw error;}
})()));
self.addEventListener('activate',event=>event.waitUntil((async()=>{
 for(const key of await caches.keys())if(key!==CACHE_NAME&&(key.startsWith(PREFIX)||/^ziokt-gui-cache-v/.test(key)))await caches.delete(key);
 await self.clients.claim();
})()));
self.addEventListener('fetch',event=>{
 const request=event.request,url=new URL(request.url);
 if(request.method!=='GET'||url.origin!==self.location.origin||request.headers.has('Authorization'))return;
 const navigation=request.mode==='navigate'&&NAVIGATIONS.has(url.pathname);
 if(!navigation&&!ALLOWED.has(url.href))return;
 event.respondWith((async()=>{
  const cache=await caches.open(CACHE_NAME),cached=await cache.match(navigation?SHELL:request.url);
  if(cached)return cached;
  return fetch(request);
 })());
});
