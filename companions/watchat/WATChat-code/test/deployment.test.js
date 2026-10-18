'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
test('WATChat worker activation preserves other applications caches',async()=>{
 const handlers={},deleted=[];
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../frontend/sw.js'),'utf8'),{self:{addEventListener:(name,handler)=>handlers[name]=handler,clients:{claim:async()=>{}}},caches:{keys:async()=>['ziokt-watchat-shell-v1','ziokt-watchat-shell-v3','ziokt-watchat-shell-v4','workbox-precache-sim','tri-project-cache'],delete:async key=>deleted.push(key)}});
 let completion;handlers.activate({waitUntil:promise=>completion=promise});await completion;assert.deepEqual(deleted,['ziokt-watchat-shell-v1','ziokt-watchat-shell-v3']);
});
