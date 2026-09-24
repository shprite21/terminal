# Q implementation and architecture

## Q as the single system — September 2026

Q is the canonical product name and sole system going forward. All new work extends this checkout. The former standalone projects remain historical references and migration sources; their capabilities are maintained as modules within Q.

The consolidation brings the regime platform and Evidence into this existing Q checkout. [Q operations](flagship.md) document the applied architecture, feature map, validation and limits. The historical phases below remain background, not instructions to replace working engines or claims of completed production execution. The implementation uses the existing Q gateway, an on-demand local Python service and one bounded shared Python executor rather than introducing PostgreSQL/Redis just for consolidation.

## Current real-data increment

### Strategy Survival Pipeline — September 22, 2026

Portfolio Research now includes an 18-layer Strategy Survival dashboard alongside all existing research and validation views. It reuses the Python research/backtest/regime engines, shared compute queue and immutable SQLite artifact store. Validation runs preserve inputs, code, configuration, random seeds, trial history, per-layer outputs and negative results without modifying original experiments. Configurable gates distinguish hard integrity failures, research warnings and N-A prerequisites; no composite score is created. Prospective user-recorded paper evidence is separate from historical research. Live monitoring has a tested read-only contract; live feeds and execution remain unavailable. See [architecture, all 18 methodologies, defaults, API contracts and limitations](strategy-survival.md).

### Unified portfolio research — September 15, 2026

Portfolio Research now contains Strategy Research and Allocation Replay as two tabs in one workspace. Strategy mandates, validation, portfolio/risk evidence, experiment comparisons, cloning and PM decisions remain available alongside replay holdings, provider selection, saved portfolios, JSON transfer, attribution, performance/drawdown charts and CSV export. Visited tabs stay mounted when switching workflows, preserving drafts, results, import previews and in-flight analysis. Existing Allocation Replay links resolve to the allocation tab; tab selection is reflected in the page URL. Storage keys, archived experiments, calculation services and execution restrictions are unchanged.

### Codex custom strategy development — September 15, 2026

Codex now develops strategies in independent Git repositories under `.data/codex-development/<project>/workspace`. The Strategies page exposes project selection, arbitrary JSON parameters, source-file review, dataset attachment and downloadable content-addressed versions. Existing template strategies and their parameter bounds remain a separate quick-backtest workflow; they do not constrain custom strategy code. Custom code runs its own tested research scripts through Codex, not through the fixed-template backtest endpoint.

The gateway persists project conversations and resumes the recorded Codex thread. It snapshots files before and after each turn and parameter edit. Codex uses a named offline permission profile scoped to the project, denies escalation, strips credential environment variables and protects known credential files. On native Windows, broad read restrictions do not fully isolate all filesystem reads; project write isolation is verified, and sensitive existing paths receive explicit deny rules. No development code is loaded into the gateway, promoted to deployment or executed by the template engine. Live execution remains disabled.

Validation includes a real Codex turn creating implementation files, arbitrary parameters and three passing tests, a separate check proving writes outside the project fail, conversation resume, immutable-version and endpoint security regressions, the quant suite, TypeScript checking and the application build.

### Explicit provider selection — September 14, 2026

The terminal now supports explicit Yahoo, Massive, Synthetic and imported CSV selection. Yahoo uses the existing Python/yfinance adapter; Massive retains raw-price/corporate-action accounting in terminal backtests. Synthetic histories are seeded, labeled scenarios, never a fallback for provider failure. This supersedes the earlier statement that synthetic data is absent from runtime paths.

Portfolio research and allocation replay support Yahoo, Massive and synthetic inputs; the original fixed portfolio demo remains available. Trading lab accepts Massive daily datasets alongside Yahoo and synthetic bars. Advanced research adds a provider-backed multi-asset history action feeding its existing models. Massive requests from Python use a token-authenticated loopback callback to the gateway so keys remain in server memory. Source-specific cache pointers and immutable dataset versions prevent cross-provider substitutions. CSV imports remain an explicit separate source.

The current Massive adapter is US daily history within two years. Its Python portfolio/lab views use split-adjusted prices and explicitly exclude cash dividends, whereas terminal backtests retain the existing raw-price split/dividend treatment. Yahoo embeds adjustments in OHLCV research units. New selected-symbol synthetic histories use seed 42, fixed end 2025-12-31 and artificial weekday observations; they do not represent exchange sessions or real performance. Existing lab scenarios retain their user-controlled seeds/dates. Order-book, latency and options-flow simulations remain synthetic because OHLCV cannot provide those observations. Strict verified-data workflows continue to require their existing calendar and corporate-action metadata. Live execution remains disabled.

