// Offline integration: real local bridge and Python, explicit generated fixtures only.
import test from 'node:test';
import assert from 'node:assert/strict';
import {once} from 'node:events';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {MarketDataService} from '../market-data.mjs';
import {EngineBridge} from '../engine.mjs';
import {createGateway} from '../server.mjs';

test('source choice survives gateway, engine, backtest and portfolio boundaries',{timeout:90000},async()=>{
  const root=await mkdtemp(path.join(tmpdir(),'q21-provider-test-'));
  const previous=process.env.Q_FLAGSHIP_DATA;process.env.Q_FLAGSHIP_DATA=root;
  const engine=new EngineBridge();
  const market=new MarketDataService({root:path.join(root,'market')});
  market.resolve=async symbol=>({symbol,name:'TEST FIXTURE',market:'US',currency:'USD',exchange:'TEST',type:'EQUITY',sector:'TEST'});
  let generated;
  market.massive={history:async instrument=>({...generated,instrument,source:'Massive · TEST FIXTURE',synthetic:false}),status:()=>({connected:false})};
  const gateway=createGateway({engine,market,codex:{stop(){}}});
  gateway.listen(0,'127.0.0.1');await once(gateway,'listening');
  const base=`http://127.0.0.1:${gateway.address().port}`;
  async function request(route,body){
    const response=await fetch(base+route,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json',Origin:'http://127.0.0.1:5173'}:{},body:body?JSON.stringify(body):undefined});
    const result=await response.json();assert.equal(response.status,200,JSON.stringify(result));return result;
  }
  try{
    assert.equal((await fetch(base+'/internal/market-history?symbol=AAPL')).status,403);
    generated=await request('/market/history?symbol=AAPL&source=synthetic');
    assert.equal(generated.synthetic,true);assert.match(generated.source,/SYNTHETIC/);assert.equal(generated.seed,42);
    assert.equal((await request('/market/history?symbol=AAPL&source=synthetic')).id,generated.id);
    const result=await request('/backtests',{source:'synthetic',datasetId:generated.id,strategy:{id:'fixture',name:'SYNTHETIC TEST',kind:'Time-series momentum',symbol:'AAPL',lookback:10,slow:20,capital:10000,costBps:10,allocation:.5,version:1}});
    assert.equal(result.dataVersion,generated.id);assert.match(result.source,/SYNTHETIC/);
    const catalog=await request('/engine/api/evidence/catalog');assert.ok(catalog.quant['history-download']);
    const replay=await request('/engine/api/portfolio/analyze',{source:'massive',period:'1y',holdings:[{ticker:'AAPL',weight:100}],benchmark:'AAPL'});
    assert.match(replay.source,/Massive/);assert.equal(replay.synthetic,false);assert.ok(Math.abs(replay.metrics.excess_return)<1e-12);
    assert.ok(replay.observations>22);
    assert.equal((await fetch(engine.url+'/api/research/market-history?symbol=AAPL&source=synthetic')).status,403);
  }finally{
    const child=engine.child,finished=child?once(child,'exit'):Promise.resolve();
    await new Promise(resolve=>gateway.close(resolve));await finished;
    if(previous===undefined)delete process.env.Q_FLAGSHIP_DATA;else process.env.Q_FLAGSHIP_DATA=previous;
    if(path.dirname(root)!==path.resolve(tmpdir())||!path.basename(root).startsWith('q21-provider-test-'))throw new Error('Unexpected test cleanup path.');
    await rm(root,{recursive:true,force:true});
  }
});
