'use strict';
const crypto=require('node:crypto');
const DEFAULT_HOSTS=['fcm.googleapis.com','updates.push.services.mozilla.com','web.push.apple.com'];
function subscription(value,hosts=DEFAULT_HOSTS){
 if(!value||typeof value!=='object'||!value.keys||typeof value.endpoint!=='string'||value.endpoint.length>4096)throw Error('INVALID_SUBSCRIPTION');
 const url=new URL(value.endpoint);if(url.protocol!=='https:'||url.username||url.password||url.port||!hosts.includes(url.hostname))throw Error('PUSH_ENDPOINT_REJECTED');
 if(!/^[A-Za-z0-9_-]{87}$/.test(value.keys.p256dh)||!/^[A-Za-z0-9_-]{22}$/.test(value.keys.auth))throw Error('INVALID_SUBSCRIPTION');
 if(Buffer.from(value.keys.p256dh,'base64url').length!==65||Buffer.from(value.keys.auth,'base64url').length!==16)throw Error('INVALID_SUBSCRIPTION');
 return {endpoint:url.href,expirationTime:null,keys:{p256dh:value.keys.p256dh,auth:value.keys.auth}};
}
class PushDispatcher{
 constructor(config,store,save,transport){this.store=store;this.save=save;this.hosts=config.endpointHosts||DEFAULT_HOSTS;this.pending=new Map(Object.entries(store.pushPending||{}));this.transport=transport||require('web-push');this.transport.setVapidDetails(config.subject,config.publicKey,config.privateKey);this.publicKey=config.publicKey;this.timer=null;this.inFlight=false;}
 register(user,value){const s=subscription(value,this.hosts);this.store.pushSubscriptions??={};const key=crypto.createHash('sha256').update(s.endpoint).digest('hex');const entries=this.store.pushSubscriptions[user]||{};if(Object.keys(entries).length>=4&&!entries[key])throw Error('PUSH_LIMIT');entries[key]=s;this.store.pushSubscriptions[user]=entries;this.save();return key;}
 unregister(user){if(this.store.pushSubscriptions)delete this.store.pushSubscriptions[user];this.pending.delete(user);this.save();}
 enqueue(user){this.pending.set(user,true);this.store.pushPending=Object.fromEntries(this.pending);this.save();if(!this.timer)this.timer=setTimeout(()=>{this.timer=null;this.flush().catch(()=>{})},15000);}
 async deliver(user){const entries=Object.entries(this.store.pushSubscriptions?.[user]||{});if(!entries.length)throw Error('PUSH_SUBSCRIPTION_REQUIRED');let success=false;for(const [key,s]of entries){try{await this.transport.sendNotification(subscription(s,this.hosts),JSON.stringify({schema:'ziokt.watchat-wakeup.v1'}),{TTL:300,urgency:'normal',topic:'ziokt-watchat',timeout:5000});success=true}catch(e){if(e.statusCode===404||e.statusCode===410){delete this.store.pushSubscriptions[user][key];this.save()}else throw e}}if(!success)throw Error('PUSH_DELIVERY_FAILED');}
 async flush(){if(this.inFlight)return;this.inFlight=true;try{for(const user of [...this.pending.keys()]){try{await this.deliver(user);this.pending.delete(user);this.store.pushPending=Object.fromEntries(this.pending);this.save()}catch(_){}}}finally{this.inFlight=false;}}

 close(){if(this.timer)clearTimeout(this.timer);}
}
module.exports={subscription,PushDispatcher};
