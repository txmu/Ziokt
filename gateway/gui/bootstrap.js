/* External bootstrap works under script-src 'self', including offline PWA use. */
window.addEventListener('error',event=>{
 const container=document.getElementById('content-container');
 if(!container||(container.children.length&&!document.getElementById('app-loading-placeholder')))return;
 const section=document.createElement('section');section.className='card';
 const title=document.createElement('h2');title.textContent='客户端加载异常 / Application load error';
 const message=document.createElement('p');message.textContent=event.message||'Unknown script error';
 const reload=document.createElement('button');reload.className='btn btn-secondary';reload.textContent='重载 / Reload';reload.onclick=()=>location.reload();
 section.append(title,message,reload);container.replaceChildren(section);
});
if('serviceWorker' in navigator&&(location.protocol==='https:'||['localhost','127.0.0.1'].includes(location.hostname))){
 window.addEventListener('load',()=>navigator.serviceWorker.register('sw.js',{updateViaCache:'none'}).then(registration=>registration.update()).catch(error=>console.warn('Offline shell registration failed:',error.message)));
}
