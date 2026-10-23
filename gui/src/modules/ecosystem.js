/* Native application entrypoints and a local workspace with no network calls. */
import {State,apiRequest,configuredEndpoint} from '../core.js';
import {mountPrivateOffline} from '../private-offline.js';

export function renderEcosystem(container){
 const en=State.language==='en',label=(zh,english)=>en?english:zh;
 const node=(tag,text)=>{const value=document.createElement(tag);if(text!==undefined)value.textContent=text;return value;};
 container.replaceChildren();container.append(node('h2',label('应用与离线工作区','Applications and offline workspace')));
 mountPrivateOffline(container);
 const status=node('p',label('应用保留原生身份与权限。注册接口不等于已经完成运行验证。','Applications retain native identity and permissions. Registered tools are not runtime health proofs.'));status.setAttribute('role','status');container.append(status);
 const offline=node('section');offline.className='card';offline.append(node('h3',label('本地文件完整性检查','Local file integrity')),
  node('p',label('完全在此设备计算 SHA-256，不上传文件。当前浏览器预算为 16 MiB；更大文件使用本地流式客户端。','Compute SHA-256 entirely on this device. No file upload. Browser budget: 16 MiB; use the local streaming client for larger files.')));
 const fileLabel=node('label',label('选择本地文件','Choose a local file')),file=node('input');file.type='file';file.id='offline-integrity-file';fileLabel.append(file);offline.append(fileLabel);
 const result=node('p');result.id='offline-integrity-result';result.setAttribute('role','status');offline.append(result);
 const verify=node('button',label('计算校验值','Compute digest'));verify.className='btn btn-primary';verify.id='offline-integrity-check';
 verify.onclick=async()=>{verify.disabled=true;try{const selected=file.files[0];if(!selected)throw Error(label('请选择文件','Choose a file'));if(selected.size>16*1024*1024)throw Error(label('超过本地浏览器预算','Local browser budget exceeded'));const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await selected.arrayBuffer())),b=>b.toString(16).padStart(2,'0')).join('');result.textContent=selected.name+' · '+selected.size+' bytes · sha256:'+digest;}catch(error){result.textContent=error.message;}finally{verify.disabled=false;}};offline.append(verify);container.append(offline);
 const queryLabel=node('label',label('查找应用','Find applications')),query=node('input');query.type='search';query.id='ecosystem-filter';queryLabel.append(query);container.append(queryLabel);
 const grid=node('div');grid.className='ecosystem-grid';container.append(grid);
 const services=[
  ['Corium',label('论坛、群组、Wiki、Mail、MailList、Broadcast、Site、NNS、CBB 与治理；具体入口依原生部署。','Forum, Groups, Wiki, Mail, MailList, Broadcast, Site, NNS, CBB and governance; entrypoints depend on the native deployment.'),configuredEndpoint('corium','/'),'corium_'],
  ['ETP',label('Forum、Chat、Mailbox、Universal Messenger、FileShare、SignalDrop；状态接口不能代替尚未接通的业务。','Forum, Chat, Mailbox, Universal Messenger, FileShare, SignalDrop; status endpoints do not implement missing business operations.'),null,'etp_'],
  ['Library / Netnews',label('图书阅读、新闻组、授权投稿与附件。','Books, newsgroups, authorized posting and attachments.'),configuredEndpoint('content','/content/'),'library_'],
  ['WATChat',label('原生聊天；连接后仍需原生身份授权。','Native chat with its own identity authorization.'),null,'watchat_'],
  ['UFS / dCPM',label('原生文件与签名软件包。','Native files and signed software packages.'),null,'ufs_'],
  ['SafeFS',label('私有保险库，仅授权账户可访问。','Private vault, authorized accounts only.'),null,'safefs_'],
  ['Shadow6',label('原生连接、命名及应用服务，保留原生安全策略。','Native connectivity, naming and application services with native security policies.'),null,'shadow6_'],
  ['Tri / TC-16 / ZDA',label('原生计算与应用；执行目标和 ABI 仍需匹配。','Native compute and applications; execution targets and ABIs must match.'),null,'tc16_'],
 ];
 const cards=[];
 for(const [name,description,url,prefix] of services){const card=node('article');card.className='card';card.append(node('h3',name),node('p',description));const availability=node('p',label('本节点授权接口尚未查询','Authorized tools have not been queried'));availability.dataset.prefix=prefix;card.append(availability);
  if(url){const link=node('a',label('打开公共原生入口','Open public native entrypoint'));link.href=url;link.target='_blank';link.rel='noopener noreferrer';link.className='btn btn-secondary';card.append(link,node('small',new URL(url).hostname));}
  else card.append(node('small',label('此处未配置独立公共网页；请使用节点授权界面。','No standalone public page configured here; use an authorized node interface.')));
  cards.push([card,(name+' '+description).toLocaleLowerCase()]);grid.append(card);
 }
 query.oninput=()=>{const value=query.value.toLocaleLowerCase();for(const [card,text] of cards)card.hidden=!text.includes(value);};
 const inspect=node('button',label('查询本节点授权接口','Query this node’s authorized tools'));inspect.className='btn btn-primary';inspect.id='ecosystem-inspect';
 inspect.onclick=async()=>{inspect.disabled=true;status.textContent=label('正在查询…','Querying…');try{const data=await apiRequest('/api/gateway/tools',{requireAuth:true});for(const line of grid.querySelectorAll('[data-prefix]')){const count=data.tools.filter(tool=>tool.name.startsWith(line.dataset.prefix)).length;line.textContent=label('本账户已注册接口：','Registered for this account: ')+count;}status.textContent=label('目录查询成功；原生操作需逐项执行验证。','Catalog received; native operations require separate runtime verification.');}catch(error){status.textContent=error.message;}finally{inspect.disabled=false;}};container.append(inspect);
 const feeds=node('section');feeds.className='card';feeds.append(node('h3',label('普通客户端与资讯订阅','Standard clients and feeds')));
 for(const [name,url] of [['NNTP TLS',configuredEndpoint('nntp','/nntp/')],['RSS',new URL('feeds/all.rss',configuredEndpoint('content','/content/')).href],['Atom',new URL('feeds/all.atom',configuredEndpoint('content','/content/')).href],['JSON Feed',new URL('feeds/all.json',configuredEndpoint('content','/content/')).href],['OPML',new URL('feeds/subscriptions.opml',configuredEndpoint('content','/content/')).href]]){const link=node('a',name);link.href=url;link.target='_blank';link.rel='noopener noreferrer';link.className='btn btn-secondary';feeds.append(link);}
 container.append(feeds);
}
