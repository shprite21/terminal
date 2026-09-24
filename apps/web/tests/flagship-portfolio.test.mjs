import assert from 'node:assert/strict';
import test from 'node:test';
import {
  equalWeights,
  equityCsv,
  parsePortfolio,
  readSaved,
  loadSaved,
  storageKey,
  legacyStorageKey,
  starter,
} from '../lib/flagship/portfolio.ts';

test('provider choices round-trip without relabeling legacy portfolios',()=>{
  for(const source of ['yahoo','massive','synthetic'])assert.equal(readSaved(JSON.stringify([{...starter,source}]))[0].source,source);
  assert.equal(Object.hasOwn(parsePortfolio(starter),'source'),false);
  assert.throws(()=>parsePortfolio({...starter,source:'unknown'}));
});

test('valid draft normalizes ticker case and whitespace', () => {
  const result = parsePortfolio({
    ...starter,
    benchmark: ' spy ',
    holdings: [{ ticker: ' aapl ', weight: 100 }],
  });
  assert.equal(result.holdings[0].ticker, 'AAPL');
  assert.equal(result.benchmark, 'SPY');
});

test('all invalid allocation shapes are rejected', () => {
  for (const holdings of [
    [],
    [{ ticker: 'AAPL', weight: 99 }],
    [{ ticker: 'AAPL', weight: NaN }],
    [
      { ticker: 'AAPL', weight: -1 },
      { ticker: 'MSFT', weight: 101 },
    ],
    [
      { ticker: 'AAPL', weight: 50 },
      { ticker: 'aapl', weight: 50 },
    ],
    [{ ticker: '=BAD', weight: 100 }],
  ]) {
    assert.throws(() => parsePortfolio({ ...starter, holdings }));
  }
});

test('invalid research settings and names are rejected', () => {
  for (const patch of [
    { name: '' },
    { period: 'max' },
    { initial_capital: Infinity },
    { risk_free_rate: -1 },
    { benchmark: 'bad ticker' },
  ])
    assert.throws(() => parsePortfolio({ ...starter, ...patch }));
});

test('equal weights total exactly 100 for 1 to 30 holdings', () => {
  for (let count = 1; count <= 30; count++) {
    const holdings = equalWeights(
      Array.from({ length: count }, (_, i) => ({ ticker: 'S' + i, weight: 0 })),
    );
    assert.equal(
      parsePortfolio({ ...starter, holdings }).holdings.length,
      count,
    );
  }
  assert.deepEqual(equalWeights([]), []);
});

test('saved portfolios round-trip with validation', () => {
  assert.deepEqual(readSaved(JSON.stringify([starter])), [starter]);
  assert.deepEqual(readSaved(null), []);
  assert.throws(() => readSaved('{broken'));
  assert.throws(() => readSaved(JSON.stringify([starter, starter])));
  assert.throws(() =>
    readSaved(JSON.stringify([{ ...starter, holdings: [] }])),
  );
});

test('CSV exports the exact analyzed curve, including the initial point', () => {
  const csv = equityCsv({
    equity_curve: [
      { date: '2024-01-02', portfolio: 1000, benchmark: 1000, drawdown: 0 },
      { date: '2024-01-03', portfolio: 900, benchmark: 950, drawdown: -0.1 },
    ],
  });
  assert.equal(
    csv,
    'date,portfolio_value,benchmark_value,drawdown\n2024-01-02,1000,1000,0\n2024-01-03,900,950,-0.1',
  );
});

test('Shprite reads portfolios saved under the previous brand without deleting them', () => {
  const entries = new Map([[legacyStorageKey, JSON.stringify([starter])]]);
  const storage = { getItem: (key) => entries.get(key) ?? null };
  assert.equal(storageKey, 'shprite.portfolios.v1');
  assert.deepEqual(loadSaved(storage), [starter]);
  assert.equal(entries.size, 1);
  assert.ok(entries.has(legacyStorageKey));
});

test('new-brand snapshots take precedence without reviving deleted or corrupted data', () => {
  const current = { ...starter, name: 'Current portfolio' };
  const entries = new Map([
    [legacyStorageKey, JSON.stringify([starter])],
    [storageKey, JSON.stringify([current])],
  ]);
  const storage = { getItem: (key) => entries.get(key) ?? null };
  assert.deepEqual(loadSaved(storage), [current]);
  entries.set(storageKey, '[]');
  assert.deepEqual(loadSaved(storage), []);
  entries.set(storageKey, '{broken');
  assert.throws(() => loadSaved(storage));
});
