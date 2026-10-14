'use strict';
self.addEventListener('push',event=>event.waitUntil((async()=>{await self.registration.showNotification('SIM Manager',{body:'A subscription needs attention / 有套餐需要关注',tag:'ziokt-sim-reminder',icon:'/sim/icon-192.png',data:{url:'/sim/'}})})()));
self.addEventListener('notificationclick',event=>{event.notification.close();event.waitUntil(self.clients.matchAll({type:'window',includeUncontrolled:true}).then(async clients=>{for(const client of clients)if(new URL(client.url).pathname.startsWith('/sim/'))return client.focus();return self.clients.openWindow('/sim/')}))});
