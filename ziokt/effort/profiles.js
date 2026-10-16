'use strict';
// Local opt-in budgets; never read intensity from a server job.
const EFFORT_PROFILES=Object.freeze([
 Object.freeze({workers:1,batch:64,pause:40,lanes:1}),
 Object.freeze({workers:1,batch:256,pause:20,lanes:2}),
 Object.freeze({workers:2,batch:512,pause:5,lanes:4}),
 Object.freeze({workers:4,batch:1024,pause:1,lanes:8}),
 Object.freeze({workers:8,batch:2048,pause:0,lanes:16})
]);
