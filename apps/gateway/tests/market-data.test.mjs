import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {MarketDataService,parseCatalogue,parseHistoryCsv} from '../market-data.mjs';
import {MassiveAdapter,parseMassive} from '../massive.mjs';

// Small invented fixtures below are parser/accounting test inputs only, never app data.
const instrument={symbol:'NVDA',name:'NVIDIA',market:'US',exchange:'NASDAQ',currency:'USD',type:'Listed security',sector:'Not supplied'};
const now=Date.parse('2026-09-10T12:00:00Z');
const aggregate={status:'OK',ticker:'NVDA',adjusted:false,results:[
  {t:Date.parse('2026-09-04T04:00:00Z'),o:100,h:102,l:99,c:100,v:10},
  {t:Date.parse('2026-09-08T04:00:00Z'),o:50,h:52,l:49,c:51,v:20},
  {t:Date.parse('2026-09-09T04:00:00Z'),o:51,h:53,l:50,c:52,v:30},
  {t:Date.parse('2026-09-10T04:00:00Z'),o:52,h:54,l:51,c:53,v:40},
]};
const csv='date,open,high,low,close,volume\n2026-09-04,10,12,9,11,100\n2026-09-08,11,13,10,12,110\n2026-09-09,12,14,11,13,120';
test('official directory parsers preserve quoted names, exchange suffixes and exclude test symbols',()=>{
  const n=parseCatalogue('Symbol|Security Name|Test Issue|ETF\nNVDA|NVIDIA|N|N\nTEST|Test security|Y|N\nQQQ|QQQ Fund|N|Y',{market:'US',delimiter:'|',type:'Equity'});
  assert.equal(n.length,2);assert.equal(n[1].type,'ETF');
  const i=parseCatalogue('SYMBOL,NAME_OF_COMPANY,ISIN_NUMBER\nABC,"Company, Limited",INE123',{market:'IN',type:'SME'});
  assert.equal(i[0].symbol,'ABC.NS');assert.equal(i[0].name,'Company, Limited');assert.equal(i[0].isin,'INE123');
  assert.equal(parseCatalogue('Symbol,SecurityName,ISINNumber\nNIFTYBEES,Nifty ETF,INF123',{market:'IN',type:'ETF'})[0].type,'ETF');
});
test('Massive raw history excludes current ET date and applies splits only to chart history',()=>{
  const d=parseMassive(aggregate,[{ticker:'NVDA',execution_date:'2026-09-08',split_from:1,split_to:2}],[{ticker:'NVDA',ex_dividend_date:'2026-09-09',currency:'USD',cash_amount:1}],instrument,now);
  assert.equal(d.bars.length,3);assert.equal(d.asOf,'2026-09-09');assert.equal(d.bars[0].close,100);assert.equal(d.chartBars[0].close,50);assert.equal(d.bars[1].splitRatio,2);assert.equal(d.bars[2].dividend,1);assert.equal(d.chartBars[0].volume,20);
});
test('Massive rejects ticker mismatch, adjusted execution prices, missing values, and unaligned actions',()=>{
  assert.throws(()=>parseMassive({...aggregate,ticker:'AAPL'},[],[],instrument,now),/matching/);
  assert.throws(()=>parseMassive({...aggregate,adjusted:true},[],[],instrument,now),/unadjusted/);
  assert.throws(()=>parseMassive({...aggregate,results:aggregate.results.map((r,i)=>i===0?{...r,o:null}:r)},[],[],instrument,now),/valid/);
  assert.throws(()=>parseMassive(aggregate,[{ticker:'NVDA',execution_date:'2026-09-07',split_from:1,split_to:2}],[],instrument,now),/matching daily bar/);
});
test('CSV validation rejects blank cells, future/current bars, duplicate dates, and malformed data',()=>{
  assert.equal(parseHistoryCsv(csv,instrument,'User export',now).bars.length,3);
  for(const content of [csv.replace(',10,12',',,12'),csv.replace('2026-09-09','2026-09-10'),csv.replace('2026-09-09','2026-09-08'),csv.replace(',120',',nope')])assert.throws(()=>parseHistoryCsv(content,instrument,'User export',now));
});
test('missing Massive key and unsupported NSE never produce fallback prices',async()=>{
  let calls=0;const adapter=new MassiveAdapter({apiKey:'',request:async()=>{calls++;throw Error('Should not fetch');}});
  await assert.rejects(adapter.history(instrument),/Connect Massive/);
  await assert.rejects(adapter.history({...instrument,market:'IN'}),/US stocks only/);assert.equal(calls,0);assert.equal(adapter.status().connected,false);
});
test('Massive authentication uses headers, redacts errors, and refuses credential redirects',async()=>{
  const key='test_secret_123';let seen;
  const a=new MassiveAdapter({apiKey:key,request:async(url,options)=>{seen={url:String(url),options};return new Response(JSON.stringify({status:'OK',results:[]}),{status:200});}});
  await a.get('/v3/reference/tickers?limit=1');assert.equal(seen.options.headers.Authorization,'Bearer '+key);assert.ok(!seen.url.includes(key));assert.equal(seen.options.redirect,'error');
  await assert.rejects(a.get('https://attacker.example/v3/reference/tickers'),/Unexpected/);
  const b=new MassiveAdapter({apiKey:key,request:async()=>new Response(key,{status:401})});
  await assert.rejects(b.get('/v3/reference/tickers'),e=>!e.message.includes(key)&&/rejected/.test(e.message));assert.equal(b.status().connected,false);
});
test('Massive paginates completely and rejects a partial successful response',async()=>{
  const a=new MassiveAdapter({apiKey:'test_key',now:()=>now,sleep:async()=>{},request:async url=>new Response(JSON.stringify({status:'OK',results:[String(url).includes('cursor')?2:1],...(String(url).includes('cursor')?{}:{next_url:'https://api.massive.com/stocks/v1/splits?cursor=two'})}))});
  assert.deepEqual((await a.pages('/stocks/v1/splits')).results,[1,2]);
  const b=new MassiveAdapter({apiKey:'test_key',request:async()=>new Response(JSON.stringify({status:'OK'}))});await assert.rejects(b.pages('/stocks/v1/splits'),/missing/);
});
test('API pacing reserves slots before dispatching concurrent requests',async()=>{
  const waits=[];const a=new MassiveAdapter({apiKey:'test_key',now:()=>now,sleep:async n=>waits.push(n),request:async()=>new Response(JSON.stringify({status:'OK',results:[]}))});
  await Promise.all([a.get('/stocks/v1/splits'),a.get('/stocks/v1/dividends'),a.get('/v3/reference/tickers')]);assert.deepEqual(waits,[12500,25000]);
});
test('immutable snapshots survive restart, changed bars get new versions, and symbol mismatches fail',async()=>{
  const root=await mkdtemp(path.join(tmpdir(),'q21-data-test-'));
  try{
    const service=new MarketDataService({root,now:()=>now});const data=parseHistoryCsv(csv,instrument,'User export',now),first=await service.saveDataset(data);
    const same=await service.saveDataset({...data,fetchedAt:new Date(now+1000).toISOString()});assert.equal(first.id,same.id);assert.equal(first.fetchedAt,same.fetchedAt);
    const second=await service.saveDataset({...data,bars:data.bars.map((b,i)=>i===0?{...b,volume:101}:b)});assert.notEqual(first.id,second.id);
    const restarted=new MarketDataService({root});assert.deepEqual((await restarted.read('dataset-'+first.id)).bars,JSON.parse(JSON.stringify(data.bars)));
    await assert.rejects(service.run({strategy:{id:'x',name:'Test',kind:'Time-series momentum',symbol:'AAPL',lookback:2,slow:4,capital:1000,costBps:0,allocation:1,version:1},datasetId:first.id}),/does not match/);
    await assert.rejects(service.run({strategy:{id:'x',name:'Test',kind:'Time-series momentum',symbol:'NVDA',lookback:2,slow:4,capital:1000,costBps:0,allocation:1,version:1},datasetId:'../../secrets'}),/Invalid dataset/);
  }finally{if(path.dirname(root)!==path.resolve(tmpdir())||!path.basename(root).startsWith('q21-data-test-'))throw new Error('Unexpected test cleanup path.');await rm(root,{recursive:true,force:true});}
});

