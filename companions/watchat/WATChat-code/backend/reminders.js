'use strict';
// Durable per-account schedules contain opaque IDs and due times only.
class ReminderScheduler{
 constructor(store,save,deliver){this.store=store;this.save=save;this.deliver=deliver;this.busy=false;}
 replace(user,items,now=Date.now()){
  if(!Array.isArray(items)||items.length>128)throw Error('REMINDER_LIMIT');const seen=new Set();
  for(const item of items){if(!item||Object.keys(item).sort().join(',')!=='due,id,webhook'||!/^[a-f0-9]{64}$/.test(item.id)||!Number.isSafeInteger(item.due)||item.due<now-86400000||item.due>now+3660*86400000||typeof item.webhook!=='boolean'||seen.has(item.id))throw Error('INVALID_REMINDER');seen.add(item.id)}
  this.store.reminders??={};const previous=this.store.reminders[user]||{};this.store.reminders[user]=Object.fromEntries(items.map(item=>[item.id,{...item,sent:previous[item.id]?.sent||false}]));this.save();
 }
 async tick(now=Date.now()){
  if(this.busy)return;this.busy=true;try{for(const [user,items]of Object.entries(this.store.reminders||{}))for(const item of Object.values(items))if(!item.sent&&item.due<=now){try{await this.deliver(user,{id:item.id,webhook:item.webhook});item.sent=true;this.save()}catch(_){}}}finally{this.busy=false;}
 }
}
module.exports={ReminderScheduler};
