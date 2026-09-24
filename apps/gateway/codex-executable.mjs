import { statSync, readdirSync } from 'node:fs';
import path from 'node:path';

const isFile = file => { try { return statSync(file).isFile(); } catch { return false; } };

// Desktop launches do not necessarily inherit Codex's session-specific PATH.
// Resolve again on reconnect because desktop updates rotate the bin directory.
export function resolveCodexExecutable({ env = process.env, platform = process.platform } = {}) {
  if (env.Q21_CODEX_PATH) return env.Q21_CODEX_PATH;
  if (platform !== 'win32') return 'codex';
  const searchPath = Object.entries(env).find(([key]) => key.toLowerCase() === 'path')?.[1] || '';
  for (const directory of searchPath.split(';').filter(Boolean)) {
    const candidate = path.join(directory.replace(/^"|"$/g, ''), 'codex.exe');
    if (isFile(candidate)) return candidate;
  }
  const localAppData = env.LOCALAPPDATA || (env.USERPROFILE && path.join(env.USERPROFILE, 'AppData', 'Local'));
  if (localAppData) {
    const bin = path.join(localAppData, 'OpenAI', 'Codex', 'bin');
    try {
      const candidates = readdirSync(bin, { withFileTypes: true })
        .filter(entry => entry.isDirectory())
        .map(entry => path.join(bin, entry.name, 'codex.exe'))
        .filter(isFile)
        .sort((a, b) => statSync(b).mtimeMs - statSync(a).mtimeMs);
      if (candidates.length) return candidates[0];
    } catch { /* Fall through to the normal executable-not-found diagnostic. */ }
  }
  return 'codex';
}
