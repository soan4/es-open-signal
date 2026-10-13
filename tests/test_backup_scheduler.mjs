import test from "node:test";
import assert from "node:assert/strict";
import {etClock,slot,shouldSkipForecast,shouldSkipGrading,fireIfNeeded} from "../cloudflare-backup/src/index.mjs";
const d=s=>new Date(s);
test("US daylight saving vs standard timezone",()=>{
 assert.equal(slot(d("2026-10-13T13:20:00Z")),"preopen");
 assert.equal(etClock(d("2026-10-13T13:20:00Z")).date,"2026-10-13");
 assert.equal(slot(d("2026-12-01T14:20:00Z")),"preopen");
});
test("no late or weekend preopen",()=>{
 assert.equal(slot(d("2026-10-13T13:30:00Z")),null);
 assert.equal(slot(d("2026-10-18T13:20:00Z")),null);
});
test("grading and catchup triggers",()=>{
 assert.equal(slot(d("2026-10-13T14:10:00Z")),"grading");
 assert.equal(slot(d("2026-10-13T20:15:00Z")),"reconcile");
 assert.equal(slot(d("2026-10-17T14:15:00Z")),"weekend-reconcile");
});
test("skip when both futures forecasts already stored",()=>{
 assert.ok(shouldSkipForecast("preopen",{date:"2026-10-13",status:"ready"},
   {date:"2026-10-13",status:"ready"},"2026-10-13"));
 assert.equal(shouldSkipForecast("preopen",{date:"2026-10-12",status:"ready"},
   {date:"2026-10-13",status:"ready"},"2026-10-13"),false);
});
test("skip grading once stored",()=>{
 assert.ok(shouldSkipGrading("grading",{date:"2026-10-13",status:"verified"},
   {date:"2026-10-13",graded:true},"2026-10-13"));
});
test("no secret prevents unauthorized trigger",async()=>{
 const result=await fireIfNeeded({},d("2026-10-13T13:20:00Z"),
   async()=>{throw new Error("should not call network")});
 assert.equal(result.status,"setup-required");
});
test("dispatch api when needed and credentials stored only in env",async()=>{
 const requests=[];
 const fake=async(url,opts)=>{
   requests.push({url,opts});
   if(url.endsWith("/dispatches"))return{status:204};
   return {ok:true,json:async()=>({date:"2026-10-12",status:"ready"})};
 };
 const result=await fireIfNeeded({GITHUB_ACTIONS_TOKEN:"dummy"},d("2026-10-13T13:20:00Z"),fake);
 assert.equal(result.status,"dispatched");
 const post=requests.find(r=>r.opts.method==="POST");
 assert.deepEqual(JSON.parse(post.opts.body),{ref:"main"});
 assert.ok(post.url.includes("update-and-publish.yml/dispatches"));
});
test("up-to-date data does not trigger extra action",async()=>{
 let count=0;
 const fake=async(url,opts)=>{
   if(opts.method==="POST"){count++;return{status:204}};
   return{ok:true,json:async()=>({date:"2026-10-13",status:"ready"})};
 };
 const result=await fireIfNeeded({GITHUB_ACTIONS_TOKEN:"dummy"},d("2026-10-13T13:20:00Z"),fake);
 assert.equal(result.status,"already-predicted");
 assert.equal(count,0);
});
test("403 token failure surfaced without leaking secret",async()=>{
 const fake=async(url,opts)=>opts.method==="POST"?{status:403}:{ok:false};
 const result=await fireIfNeeded({GITHUB_ACTIONS_TOKEN:"bad-token"},d("2026-10-13T13:20:00Z"),fake);
 assert.equal(result.status,"dispatch-failed");
 assert.equal(result.http_status,403);
 assert.equal(JSON.stringify(result).includes("bad-token"),false);
});
