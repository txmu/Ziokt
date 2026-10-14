'use strict';
const https=require('node:https'),dns=require('node:dns').promises,net=require('node:net'),crypto=require('node:crypto');
function publicAddress(address){if(net.isIP(address)===4){const b=address.split('.').map(Number);return !(b[0]===0||b[0]===10||b[0]===127||b[0]>=224||(b[0]===169&&b[1]===254)||(b[0]===172&&b[1]>=16&&b[1]<=31)||(b[0]===192&&(b[1]===168||b[1]===0))||(b[0]===100&&b[1]>=64&&b[1]<=127)||(b[0]===198&&(b[1]===18||b[1]===19)))}if(net.isIP(address)===6){const v=address.toLowerCase();return !v.includes('.')&&/^2[0-9a-f]{3}:/.test(v)&&!v.startsWith('2001:db8:')}return false}
class Webhook{
 constructor(config,lookup=dns.lookup,request=https.request){this.url=new URL(config.endpoint);if(this.url.protocol!=='https:'||this.url.username||this.url.password||this.url.port||net.isIP(this.url.hostname)||typeof config.secret!=='string'||config.secret.length<32)throw Error('INVALID_WEBHOOK_CONFIG');this.secret=config.secret;this.lookup=lookup;this.request=request;}
 async send(id){
  const addresses=await this.lookup(this.url.hostname,{all:true});if(!addresses.length||addresses.some(item=>!publicAddress(item.address)))throw Error('WEBHOOK_ADDRESS_REJECTED');const pinned=addresses[0],payload=JSON.stringify({schema:'ziokt.sim-reminder.v1',id});const signature=crypto.createHmac('sha256',this.secret).update(payload).digest('hex');
  return new Promise((resolve,reject)=>{const req=this.request(this.url,{method:'POST',headers:{'Content-Type':'application/json','Content-Length':Buffer.byteLength(payload),'X-Ziokt-Signature':signature},timeout:5000,lookup:(_,options,callback)=>callback(null,pinned.address,pinned.family)},res=>{res.resume();res.on('end',()=>res.statusCode>=200&&res.statusCode<300?resolve():reject(Error('WEBHOOK_DELIVERY_FAILED')))});req.on('error',reject);req.on('timeout',()=>req.destroy(Error('WEBHOOK_TIMEOUT')));req.end(payload)})
 }
}
module.exports={Webhook,publicAddress};
