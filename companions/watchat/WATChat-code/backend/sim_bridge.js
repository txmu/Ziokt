'use strict';
// Only existing local accounts receive schedules; retries survive in encrypted store state.
class SimFederation{
 constructor(bridge,store,save,scheduler){this.bridge=bridge;this.store=store;this.save=save;this.scheduler=scheduler;this.busy=false;store.simPending??={};store.simBridgeEvents??={}}
 queue(user,items){this.store.simPending[user]=items;this.save()}
 async flush(){if(this.busy)return;this.busy=true;try{for(const user of this.store.users){const pending=this.store.simPending[user.id];if(pending){await this.bridge.call('sim.reminders.replace',{user:user.id,items:pending});if(this.store.simPending[user.id]!==pending)continue;delete this.store.simPending[user.id];this.save()}const next=await this.bridge.call('sim.reminders.pull',{user:user.id});if(!this.store.simPending[user.id]&&next.event&&this.store.simBridgeEvents[user.id]!==next.event){this.scheduler.replace(user.id,next.items);this.store.simBridgeEvents[user.id]=next.event;this.save()}}}catch(_){/* Durable schedules are retried on the next tick. */}finally{this.busy=false}}
}
module.exports={SimFederation};
