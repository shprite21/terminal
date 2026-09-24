// Explicit integration/benchmark run; isolated synthetic computations, no provider calls.
import assert from 'node:assert/strict';
import {once} from 'node:events';
import {mkdir,writeFile} from 'node:fs/promises';
import {spawnSync} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {EngineBridge} from '../engine.mjs';
import {createGateway} from '../server.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../../..');
const out=path.join(root,'.data/flagship-validation',new Date().toISOString().replaceAll(':','-'));
await mkdir(out,{recursive:true});
const metrics={recorded_at:new Date().toISOString(),node:process.version,platform:process.platform,notes:'One local run, warm OS caches possible; not a before/after speedup claim.',synthetic_only:true};
const engine=new EngineBridge();
const gateway=createGateway({engine,codex:{stop(){}}});
gateway.listen(0,'127.0.0.1');await once(gateway,'listening');
const base=`http://127.0.0.1:${gateway.address().port}`;
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function request(route,payload){
  const response=await fetch(base+route,{method:payload===undefined?'GET':'POST',headers:{Host:'127.0.0.1:5174',...(payload===undefined?{}:{Origin:'http://127.0.0.1:5173','Content-Type':'application/json'})},body:payload===undefined?undefined:JSON.stringify({payload}),signal:AbortSignal.timeout(120000)});
  assert.equal(response.status,200,`${route}: ${await (response.ok?Promise.resolve(''):response.text())}`);return response;
}
const api=async(route,payload)=>(await request('/engine/api'+route,payload)).json();
async function complete(job){
  for(let i=0;i<12000;i++){
    const value=await api(`/evidence/artifacts/job/${job.id}`),event=value.events.at(-1);
    if(['completed','failed','cancelled','interrupted'].includes(event.action)){
      assert.equal(event.action,'completed',JSON.stringify(event));assert.ok(event.body.artifact_kind);return event.body;
    }
    await sleep(50);
  }
  throw new Error('Timed out waiting for computation');
}
function distribution(values){const sorted=[...values].sort((a,b)=>a-b);return {samples:values.length,median_ms:sorted[Math.floor(sorted.length*.5)],p95_ms:sorted[Math.min(sorted.length-1,Math.floor(sorted.length*.95))],max_ms:sorted.at(-1)};}
async function timings(route,count){const times=[];for(let i=0;i<count;i++){const start=performance.now();await (await request(route)).text();times.push(performance.now()-start);}return distribution(times);}
function memory(){
  const result=spawnSync('powershell',['-NoProfile','-Command',`Get-Process -Id ${process.pid},${engine.child.pid},${engine.runtimePid} | Select-Object Id,ProcessName,WorkingSet64,PrivateMemorySize64 | ConvertTo-Json -Compress`],{encoding:'utf8',windowsHide:true});
  assert.equal(result.status,0,result.stderr);return JSON.parse(result.stdout);
}
async function stopEngine(){const child=engine.child;if(!child)return;const done=once(child,'exit');engine.stop();await done;}
try{
  assert.equal((await (await request('/flagship/status')).json()).engine.state,'idle');
  metrics.gateway_idle=await timings('/flagship/status',30);
  const start=performance.now();assert.equal((await api('/health')).liveOrderSubmission,false);metrics.engine_startup_ms=performance.now()-start;
  metrics.memory_engine_ready=memory();
  assert.equal((await fetch(engine.url+'/api/health')).status,403);
  assert.equal((await fetch(base+'/engine/api/health',{headers:{Host:'127.0.0.1:5174',Origin:'https://untrusted.example'}})).status,403);
  assert.equal((await fetch(base+'/orders',{method:'POST',headers:{Host:'127.0.0.1:5174',Origin:'http://127.0.0.1:5173','Content-Type':'application/json'},body:'{}'})).status,404);
  const catalog=await api('/evidence/catalog');let artifacts=0;const counts={};
  for(const kind of catalog.kinds){
    for(let offset=0;;offset+=100){const page=await api(`/evidence/artifacts/${kind}?limit=100&offset=${offset}`);counts[kind]=page.total;for(const item of page.items){const record=await api(`/evidence/artifacts/${kind}/${item.id}`);assert.equal(record.id,item.id);artifacts++;}if(offset+100>=page.total)break;}
  }
  const runs=await api('/research/runs');for(const run of runs.runs)assert.equal((await api('/research/runs/'+run.run_id)).run_id,run.run_id);
  metrics.migrated_inventory={records_read:artifacts,counts,regime_dashboard_runs_read:runs.runs.length};
  await stopEngine();
  process.env.Q_FLAGSHIP_DATA=path.join(out,'synthetic-data');
  await api('/health');
  const dataset=await complete(await api('/evidence/actions/load-bars',{source:'synthetic',interval:'1d',start:'2025-01-01',end:'2025-06-30',seed:9}));
  const comparison=await complete(await api('/evidence/actions/compare',{dataset_id:dataset.artifact_id,config:{lookback:2},a_start:'2025-01-01',a_end:'2025-03-31',b_start:'2025-04-01',b_end:'2025-06-30',acknowledge:true}));
  const mmStart=performance.now();const mm=await api('/evidence/actions/market-making',{events:20000,seed:13});
  const gatewayTimes=[],engineTimes=[];let done=false;
  const resultPromise=complete(mm).then(result=>{done=true;return result;});
  while(!done){
    let t=performance.now();await (await request('/flagship/status')).text();gatewayTimes.push(performance.now()-t);
    t=performance.now();await api('/health');engineTimes.push(performance.now()-t);await sleep(20);
  }
  const mmResult=await resultPromise;metrics.synthetic_mm_20000_ms=performance.now()-mmStart;
  metrics.gateway_during_mm=distribution(gatewayTimes);metrics.engine_health_during_mm=distribution(engineTimes);metrics.memory_after_mm=memory();
  for(const [name,result] of [['comparison',comparison],['market-making',mmResult]]){
    const response=await request(`/engine/api/evidence/artifacts/${result.artifact_kind}/${result.artifact_id}/export`);
    const file=path.join(out,name+'.zip');await writeFile(file,Buffer.from(await response.arrayBuffer()));
    const replay=spawnSync(engine.python,['-m','evidence.replay_lab',file],{cwd:engine.cwd,encoding:'utf8',windowsHide:true});
    assert.equal(replay.status,0,replay.stdout+replay.stderr);metrics[name+'_replay']=JSON.parse(replay.stdout);
  }
  metrics.engine_health_warm=await timings('/engine/api/health',30);
  const suiteStart=performance.now();const suite=await complete(await api('/evidence/actions/regime-suite',{acknowledge:true}));
  const suiteRecord=await api(`/evidence/artifacts/regime_suite/${suite.artifact_id}`);
  assert.equal(suiteRecord.artifact.strategy_count,14);assert.equal(suiteRecord.artifact.synthetic,true);
  metrics.regime_suite={elapsed_ms:performance.now()-suiteStart,strategy_count:suiteRecord.artifact.strategy_count};
  const suiteZip=await request(`/engine/api/evidence/artifacts/regime_suite/${suite.artifact_id}/export`);
  await writeFile(path.join(out,'regime-suite.zip'),Buffer.from(await suiteZip.arrayBuffer()));
  metrics.memory_after_regime_suite=memory();
  // Simulate abrupt owner disappearance: Windows closes the inherited stdin pipe.
  const orphan=engine.child;const exited=once(orphan,'exit');const shutdown=performance.now();orphan.stdin.end();
  await Promise.race([exited,sleep(10000).then(()=>{throw new Error('Orphan research process survived owner EOF');})]);
  metrics.owner_eof_shutdown_ms=performance.now()-shutdown;
  assert.equal(engine.status().state,'idle');await api('/health');assert.equal(engine.status().state,'ready');
  metrics.restart_verified=true;
  await writeFile(path.join(out,'measurements.json'),JSON.stringify(metrics,null,2));
  console.log(JSON.stringify({output:out,...metrics},null,2));
}finally{await stopEngine();gateway.closeAllConnections();await new Promise(resolve=>gateway.close(resolve));}
