// Real local gateway -> authenticated Python -> existing research -> 18 layers.
// All data is an explicitly labeled seeded fixture; no network market provider.
import test from 'node:test';
import assert from 'node:assert/strict';
import { once } from 'node:events';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { EngineBridge } from '../engine.mjs';
import { createGateway } from '../server.mjs';

test('Survival API runs all layers through the Q gateway and retains failed gates', { timeout: 120000 }, async () => {
  const root = await mkdtemp(path.join(tmpdir(), 'q-survival-runtime-'));
  const previous = process.env.Q_FLAGSHIP_DATA;
  process.env.Q_FLAGSHIP_DATA = root;
  const engine = new EngineBridge();
  const gateway = createGateway({ engine, codex: { stop() {} } });
  gateway.listen(0, '127.0.0.1');
  await once(gateway, 'listening');
  const base = `http://127.0.0.1:${gateway.address().port}/engine/api/research`;
  async function request(route, body, expected = 200) {
    const response = await fetch(base + route, {
      method: body === undefined ? 'GET' : 'POST',
      headers: body === undefined ? {} : { 'Content-Type': 'application/json', Origin: 'http://127.0.0.1:5173' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const result = await response.json();
    assert.equal(response.status, expected, JSON.stringify(result));
    return result;
  }
  async function completed(route) {
    for (let attempt = 0; attempt < 800; attempt++) {
      const value = await request(route);
      if (value.status === 'completed') return value;
      assert.notEqual(value.status, 'failed', JSON.stringify(value));
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    throw new Error('Local validation did not complete');
  }
  try {
    assert.equal((await request('/survival/catalog')).layers.length, 18);
    const research = await request('/runs', {
      name: 'SYNTHETIC survival gateway fixture', hypothesis: 'Deterministic workflow coverage, not market performance.',
      data_mode: 'demo', symbols: ['AAPL', 'MSFT'],
      sleeves: [{ strategy: 'time_series_momentum', lookback: 20, budget: 100 }], train_window: 126,
    }, 202);
    const original = await completed(`/runs/${research.run_id}`);
    const payload = { experiment_id: research.run_id, config: { bootstrap_samples: 100, max_folds: 2, max_universe_subsets: 1,
      gates: [{ layer: 2, metric: 'test_sharpe', operator: '>=', threshold: 1000, severity: 'FAIL' }] } };
    const queued = await request('/survival/runs', payload, 202);
    const validation = await completed(`/survival/runs/${queued.id}`);
    assert.equal(validation.result.layers.length, 18);
    assert.equal(validation.result.summary.status, 'FAIL');
    assert.equal(validation.result.summary.live_eligible, false);
    assert.equal(validation.result.synthetic, true);
    assert.equal(validation.result.layers[17].status, 'N-A');
    assert.equal((await request('/survival/runs', payload, 202)).id, queued.id);
    assert.deepEqual((await request(`/runs/${research.run_id}`)).result, original.result);
    const book = await request(`/survival/runs?experiment_id=${research.run_id}`);
    assert.equal(book.runs[0].summary.counts.FAIL, 1);
    const paper = await request('/survival/paper', { experiment_id: research.run_id, initial_nav: 10000 }, 201);
    const rejected = await request(`/survival/paper/${paper.id}/events`, { kind: 'signal', observed_at: '2020-01-01T00:00:00Z' }, 422);
    assert.match(rejected.detail, /advance strictly/);
    const exported = await fetch(base + `/survival/runs/${queued.id}/export`);
    assert.equal(exported.status, 200);
    assert.equal(exported.headers.get('content-type'), 'application/zip');
    assert.ok((await exported.arrayBuffer()).byteLength > 1000);
  } finally {
    const child = engine.child;
    const exited = child ? once(child, 'exit') : Promise.resolve();
    await new Promise(resolve => gateway.close(resolve));
    await exited;
    if (previous === undefined) delete process.env.Q_FLAGSHIP_DATA;
    else process.env.Q_FLAGSHIP_DATA = previous;
    if (path.dirname(root) !== path.resolve(tmpdir()) || !path.basename(root).startsWith('q-survival-runtime-')) throw new Error('Unexpected cleanup target');
    await rm(root, { recursive: true, force: true });
  }
});
