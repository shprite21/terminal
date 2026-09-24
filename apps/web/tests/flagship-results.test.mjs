import test from 'node:test';
import assert from 'node:assert/strict';
import {normalizedPeriods,drawdownRows,chartRows,candleTimestamp,chartAxis,useGenericEquityCharts} from '../lib/flagship/evidence-results.ts';
import {mergeSaved,starter} from '../lib/flagship/portfolio.ts';

test('candle labels convert explicit offsets to UTC without guessing unzoned source times',()=>{
  assert.equal(candleTimestamp('2025-01-01T09:15:00+05:30'),'2025-01-01 03:45:00 UTC');
  assert.equal(candleTimestamp('2025-01-01T00:15:00+05:30'),'2024-12-31 18:45:00 UTC');
  assert.equal(candleTimestamp('2025-01-01T03:45:00Z'),'2025-01-01 03:45:00 UTC');
  assert.equal(candleTimestamp('2025-01-01'),'2025-01-01 (source time)');
  assert.equal(candleTimestamp('invalid'),'invalid (source time)');
});

test('elapsed comparisons use each frozen starting cash and leave shorter periods absent',()=>{
  assert.deepEqual(normalizedPeriods({A:{configuration:{initial_cash:100},equity:[{equity:90},{equity:110}]},B:{configuration:{initial_cash:200},equity:[{equity:220}]}}),[{elapsed_bar:0,A:90,B:110.00000000000001},{elapsed_bar:1,A:110.00000000000001}]);
});
test('drawdown includes initial capital, recovers at new peak, and retains source rows',()=>{
  const source=[{equity:90},{equity:100},{equity:120},{equity:60}];
  const actual=drawdownRows(source,100).map(r=>r.drawdown_percent);
  assert.ok(Math.abs(actual[0]+10)<1e-12);assert.deepEqual(actual.slice(1),[0,0,-50]);assert.equal(source[0].drawdown_percent,undefined);
});

test('saved strategy charts retain date axes and do not fabricate single-account drawdowns',()=>{
  const basket=[{date:'2020-01-02',baseline:100,optimized:102},{date:'2020-01-03',baseline:98,optimized:101}];
  assert.equal(chartAxis(basket),'date');
  assert.equal(useGenericEquityCharts({},basket),false);
  const account=[{date:'2020-01-02',equity:100},{date:'2020-01-03',equity:95}];
  assert.equal(useGenericEquityCharts({},account),true);
  assert.equal(useGenericEquityCharts({charts:[{table:'comparison_equity'}]},account),false);
  assert.equal(useGenericEquityCharts({},[{equity:NaN}]),false);
  assert.equal(chartAxis([{step:0,median:100}]),'step');
  assert.equal(chartAxis([{point:0,annual_volatility:.2}],'annual_volatility'),'annual_volatility');
});
test('chart sampling retains both series extrema and endpoint chronology',()=>{
  const rows=Array.from({length:20000},(_,i)=>({i,a:0,b:0}));rows[3001].a=-999;rows[15000].b=888;
  const sampled=chartRows(rows,['a','b']);assert.ok(sampled.length<=1200);assert.equal(sampled[0],rows[0]);assert.equal(sampled.at(-1),rows.at(-1));assert.ok(sampled.includes(rows[3001]));assert.ok(sampled.includes(rows[15000]));assert.ok(sampled.every((r,i)=>!i||r.i>sampled[i-1].i));
});
test('portfolio transfer preserves same-name snapshots and rejects excess atomically',()=>{
  const existing=[structuredClone(starter)],changed={...starter,initial_capital:200};
  const result=mergeSaved(existing,[starter,changed]);assert.equal(result.length,2);assert.equal(result[0].initial_capital,starter.initial_capital);assert.match(result[1].name,/import 1/);assert.equal(existing.length,1);
  assert.throws(()=>mergeSaved(Array.from({length:50},(_,i)=>({...starter,name:String(i)})),[starter]),/exceed/);
});
