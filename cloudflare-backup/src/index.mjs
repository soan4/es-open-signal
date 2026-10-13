/**
 * Independent Cloudflare Cron Trigger for the ES + NQ opening gap forecaster.
 * Does not generate/replace a forecast. Sends an authenticated GitHub Actions
 * workflow_dispatch, where the existing ET cutoff prevents look-ahead.
 *
 * Setup once: define secret GITHUB_ACTIONS_TOKEN in this Cloudflare Worker.
 * Restrict the fine-grained PAT to this repository, Actions: Read and write.
 */
const OWNER="soan4";
const REPOSITORY="es-open-signal";
const WORKFLOW="update-and-publish.yml";

export function etClock(when){
  const parts=new Intl.DateTimeFormat("en-US",{
    timeZone:"America/New_York",year:"numeric",month:"2-digit",
    day:"2-digit",hour:"2-digit",minute:"2-digit",hourCycle:"h23",
    weekday:"short"
  }).formatToParts(when);
  const p=Object.fromEntries(parts.filter(x=>x.type!=="literal").map(x=>[x.type,x.value]));
  return {date:p.year+"-"+p.month+"-"+p.day,
          hour:Number(p.hour),minute:Number(p.minute),weekday:p.weekday};
}

export function slot(when){
  const p=etClock(when);
  // The Worker fires every 5 min in 13-16 UTC. Only these NY slots dispatch.
  // Both standard and daylight saving time are supported automatically.
  if(["Mon","Tue","Wed","Thu","Fri"].includes(p.weekday)){
    if(p.hour===9 && [10,15,20,25].includes(p.minute)) return "preopen";
    if(p.hour===10 && [10,30,50].includes(p.minute)) return "grading";
    if(p.hour===11 && p.minute===15) return "grading";
    if(p.hour===16 && p.minute===15) return "reconcile";
  }
  if(p.weekday==="Sat" && p.minute===15 && [10,11].includes(p.hour)){
    return "weekend-reconcile";
  }
  return null;
}
export function shouldSkipForecast(purpose, latest,shadow,targetDate){
  return purpose==="preopen" &&
    latest?.date===targetDate && latest?.status==="ready" &&
    shadow?.date===targetDate && shadow?.status==="ready";
}
export function shouldSkipGrading(purpose, verified, shadow,targetDate){
  return purpose==="grading" && verified?.date===targetDate &&
    verified?.status==="verified" &&
    (shadow?.date!==targetDate || shadow?.graded===true);
}
async function getArchive(name, fetched, now){
  const u="https://raw.githubusercontent.com/"+OWNER+"/"+REPOSITORY+
           "/main/data/"+name+"?v="+now.getTime();
  try{
    const res=await fetched(u,{headers:{"Accept":"application/json"},
                               cf:{cacheTtl:0,cacheEverything:false}});
    return res.ok?await res.json():null;
  }catch(_){return null;}
}

export async function fireIfNeeded(env,now=new Date(),fetched=fetch){
  const purpose=slot(now);
  if(!purpose)return {status:"outside-window"};
  const date=etClock(now).date;
  if(!env.GITHUB_ACTIONS_TOKEN)return {status:"setup-required",purpose,date};
  if(purpose==="preopen"||purpose==="grading"){
    const [latest,shadow,verified]=await Promise.all([
      getArchive("latest.json",fetched,now),
      getArchive("shadow.json",fetched,now),
      purpose==="grading"?getArchive("verification.json",fetched,now):Promise.resolve(null)
    ]);
    if(shouldSkipForecast(purpose,latest,shadow,date))
      return {status:"already-predicted",purpose,date};
    if(shouldSkipGrading(purpose,verified,shadow,date))
      return {status:"already-graded",purpose,date};
  }
  const url="https://api.github.com/repos/"+OWNER+"/"+REPOSITORY+
            "/actions/workflows/"+WORKFLOW+"/dispatches";
  const response=await fetched(url,{
    method:"POST",
    headers:{
      "Authorization":"Bearer "+env.GITHUB_ACTIONS_TOKEN,
      "Accept":"application/vnd.github+json",
      "X-GitHub-Api-Version":"2022-11-28",
      "User-Agent":"es-open-signal-cloudflare-scheduler"
    },
    body:JSON.stringify({ref:"main"})
  });
  if(response.status!==204){
    // Do not emit the token or full provider response into the log.
    return {status:"dispatch-failed",purpose,date,http_status:response.status};
  }
  return {status:"dispatched",purpose,date};
}
export default {
  async scheduled(_controller,env,ctx){
    ctx.waitUntil((async()=>{
      const result=await fireIfNeeded(env,new Date());
      console.log("External trigger:",JSON.stringify(result));
      if(result.status==="dispatch-failed"||result.status==="setup-required")
        throw new Error("Backup scheduler cannot dispatch: "+result.status);
    })());
  },
  async fetch(_request){
    return new Response(JSON.stringify({service:"ES Open Signal backup scheduler",
      notice:"Read-only endpoint. All triggering uses internal Cloudflare Cron.",
      token:"not exposed"}),{
      status:200,headers:{"content-type":"application/json;charset=utf-8",
         "cache-control":"no-store"}});
  }
};
