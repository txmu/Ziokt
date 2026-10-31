import {State,getActiveRemoteNode,renderToolPanel} from '../core.js';
import {renderEcosystem} from './ecosystem.js';

export function renderApps(container){
 renderEcosystem(container);
 mountWebsiteHub(container);
 const native=document.createElement('section');native.className='card';container.append(native);
 renderToolPanel(native,'dCPM / Native packages',name=>/^(dcpm_|package_)/.test(name)).catch(error=>{native.textContent=error.message;});
}

function mountWebsiteHub(container){
 const label=(zh,en)=>State.language.startsWith('en')?en:zh;
 const box=document.createElement('section');box.className='card';box.style.padding='20px';
 const heading=document.createElement('h2');heading.textContent=label('独立建站与节点 ZDNS','Websites and node ZDNS');
 const note=document.createElement('p');note.textContent=label('访问静态站点、Wiki 与博客导出；多层子域按签名逐层验证，私有应用单独授权。','Browse native static sites, wiki and blog exports. Subdomains require signed delegations; private apps require separate grants.');
 const form=document.createElement('form'),name=document.createElement('input'),path=document.createElement('input'),open=document.createElement('button'),catalog=document.createElement('button'),result=document.createElement('pre');
 name.required=true;name.placeholder='blog.team.example.corix';name.setAttribute('aria-label',label('Ziokt 完整域名','Full Ziokt name'));path.placeholder='posts/hello/';path.setAttribute('aria-label',label('文件路径','File path'));
 open.textContent=label('通过当前节点打开','Open through this node');open.className='btn btn-primary';catalog.textContent=label('查看建站方式与实际节点配置','Website methods and node configuration');catalog.type='button';catalog.className='btn btn-secondary';result.style.whiteSpace='pre-wrap';
 const base=()=>new URL(State.runtimeMode==='local'?State.localGatewayUrl:(getActiveRemoteNode()?.url||State.gatewayUrl)).origin;
 form.onsubmit=event=>{event.preventDefault();try{window.open(ZioktSiteUrl(base(),name.value.trim(),path.value),'_blank','noopener,noreferrer');}catch(error){result.textContent=error.message;}};
 catalog.onclick=async()=>{try{const response=await fetch(new URL('/api/gateway/sites',base()),{credentials:'omit',cache:'no-store',signal:AbortSignal.timeout(10000)});if(!response.ok)throw Error('Site catalog unavailable');result.textContent=JSON.stringify(await response.json(),null,2);}catch(error){result.textContent=error.message;}};
 form.append(name,path,open);box.append(heading,note,form,catalog,result);container.prepend(box);
}
