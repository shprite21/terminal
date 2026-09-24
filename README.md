# Q

**Q is our single quantitative research and trading system going forward.** All future development belongs in this checkout, with research, validation, portfolio analysis and connections integrated as modules of Q. Display name: **Q**. Technical namespace: `q21`.

## Run locally

Use Node.js 24+ (the local gateway imports TypeScript through Node's built-in type stripping) and the existing installed web dependencies.

```powershell
./start-q21.ps1
```

This starts the web app at http://127.0.0.1:5173 and the loopback integration gateway. For a fresh install, run `npm run install:ci` in apps/web first.

## One Q workspace

The regime platform and Evidence now run inside Q. Use **Portfolio research**, **Allocation replay**, **Trading lab**, **Market making**, and **Advanced research**. Their original accounting conventions and historical snapshots are retained. Research starts one shared Python service only when needed; Q backtests use a separate bounded Node worker.

This checkout's shared Python 3.12 environment is installed. On a fresh checkout, run `./setup-flagship.ps1 -Python 'path/to/python.exe'` once with Python 3.12+, then start Q normally. See [Q operation, feature map and migration notes](docs/flagship.md). The older project specification contains planned capabilities and is not a claim that those capabilities exist.

The former standalone projects are retained as historical references and migration sources. Q is the active product; their capabilities evolve here. Legacy script names, module paths and storage keys remain compatible with existing data.

## Real market data

- Browse the full current Nasdaq directory and NSE equity, ETF and SME directories under Markets.
- Connect **Massive** in Connections with your own API key for US daily history. Keys stay in local backend memory and are not sent to Codex.
- Q's market pages load no synthetic prices or precomputed demo backtests. The imported research labs offer separately labeled, explicitly selected synthetic scenarios; provider errors never switch to them.
- Massive does not cover NSE. Import real unadjusted NSE historical CSV files under Data until an India data provider is connected.
- Massive history uses a two-year window and five-request-per-minute pacing for Basic-plan compatibility. Each history request includes bars, splits and dividends. History is completed daily data, not a live quote.
- Immutable data snapshots and results persist locally in `.data/market`. Active browser workspace storage is `q21-workspace-real-v2`. The original synthetic workspace is retained and exportable under Settings.

## Research and connections

Five editable long-only strategy templates support server-side backtests with next-open execution, whole-share sizing, per-side costs, split handling, and dividend receivables. Results include their actual dataset version and provider. Charts, indicators and scanners use loaded historical datasets only; the scanner is not an exchange-wide screen.

Codex streams actual research conversations through the installed app server. Angel One and IBKR provide read-only account access after user authentication. Run `./start-ibkr.ps1` for IBKR's local gateway.

Manual paper fills and all live order submission remain disabled. Daily bars do not provide executable quote freshness or production session controls. Simulated account balances are explicitly separate from broker balances.

## Validation

From apps/web:
```sh
node --test tests/quant.test.mjs
npx tsc --noEmit --incremental false
npm run build
```

From the root:
```sh
node --test apps/gateway/tests/*.test.mjs
```

See [real data behavior and limitations](docs/real-market-data.md), [connection setup](docs/connections.md), [implementation plan](docs/implementation.md), and [original product specification](docs/q21-product-specification.md).
