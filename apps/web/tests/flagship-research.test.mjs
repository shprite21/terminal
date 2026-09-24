import assert from 'node:assert/strict';
import test from 'node:test';
import { comparableRuns, defaults, num, pct, researchApi, validateResearch } from '../lib/flagship/research.ts';

test('research supports explicit providers and enforces the Massive history window',()=>{
  for(const data_mode of ['yahoo','massive','synthetic','demo'])assert.equal(validateResearch({...defaults,data_mode,period:'2y'}).data_mode,data_mode);
  assert.throws(()=>validateResearch({...defaults,data_mode:'massive',period:'5y'}),/two years/);
});

test('valid mandate preserves execution and strategy settings', () => {
  const result = validateResearch({ ...defaults, symbols: [' aapl ', ' msft '], benchmark: 'spy' });
  assert.deepEqual(result.symbols, ['AAPL', 'MSFT']);
  assert.equal(result.benchmark, 'SPY');
  assert.equal(result.commission_bps, defaults.commission_bps);
  assert.equal(result.sleeves.length, 2);
});
const invalidCases = /** @type {[string, object][]} */ ([
  ['duplicate ticker', { symbols: ['AAA', 'aaa'] }],
  ['no hypothesis', { hypothesis: ' ' }],
  ['invalid cost', { commission_bps: NaN }],
  ['invalid budget', { sleeves: [{ strategy: 'mean_reversion', lookback: 20, budget: 10 }] }],
  ['unknown strategy', { sleeves: [{ strategy: 'earnings', lookback: 20, budget: 100 }] }],
  ['history too short', { train_window: 126 }],
  ['invalid net limit', { max_gross_exposure: 0.5, max_net_exposure: 1 }],
  ['snapshot path', { snapshot_run_id: '../elsewhere' }],
]);
for (const [name, changes] of invalidCases) {
  test(`rejects ${name}`, () => assert.throws(() => validateResearch({ ...defaults, ...changes })));
}
test('comparison requires identical data and evaluation protocol', () => {
  const run = { request: defaults, snapshot_sha256: 'abc', evaluation_start: '2020-01-01', end_date: '2024-01-01' };
  assert.equal(comparableRuns([run, structuredClone(run)]), true);
  assert.equal(comparableRuns([run, { ...run, snapshot_sha256: 'def' }]), false);
  assert.equal(comparableRuns([run, { ...run, request: { ...defaults, train_window: 504 } }]), false);
  assert.equal(comparableRuns([run, { ...run, evaluation_start: '2021-01-01' }]), false);
});
test('missing and non-finite values do not masquerade as zero', () => {
  assert.equal(pct(null), '—'); assert.equal(num(NaN), '—'); assert.equal(pct(0), '0.00%');
});
test('API exposes validation errors instead of manufacturing data', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: [{ loc: ['body', 'symbols'], msg: 'Invalid universe' }] }), { status: 422 });
  try { await assert.rejects(() => researchApi('/runs', defaults), /symbols: Invalid universe/); }
  finally { globalThis.fetch = original; }
});
test('unreachable API gives reconnect instructions', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => { throw new Error('network'); };
  try { await assert.rejects(() => researchApi('/runs'), /Reconnect/); }
  finally { globalThis.fetch = original; }
});
