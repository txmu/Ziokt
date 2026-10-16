import React, { useEffect, useState } from 'react';
import { t } from '../locales';
interface Gateway { account:string;sim_federation_configured:boolean;background_push_configured:boolean;pending_reminders:boolean }
export default function GatewayPanel(){
 const [gateway,setGateway]=useState<Gateway|null>(null),[username,setUsername]=useState(''),[password,setPassword]=useState(''),[busy,setBusy]=useState(false),[message,setMessage]=useState('');
 async function request(path:string,body?:object){const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),10000);try{const response=await fetch(path,{method:body?'POST':'GET',credentials:'same-origin',cache:'no-store',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined,signal:controller.signal});if(!response.ok)throw Error(response.status===401?'AUTH_REQUIRED':'GATEWAY_UNAVAILABLE');return await response.json()}finally{clearTimeout(timer)}}
 async function refresh(){try{setGateway(await request('/api/integration'));setMessage('')}catch(_){setGateway(null);setMessage(t('未连接提醒网关；本地加密管理仍可使用。'))}}
 useEffect(()=>{refresh()},[]);
 async function login(){setBusy(true);try{await request('/api/login',{username,password});setPassword('');await refresh()}catch(_){setMessage(t('登录失败，请检查账户或同源网关配置。'))}finally{setBusy(false)}}
 async function logout(){setBusy(true);try{await request('/api/logout',{});setGateway(null);setMessage(t('已退出提醒网关。'))}catch(_){setMessage(t('网关暂不可用。'))}finally{setPassword('');setBusy(false)}}
 return <section className="bg-gray-50 rounded-xl border border-gray-200 p-4 space-y-3" aria-label={t('Ziokt 提醒网关')}>
  <h3 className="font-bold">{t('Ziokt 提醒网关')}</h3><p className="text-sm">{t('登录是可选的。卡片、号码和 PIN 不会发送至网关；仅同步不含号码的提醒标识和时间。')}</p>
  {gateway?<><p>{t('已连接账户')}: {gateway.account}</p><p>{gateway.sim_federation_configured?t('SIM 联邦桥已配置'):t('独立网关（未配置联邦桥）')}</p><p>{gateway.background_push_configured?t('后台推送已配置，仍需授权并注册此设备。'):t('后台推送未配置；仅使用本地通知。')}</p><p>{gateway.pending_reminders?t('提醒等待联邦同步'):t('无待同步提醒')}</p><button type="button" disabled={busy} onClick={logout} className="px-4 py-3 border rounded">{t('退出网关')}</button></>:<><label className="block">{t('网关用户名')}<input autoComplete="username" value={username} maxLength={32} onChange={e=>setUsername(e.target.value)} className="block w-full border rounded p-3" /></label><label className="block">{t('网关密码')}<input type="password" autoComplete="current-password" value={password} maxLength={128} onChange={e=>setPassword(e.target.value)} className="block w-full border rounded p-3" /></label><button type="button" disabled={busy||!username||!password} onClick={login} className="px-4 py-3 border rounded">{t('登录网关')}</button></>}
  <button type="button" disabled={busy} onClick={refresh} className="px-4 py-3 border rounded ml-2">{t('刷新网关状态')}</button><p role="status" aria-live="polite" className="text-sm">{message}</p>
 </section>
}