The displayed brand is now **Q**; technical namespace remains `q21`. Synthetic data has been removed from all runtime paths. Official Nasdaq/NSE catalogue adapters, Massive US daily history, CSV import, immutable local data snapshots, and corporate-action-aware backtests now live behind `apps/gateway/market-data.mjs`. Market UI and data transport are separate components/hooks. The old synthetic workspace remains exportable, but does not populate current prices or results. Massive authentication is required for US prices; NSE prices require imported real history. Manual paper fills and all live order submission remain disabled. See [real-data behavior and limits](real-market-data.md). Earlier phase descriptions below describe the original scaffold and are superseded by this increment.

## Repository audit

The initial workspace contained only the product specification. There were no existing strategies, tests, data pipelines, frontend, or backend to reuse. The scaffold uses React, TypeScript, the Next.js app-router API through Vinext, Tailwind, and the bundled accessible Shadcn components. Vinext permits the same web application and route handlers to run on the Sites Worker runtime.

## Current structure

| Path | Responsibility |
| --- | --- |
| apps/web/app | App entry, theme, metadata, market/backtest/health HTTP routes |
| apps/web/components/terminal.tsx | Terminal workspace, navigation, forms, state, result views |
| apps/web/components/terminal-charts.tsx | SVG equity, drawdown, sparkline, and OHLC charts |
| apps/web/lib/quant.ts | Synthetic data, indicators, signals, daily backtesting, metrics |
| apps/web/lib/paper.ts | Local paper-order accounting and deterministic checks |
| apps/web/tests/quant.test.mjs | Quant and paper-account behavior tests |
| docs | Specification and staged implementation plan |

The research/backtest HTTP boundary is server-side. The account simulator and workspace persistence are explicitly local to the browser. They must not be reused as production execution services.

## Proposed production architecture

Retain apps/web as the interface. Add apps/api as a Python/FastAPI modular monolith backed by PostgreSQL and Redis. Move quantitative functionality behind typed endpoints into quant/{data,features,strategies,backtest,portfolio,risk,execution,brokers,validation,regimes}. Add workers and a scheduler under infrastructure. No frontend process should own live execution. Keep production strategy versions immutable and separate from development worktrees. CodexGateway accesses scoped research and repository tools; OMS/EMS, compliance, risk, settlement, and broker services control execution independently.

## Delivery phases

1. **Implemented:** coherent terminal shell, design system, navigation, command palette, synthetic fixtures, connected research and backtesting workflow, and clearly separated manual paper simulator.
2. Add historical CSV ingestion and provider adapters, exchange calendars, validated adjusted bars, PostgreSQL persistence, and dataset versioning.
3. Add Python strategy specifications and implementations, cross-sectional portfolios, version history, strategy code worktrees, and registry.
4. Replace the initial backtest service with a Python job worker, extend accounting and transaction models, and independently validate all statistics.
5. Add asynchronous parameter experiments, baseline comparison, held-out testing, walk-forward validation, and Monte Carlo diagnostics.
6. Add multi-currency portfolio accounting, FX attribution, factor/risk calculations, compliance profiles, and a proper settlement ledger.
7. Add scheduled backend paper execution, persistent OMS/EMS state, reconciliation, and observability.
8. Connect Codex through a server-side gateway, streamed tool events, scoped repository worktrees, diff review, and contextual research artifacts.
9. Add Angel One and IBKR paper adapters, credentials in server secret storage, contract mapping, calendar checks, and broker reconciliation.
10. Validate production execution boundaries, immutable promotion, deployment approvals, operational monitoring, recovery, and security before enabling any live adapter.

No unimplemented phase is represented as connected or production-ready in the terminal.

## Connection increment

`apps/gateway` now provides a local Node.js service for the installed Codex app-server and read-only Angel One/IBKR adapters. The web app uses a same-origin development proxy and displays verified session states. Codex supports real streamed research conversations. Angel One offers an in-app local login form; IBKR uses its own installed Client Portal Gateway login. Broker authentication still requires the account holder. See [connection details](connections.md). This does not implement the broader production execution phases above.
