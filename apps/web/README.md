# Q web interface

React/TypeScript terminal for Q's research, validation and portfolio workflows. See the [root README](../../README.md) for the research methodology, full setup and operational limits.

## Development

Use Node.js 24+ and npm. From this directory:

```sh
npm run install:ci
npm run dev
```

The web preview listens at `http://127.0.0.1:5173`. Integrated research requires the loopback gateway; use `../../start-q21.ps1` from the repository root to start both services. The Vite proxy routes `/integrations` to `127.0.0.1:5174`.

## Structure

- `app/`: application entry, theme and HTTP routes.
- `components/`: terminal views and the UI primitives they use.
- `lib/quant.ts`: daily research backtesting and indicators.
- `lib/paper.ts`: separate local account-simulation rules; manual paper fills remain disabled in the terminal.
- `lib/flagship/`: typed contracts for integrated research workflows.
- `hooks/`: market-data and integration state.
- `tests/`: deterministic quant and research-view contract tests.

## Validation

```sh
node --test tests/*.test.mjs
npx tsc --noEmit --incremental false
npm run build
```

## Hosting configuration

Preserve `.openai/hosting.json`, `build/sites-vite-plugin.ts`, its license, and the Sites plugin in `vite.config.ts`. The build emits a Cloudflare Worker artifact through Vinext. `npm start` previews that artifact locally; it does not deploy it or provision the gateway/Python engine.

The hosting manifest currently enables neither D1 nor R2. Optional binding helpers and Drizzle configuration remain available for that hosting contract. Local `.wrangler/`, `.sites-runtime/`, `.vinext/` and build output are generated and ignored. The bundled authentication helper is separate from broker authentication and research-provider credentials.
