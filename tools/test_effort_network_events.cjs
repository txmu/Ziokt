'use strict';
// Exercise the shipped scripts with OS/browser network events, without network probes.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function harness(file){
 const listeners={},elements={};
 const element=id=>elements[id]||(elements[id]={value:id==='help-mode'?'compute':'2',checked:false,textContent:'',options:Array.from({length:5},()=>({})),addEventListener(t,fn){(this.events||(this.events={}))[t]=fn},setAttribute(){}});
 const navigator={language:'zh',onLine:true,hardwareConcurrency:1};let calls=0,aborts=0;
 const context={navigator,console,Set,Map,Promise,TextEncoder,BigInt,AbortController,JSON,Error,setTimeout,clearTimeout,
  document:{hidden:false,visibilityState:'visible',documentElement:{},querySelector:s=>element(s.slice(1)),getElementById:element,querySelectorAll:()=>[],addEventListener(){}},
  isSecureContext:true,crypto:{subtle:{}},Worker:function(){this.terminate=()=>{};this.postMessage=()=>{}},
  fetch(){calls++;return new Promise(()=>{})},
  XMLHttpRequest:function(){this.open=()=>{};this.setRequestHeader=()=>{};this.send=()=>{calls++};this.abort=()=>{aborts++}},
  EFFORT_PROFILES:[{workers:1},{workers:1}],addEventListener(t,fn){(listeners[t]||(listeners[t]=[])).push(fn)}};
 context.window=context;vm.createContext(context);
 vm.runInContext(fs.readFileSync('ziokt/effort/modes.js','utf8'),context);
 vm.runInContext(fs.readFileSync(file,'utf8'),context);
 return {context,element,listeners,get calls(){return calls},get aborts(){return aborts},event(t){navigator.onLine=t==='online';for(const fn of listeners[t]||[])fn()},click(){element('start').events.click({preventDefault(){},stopImmediatePropagation(){}})}};
}
const compute=harness('ziokt/effort/app.js');
compute.event('offline');compute.click();assert.match(compute.element('status').textContent,/网络已断开/);assert.equal(compute.calls,0);
compute.event('online');assert.equal(vm.runInContext('active',compute.context),true);
compute.event('offline');assert.equal(vm.runInContext('active',compute.context),false);assert.equal(vm.runInContext('workers.size',compute.context),0);
compute.click();compute.event('online');assert.equal(vm.runInContext('active',compute.context),false);
const relay=harness('ziokt/effort/relay.js');relay.element('help-mode').value='network';
relay.event('offline');relay.click();assert.match(relay.element('status').textContent,/网络已断开/);
const initial=relay.calls;relay.click();relay.event('online');assert.equal(relay.calls,initial);
// No periodic connectivity check is installed by either script.
for(const file of ['app.js','relay.js'])assert.doesNotMatch(fs.readFileSync('ziokt/effort/'+file,'utf8'),/setInterval|https?:\/\/.*(?:connectivity|generate_204)/);
console.log('PASS: offline pause, worker cancellation, online resume, manual cancellation, no connectivity polling');
