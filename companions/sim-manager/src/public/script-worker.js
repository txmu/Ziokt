'use strict';
const reply=self.postMessage.bind(self),compile=Function;
for(const name of ['fetch','XMLHttpRequest','WebSocket','EventSource','WebTransport','Worker','SharedWorker','importScripts','indexedDB','caches','BroadcastChannel'])Object.defineProperty(self,name,{value:undefined,writable:false,configurable:false});
let used=false;
self.onmessage=event=>{if(used)return;used=true;const {id,code,data,input}=event.data;const output=[];let text='',chart=null;
 try{if(typeof code!=='string'||code.length>32768||typeof input!=='string'||input.length>65536)throw Error('SCRIPT_LIMIT');
 const api=Object.freeze({log:(...args)=>{if(output.length<64)output.push(args.map(a=>JSON.stringify(a)).join(' ').slice(0,4096))},readInput:()=>input,writeOutput:value=>{text=String(value).slice(0,65536)},renderPieChart:(title,data)=>chart={title,type:'pie',data},renderBarChart:(title,data)=>chart={title,type:'bar',data},renderLineChart:(title,data)=>chart={title,type:'line',data}});
 compile('data','api','"use strict";\n'+code)(Object.freeze(data),api);const result=JSON.stringify({id,ok:true,output,text,chart});if(result.length>131072)throw Error('SCRIPT_LIMIT');reply(JSON.parse(result));
 }catch(e){reply({id,ok:false,error:String(e.message).slice(0,256)})}finally{self.close()}
};
