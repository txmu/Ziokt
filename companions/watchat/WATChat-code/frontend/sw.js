'use strict';
const CACHE='ziokt-watchat-shell-v2',SHELL=['/','/app.js','/style.css','/manifest.webmanifest','/icon-192.png','/icon-512.png'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(SHELL))));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',event=>{const url=new URL(event.request.url);if(url.origin!==self.location.origin||event.request.method!=='GET'||!SHELL.includes(url.pathname))return;event.respondWith(fetch(event.request).catch(()=>caches.match(event.request)))});
self.addEventListener('message',event=>{if(event.data?.type==='locale'&&['en','zh-CN'].includes(event.data.locale))event.waitUntil(caches.open(CACHE).then(cache=>cache.put('/__locale',new Response(event.data.locale))))});
self.addEventListener('push',event=>event.waitUntil((async()=>{let locale='en';const saved=await caches.match('/__locale');if(saved)locale=await saved.text();await self.registration.showNotification('WATChat',{body:locale==='zh-CN'?'收到新消息':'New message',tag:'ziokt-watchat',icon:'/icon-192.png',badge:'/icon-192.png',data:{url:'/'}})})()));
self.addEventListener('notificationclick',event=>{event.notification.close();event.waitUntil(self.clients.matchAll({type:'window',includeUncontrolled:true}).then(async windows=>{for(const client of windows)if(new URL(client.url).origin===self.location.origin)return client.focus();return self.clients.openWindow('/')}))});
