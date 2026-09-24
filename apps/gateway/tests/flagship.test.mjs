import test from 'node:test';
import assert from 'node:assert/strict';
import {QuantPool} from '../quant-pool.mjs';
import {EngineBridge} from '../engine.mjs';
import {backtest,starterStrategies} from '../../web/lib/quant.ts';
import {barsFor} from '../../web/tests/fixtures.mjs';

test('worker preserves every numerical output of all Q templates',async()=>{
  const pool=new QuantPool();
  try{for(const strategy of starterStrategies){const bars=barsFor(strategy.symbol);const expected=backtest(strategy,bars,'fixture-version');const actual=await pool.run(strategy,bars,'fixture-version');delete expected.createdAt;delete actual.createdAt;assert.deepEqual(actual,expected);}}
  finally{pool.close();}
});
test('bounded worker admission rejects overflow without changing accepted work',async()=>{
  const pool=new QuantPool();
  try{const s=starterStrategies[0],bars=barsFor(s.symbol,3000);const pending=[pool.run(s,bars,'a'),pool.run(s,bars,'b'),pool.run(s,bars,'c')];await assert.rejects(pool.run(s,bars,'overflow'),/queued/);const results=await Promise.all(pending);assert.deepEqual(results.map(r=>r.dataVersion),['a','b','c']);}
  finally{pool.close();}
});
test('the Python engine is idle until requested and fails clearly when unconfigured',async()=>{
  const engine=new EngineBridge({python:'C:/missing-q-test-python.exe'});
  assert.equal(engine.child,null);assert.equal(engine.status().state,'idle');
  await assert.rejects(engine.start(),/setup-flagship/);assert.equal(engine.child,null);
});