test('provider cache keys isolate concurrent requests and never substitute CSV or synthetic',async()=>{
  const root=await mkdtemp(path.join(tmpdir(),'q21-data-test-'));
  try{
    const service=new MarketDataService({root,now:()=>now,massive:{history:async()=>{throw Error('Massive offline fixture');}}});
    service.resolve=async()=>instrument;
    let calls=0;
    service.alternateHistory=async(symbol,source)=>{calls++;const data=parseHistoryCsv(csv,instrument,'fixture',now);return {...data,currency:'USD',source:source==='synthetic'?'SYNTHETIC · test fixture':'Yahoo · test fixture'};};
    const [synthetic,yahoo]=await Promise.all([service.history('NVDA',false,'synthetic'),service.history('NVDA',false,'yahoo')]);
    assert.notEqual(synthetic.id,yahoo.id);assert.equal(synthetic.synthetic,true);assert.equal(yahoo.synthetic,false);
    assert.equal((await service.history('NVDA',false,'synthetic')).id,synthetic.id);assert.equal(calls,2);
    await service.importCsv({symbol:'NVDA',csv,source:'Fixture import',unadjustedConfirmed:true});
    await assert.rejects(service.history('NVDA',false,'massive'),/Massive offline/);
    const imported=await service.history('NVDA',false,'csv');assert.match(imported.source,/^CSV/);
    service.alternateHistory=async()=>{throw Error('Yahoo offline fixture');};
    const cached=await service.history('NVDA',true,'yahoo');assert.equal(cached.id,yahoo.id);assert.equal(cached.stale,true);
    assert.equal((await service.read('dataset-'+synthetic.id)).synthetic,true);
  }finally{if(path.dirname(root)!==path.resolve(tmpdir())||!path.basename(root).startsWith('q21-data-test-'))throw new Error('Unexpected test cleanup path.');await rm(root,{recursive:true,force:true});}
});
