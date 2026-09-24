import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, utimesSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { resolveCodexExecutable } from '../codex-executable.mjs';
import { CodexGateway } from '../codex.mjs';

test('Windows desktop launch resolves Codex without a session PATH and survives updates', t => {
  const root = mkdtempSync(path.join(tmpdir(), 'q-codex-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const executable = version => {
    const file = path.join(root, 'OpenAI', 'Codex', 'bin', version, 'codex.exe');
    mkdirSync(path.dirname(file), { recursive: true });
    writeFileSync(file, 'fixture');
    return file;
  };
  const old = executable('old');
  utimesSync(old, 1, 1);
  const options = { platform: 'win32', env: { LOCALAPPDATA: root } };
  assert.equal(resolveCodexExecutable(options), old);
  const current = executable('current');
  assert.equal(resolveCodexExecutable(options), current);
  assert.equal(resolveCodexExecutable({ ...options, env: { ...options.env, Path: path.dirname(old) } }), old);
  assert.equal(resolveCodexExecutable({ ...options, env: { Q21_CODEX_PATH: 'explicit.exe' } }), 'explicit.exe');
});

test('missing executable produces actionable status and can be retried', async () => {
  const gateway = new CodexGateway({ executable: path.join(tmpdir(), 'q-nonexistent-codex', 'codex.exe') });
  for (let attempt = 0; attempt < 2; attempt++) {
    const status = await gateway.status();
    assert.equal(status.state, 'unavailable');
    assert.match(status.message, /Q21_CODEX_PATH/);
  }
  gateway.stop();
});
