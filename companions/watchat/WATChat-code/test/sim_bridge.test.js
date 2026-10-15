'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const {SimFederation}=require('../backend/sim_bridge'),{ReminderScheduler}=require('../backend/reminders');
test('SIM native bridge retries, schedules and delivers without losing a concurrent edit',async()=>{
 const store={users:[{id:'local-user'}]},delivered=[],saved=[];let fail=true,remote={items:[],event:null},federation;
 const scheduler=new ReminderScheduler(store,()=>saved.push(1),async(user,item)=>delivered.push(item.id));
 const bridge={async call(method,params){if(method.endsWith('replace')){if(fail){fail=false;throw Error('OFFLINE')}remote={items:params.items,event:'event-'+params.items[0].id};if(params.items[0].id==='old')federation.queue('local-user',[{id:'a'.repeat(64),due:Date.now(),webhook:false}]);return {event:remote.event}}return remote}};
 federation=new SimFederation(bridge,store,()=>saved.push(1),scheduler);federation.queue('local-user',[{id:'old',due:Date.now(),webhook:false}]);await federation.flush();assert.ok(store.simPending['local-user']);await federation.flush();assert.equal(store.simPending['local-user'][0].id,'a'.repeat(64));await federation.flush();assert.equal(store.simPending['local-user'],undefined);await scheduler.tick();assert.deepEqual(delivered,['a'.repeat(64)]);await federation.flush();await scheduler.tick();assert.equal(delivered.length,1);assert.ok(saved.length>0);
});
test('a renewed due time resets sent state and bridge respects AirGap',async()=>{
 const store={},scheduler=new ReminderScheduler(store,()=>{},async()=>{}),now=Date.now(),item={id:'b'.repeat(64),due:now,webhook:false};scheduler.replace('user',[item],now);await scheduler.tick(now);assert.equal(store.reminders.user[item.id].sent,true);scheduler.replace('user',[{...item,due:now+1000}],now);assert.equal(store.reminders.user[item.id].sent,false);
 const {BridgeWorker}=require('../backend/bridge');const old=process.env.ZIOKT_AIRGAP;process.env.ZIOKT_AIRGAP='1';try{await assert.rejects(new BridgeWorker('/not-used').call('sim.reminders.pull',{}),/AIRGAP_DENIED/)}finally{if(old===undefined)delete process.env.ZIOKT_AIRGAP;else process.env.ZIOKT_AIRGAP=old}
});
