import type { Subscription, NotificationSettings } from '../types';
import { calculateNextRenewal } from './helpers';
export interface Reminder { id: string; due: number; webhook: boolean }
const DAY=86400000;
const encoder=new TextEncoder();
export async function planReminders(subscriptions: Subscription[], settings: NotificationSettings, now=Date.now()): Promise<Reminder[]> {
 if(!settings.enabled)return [];
 const result:Reminder[]=[];
 for(const sub of subscriptions.slice(0,128)){
  if(sub.isArchived||sub.cycleType==='permanent')continue;
  const renewal=calculateNextRenewal(sub.startDate,sub.cycleDays,sub.cycleType,sub.lastActiveDate).getTime();
  if(!Number.isFinite(renewal))continue;
  const threshold=Math.max(0,Math.min(365,Number(sub.notificationThreshold)||0));
  const due=Math.max(now-DAY,renewal-threshold*DAY);
  const hash=await crypto.subtle.digest('SHA-256',encoder.encode('Ziokt/SIM/reminder/v1/'+sub.id+'/'+renewal));
  result.push({id:Array.from(new Uint8Array(hash),v=>v.toString(16).padStart(2,'0')).join(''),due,webhook:!!settings.webhookEnabled});
 }
 return result;
}
async function stateDB():Promise<IDBDatabase>{return new Promise((resolve,reject)=>{const r=indexedDB.open('ziokt-sim-reminders',1);r.onupgradeneeded=()=>r.result.createObjectStore('sent');r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)})}
async function sent(db:IDBDatabase,id:string,mark=false):Promise<boolean>{return new Promise((resolve,reject)=>{const tx=db.transaction('sent',mark?'readwrite':'readonly'),store=tx.objectStore('sent'),r=mark?store.put(true,id):store.get(id);r.onsuccess=()=>resolve(!!r.result);r.onerror=()=>reject(r.error)})}
export async function notifyGeneric(settings:NotificationSettings):Promise<void>{
 if(!('Notification'in window)||Notification.permission!=='granted'||!('serviceWorker'in navigator))throw Error('NOTIFICATION_PERMISSION_REQUIRED');
 const registration=await navigator.serviceWorker.ready;
 const chinese=document.documentElement.lang==='zh-CN';
 await registration.showNotification('SIM Manager',{body:chinese?'有套餐需要关注':'A subscription needs attention',tag:'ziokt-sim-reminder',icon:'/sim/icon-192.png',silent:!settings.soundEnabled,data:{url:'/sim/'}});
}
export async function runReminders(items:Reminder[],settings:NotificationSettings,now=Date.now()):Promise<void>{
 if(!settings.enabled)return;
 const db=await stateDB();
 try{for(const item of items){if(item.due>now||await sent(db,item.id))continue;await notifyGeneric(settings);await sent(db,item.id,true)}}finally{db.close()}
}
export async function registerBackground(items:Reminder[]):Promise<{background:boolean;webhook:boolean}>{
 const response=await fetch('/api/reminders',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({items}),cache:'no-store'});
 if(!response.ok)throw Error('FEDERATION_NOTIFICATION_GATEWAY_REQUIRED');return response.json();
}
export async function enableNotifications():Promise<boolean>{
 if(!('Notification'in window)||!('serviceWorker'in navigator)||!window.isSecureContext)return false;
 if(await Notification.requestPermission()!=='granted')return false;
 const registration=await navigator.serviceWorker.ready;
 const response=await fetch('/api/push-key',{cache:'no-store',credentials:'same-origin'});
 if(!response.ok)return true;const config=await response.json();if(!config.enabled)return true;
 const raw=atob(config.publicKey.replace(/-/g,'+').replace(/_/g,'/'));
 const subscription=await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:Uint8Array.from(raw,v=>v.charCodeAt(0))});
 const registered=await fetch('/api/push-subscription',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify(subscription.toJSON())});
 if(!registered.ok)throw Error('PUSH_REGISTRATION_FAILED');return true;
}
