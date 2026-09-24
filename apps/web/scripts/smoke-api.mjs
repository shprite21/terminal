import assert from 'node:assert/strict';
const base=process.argv[2]||'http://127.0.0.1:5173';
const health=await (await fetch(base+'/api/health')).json();
assert.equal(health.mode,'real-data-research');
const response=await fetch(base+'/api/markets'),market=await response.json();
assert.equal(response.status,200);assert.ok(market.instruments.length>0);
assert.equal(market.synthetic,undefined);assert.ok(market.instruments.every(i=>i.price===undefined));
const headers={'Content-Type':'application/json',Origin:base};
const strategy={id:'smoke',name:'API smoke test',kind:'SMA crossover',symbol:'NVDA',lookback:20,slow:50,capital:100000,costBps:10,allocation:.95,version:1};
const invalid=await fetch(base+'/api/backtests',{method:'POST',headers,body:JSON.stringify({...strategy,capital:-1})});assert.equal(invalid.status,400);
const mismatch=await fetch(base+'/integrations/backtests',{method:'POST',headers,body:JSON.stringify({strategy,datasetId:'not-a-dataset'})});assert.equal(mismatch.status,400);
const noOrigin=await fetch(base+'/integrations/market/import',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});assert.equal(noOrigin.status,403);
const status=await (await fetch(base+'/integrations/status')).json();
if(!status.massive?.configured){
  const unavailable=await fetch(base+'/integrations/market/history?symbol=NVDA'),data=await unavailable.json();
  // A previously saved real dataset is permissible after disconnect; never fabricate a new one.
  if(unavailable.ok){assert.ok(data.source.startsWith('Massive'));assert.ok(data.cached);}
  else{assert.equal(unavailable.status,400);assert.match(data.error,/Connect Massive/);}
}
console.log(JSON.stringify({checked:'Real-data routes, catalogue, rejected inputs, same-origin mutations, missing-key behavior',instruments:market.instruments.length,sources:market.sources,massive:status.massive?.state}));
