'use strict';
// Shared URL builder: public site navigation has no application credentials.
(function(root){
const suffixes=["3c", "a", "ano", "b", "c", "cor", "corium", "corix", "d", "dcpm", "dr", "e", "etp", "f", "fs", "g", "h", "i", "j", "k", "l", "m", "n", "num", "o", "p", "q", "r", "s", "s6", "safefs", "shadow", "shadow6", "sim", "t", "tc16", "tcc", "tri", "ttc", "u", "ufs", "v", "w", "wat", "wch", "wchat", "x", "y", "z", "zda", "zi", "zio", "ziok", "ziokn", "ziokt", "zioktriuk", "zioktruik", "zioktruk"];
function siteUrl(origin,name,path=''){
 const url=new URL(origin);
 if(url.username||url.password||url.search||url.hash||!['','/'].includes(url.pathname)||!(url.protocol==='https:'||url.protocol==='http:'&&['127.0.0.1','localhost','[::1]'].includes(url.hostname)))throw Error('HTTPS Gateway origin required');
 if(typeof name!=='string'||name.length>253||name!==name.toLowerCase())throw Error('Canonical Ziokt name required');
 const labels=name.split('.'),suffix=labels.pop();
 if(labels.length<1||labels.length>9||!suffixes.includes(suffix)||labels.some(v=>!(/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/).test(v)))throw Error('Ziokt suffix and valid domain labels required');
 if(typeof path!=='string'||path.length>2048||/[\\\x00-\x1f?#%]/.test(path)||path.split('/').some(v=>v==='.'||v==='..'))throw Error('Safe relative website path required');
 url.pathname='/gateway/'+suffix+'/'+labels.join('.')+'/'+path.replace(/^\/+/, '').split('/').map(encodeURIComponent).join('/');return url.href;
}
root.ZioktSiteUrl=siteUrl;if(typeof module!=='undefined')module.exports=siteUrl;
})(globalThis);
