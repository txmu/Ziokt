import type { AppData } from '../types';
export function runIsolatedScript(code:string,data:AppData,input:string):Promise<{output:string[];text:string;chart:any}>{
 return new Promise((resolve,reject)=>{
  const worker=new Worker('/sim/script-worker.js');const id=crypto.randomUUID();
  const timer=setTimeout(()=>{worker.terminate();reject(Error('SCRIPT_DEADLINE'))},1000);
  const close=()=>{clearTimeout(timer);worker.terminate()};
  worker.onerror=()=>{close();reject(Error('SCRIPT_REJECTED'))};
  worker.onmessage=event=>{if(event.data.id!==id)return;close();if(!event.data.ok)reject(Error(event.data.error));else resolve(event.data)};
  const exposed=structuredClone(data);
  for(const sub of exposed.subscriptions){delete sub.phoneNumber;delete sub.simPin;delete sub.simPuk;delete sub.virtualNumbers;delete sub.bankAccount;delete sub.debitCreditCard;}
  delete exposed.securitySettings;delete exposed.syncSettings;
  worker.postMessage({id,code,data:exposed,input});
 });
}
