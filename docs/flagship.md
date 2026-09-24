# Q — operation and feature map

**Q is the single system going forward.** All future capabilities belong in this checkout as integrated Q modules. Former product names below identify the origin of retained capabilities and records. The original projects remain historical references and migration sources. Existing technical paths and storage keys are retained for compatibility.

The consolidation extends the existing Q terminal. It does not replace Q's theme, saved workspace, market data store, Sites manifest or Vite Sites plugin. The historical product specification describes many planned features; the scope here is the capabilities that actually existed in the three projects.

## Start and stop

Run `./start-q21.ps1` from the repository root and use `http://127.0.0.1:5173`. Restart a previously running Q gateway to load these changes. Node 24+ is required for the gateway's direct TypeScript imports. The shared Python 3.12 environment at `apps/engine/.venv` has been installed and `pip check` passes. For a new checkout, install web dependencies from their lockfile and run `./setup-flagship.ps1 -Python 'C:/path/to/python.exe'` with Python 3.12+.

Q launches the Python engine only when a research endpoint is requested. The private ephemeral loopback port requires a random gateway token. Python reports readiness only after application startup. One bounded executor admits at most three queued/running Python calculations across both imported workflows. Q's existing daily backtest runs in one bounded Node worker. A queue-full response requires retrying after a calculation finishes.

Stop Q through its launcher. The Python service watches its owner's pipe and exits if the gateway terminates, including Windows force-close. Work still in progress is marked interrupted/failed on restart; it is not silently represented as completed. A stop permits up to five seconds for shutdown before ending unfinished work. Existing completed snapshots remain readable. These are local research jobs, not a production trading service.

## Where each existing capability lives

| Origin / capability | Q location | Preserved behavior / scope |
| --- | --- | --- |
| Q market catalogues, Massive history, CSV import, immutable data | Markets, Research, Data, Connections | Existing adapters and source labels; failed providers stay failed. No synthetic fallback. |
| Q five templates, indicators, scanner, backtests and workspace export | Existing Q pages | Next eligible open, cash and whole shares, costs, splits and dividends; worker parity tested for every template. Scanner uses loaded datasets. |
| Q Codex, Angel One, IBKR | Existing Connections and Codex panel | Real streamed Codex integration and user-authenticated read-only broker access retained. No live order endpoint added. |
| Regime PM mandate and eight data-supported sleeves | Portfolio research | Yahoo/demo selection, ensemble/HMM options, allocation/risk constraints, validation windows, costs, experiment book, clone using frozen prices, comparisons and PM decision history. |
| Regime PM diagnostics | Portfolio research → Validation / Portfolio & risk | Equity, drawdown, exposure, turnover, attribution, benchmark, factor, correlation, regime, cost and parameter diagnostics; retained memo and artifact downloads. |
| Custom weighted portfolio | Allocation replay | Up to 30 holdings, weight checks, benchmark, historical performance, risk statistics, chart/table/CSV, saved portfolios, WebMCP tools where supported. |
| Original broader regime Python library | `apps/engine/{strategies,regime_detection,portfolio,analytics,...}` | HMM, macro/breadth/volatility detectors, allocation/optimization, pairs and cointegration, events, sector rotation, robustness, backtesting and report libraries retained. Modules that were Python-only remain callable Python APIs; they are not advertised as new real-data UI strategies. |
| Original 14-strategy offline regime script | Advanced research → Run full regime library scenario | Retained seeded 900-session suite and generated earnings, factor/benchmark/regime/risk/robustness diagnostics, HTML report and source export. Explicit synthetic acknowledgement. |
| Older regime experiment records | Artifact library → Regime archive | All 13 experiment records, including three without newer dashboard job files. Existing files downloadable; missing result evidence is not fabricated. |
| Evidence Yahoo / synthetic daily and intraday data | Trading lab | Source, interval, dates, seed/volatility/drift; frozen datasets, actual coverage, limitations and price/volume candlesticks. |
| Evidence day/swing study | Trading lab | Momentum, moving average, mean reversion, warm-up, costs, cash, volume participation, independent A/B periods and acknowledgement. |
| Evidence two-period visual analysis | Saved lab report | Metrics, rebased equity by elapsed bar, actual dates, equity/benchmark, drawdown, trades/fills and full exports. |
| Evidence synthetic market making / latency arbitrage | Market making | Original configuration and replay; separate P&L/fees, venue/quote, inventory, sensitivity, fill and decision views. Atomic hedge and synthetic assumptions remain explicit. |
| Evidence hypotheses and versions | Advanced research | Templates, formulation checks, guided fields plus complete JSON, edit saved hypothesis as new version, state transitions and audit history. No fabricated LLM output. |
| Evidence strict historical data | Advanced research | Official master download/search, Angel historical session, resumable downloads, freeze-download, exact CSV/manifest validation, calendars, actions and quality-review artifacts. |
| Evidence frozen daily strategies | Advanced research | Frozen hypothesis/dataset IDs, universe, chronological boundaries, trailing features, effective-dated costs and complete execution schema. Structured lists stay editable in JSON as in the original UI. |
| Evidence studies and validation | Advanced research | Training/validation/one-use holdout, registered failures, bounded explicit robustness variants, walk-forward with inner validation and separate final holdout. |
| Evidence result evidence | Artifact library / completed result | Metrics, benchmark, signal diagnostics/observations, signals/orders/fills/trades/holdings/cash/dividend/open-position tables and provenance/export. |
| Evidence forward review | Advanced research / Candidate review library | Eight evidence criteria, attestations, frozen specification and monitoring plan export. This does not deploy or place orders. |
| Evidence command line | `./.venv/Scripts/python.exe -m evidence.cli` from `apps/engine` | Original commands retained under the `evidence` namespace; default store is Q's `.data/flagship/evidence`. |

The Streamlit interface and second dashboard server are replaced by Q-native lazy views. Already visited research views preserve drafts during navigation; inactive views suspend effects/polling. Evidence uses one shared workspace across its three sidebar entries. Per-action advanced JSON drafts survive action switching. This is in-session preservation, not a promise of saving unsaved drafts through browser reloads. Saved snapshots remain independent of forms.

Large plots display a bounded sample preserving the displayed series' extrema in each bucket and identify that sampling in the caption. Result tables paginate without dropping observations. Full source rows and exports remain unchanged. Candlesticks provide an adjustable window of up to 600 actual bars. Explicit source time zones are converted to UTC in candle labels; unzoned legacy values retain a source-time label. Original observations and exports are unchanged.

## Accounting boundaries

| Engine | Model |
| --- | --- |
| Q daily research | Raw execution OHLC, next-open whole-share fills, cash, explicit per-side costs, splits and dividend receivables. |
| Regime research | Portfolio weights and lagged return accounting, fractional allocations, configured leverage and costs. These are research exposures, not Q share orders. |
| Allocation replay | Adjusted Yahoo closes and buy-and-hold fractional allocation; single verified quote currency, no live execution. |
| Evidence strict daily | Raw price convention, explicit sessions and availability, whole shares, historical effective-dated cost schedules and corporate-action ledger. |
| Evidence bar lab | Yahoo adjusted bars or labeled synthetic bars, independent period cash/warm-up, next observed open, prior volume participation. |
| Evidence MM | Seeded synthetic event/queue/latency simulation, inventory limits and modeled atomic arbitrage hedges, scenario units. |

These outputs are not silently combined into one performance series. Price conventions, currencies, costs, sessions, fractional weights and fill timing must match before making a controlled comparison. No new broker login, live order, external financial action or live price feed was enabled by this consolidation.

The retained legacy full-library diagnostic script selects pairs using its complete synthetic sample. Its headline output is in-sample diagnostic evidence, not causal out-of-sample validation. That original behavior remains explicit in the saved suite's limitations. Portfolio research continues to keep pairs unavailable until a train-only selection/calibration contract exists; consolidating code does not remove that restriction.

## Migration and portfolio transfer

The original migration copied 19 Evidence artifacts and 13 regime experiment folders into `.data/flagship`. All 95 files in the regime experiment folders were subsequently compared byte-for-byte with the originals and matched. The Evidence store validates content hashes when artifacts are read. The original projects and their environments remain available.

Two shared regime report files were additionally copied to `.data/flagship/legacy-reports` with a SHA-256 manifest. Their filenames were reused across older source runs, so they are labeled as shared files present at migration time, never attributed as immutable evidence for each older record. Their original paths remain historical references inside the unchanged experiment JSON.

Saved allocation portfolios on `http://localhost:3000` or `http://127.0.0.1:3000` belong to that browser origin. Q cannot read them across origins. To transfer them without modifying the former app:

1. Open the exact old portfolio origin in the browser where the portfolios were saved.
2. Run this export snippet in that page's browser developer console. It reads only the two known portfolio keys and downloads their JSON; it does not delete them.

```javascript
const raw = localStorage.getItem('shprite.portfolios.v1') ?? localStorage.getItem('axiom.portfolios.v1');
if (raw === null) throw new Error('No saved portfolios on this browser origin');
const url = URL.createObjectURL(new Blob([raw], {type:'application/json'}));
const link = document.createElement('a'); link.href = url; link.download = 'saved-portfolios.json'; link.click();
setTimeout(() => URL.revokeObjectURL(url), 1000);
```

3. In Q → Allocation replay → Transfer saved portfolios, select the JSON, review the names, then choose **Add reviewed portfolios**. Invalid files are rejected; identical snapshots are skipped; different snapshots with the same name get an import suffix. A 50-portfolio limit is checked before writing. Export Q's current saved portfolios from the same panel at any time.

Q's existing `q21-workspace-real-v2` browser store, original exportable synthetic workspace, `.data/market` and credentials were not removed or merged into incompatible schemas. Evidence's OS keyring service name remains `evidence-angel-one`. Its credential setup is interactive and must be performed by the user; no secret is persisted in web state. The history session and Q account connection still have distinct provider lifecycles.

## Verification and remaining acceptance limits

Applied-code validation: 146 Python tests pass in Q's own environment, 60 Node tests pass, TypeScript checking passes and the Vinext production build passes. Python tests omit the legacy Streamlit UI suite because that UI has been replaced; the one reported warning is a Starlette/httpx TestClient deprecation. Numerical tests cover chronology, accounting, costs, corporate actions, queue bounds, replay and Q worker parity. Additional tests check import preservation, plot transformations and old archive access.

`node apps/gateway/tests/flagship-runtime.mjs` performs real loopback gateway→Python integration, reads migrated artifacts, runs isolated synthetic comparisons/MM/full-library scenarios, exports results, replays the bar/MM bundles, checks health while computing and verifies shutdown/restart. Outputs go to `.data/flagship-validation/<UTC timestamp>` and do not populate the user's research history. Recorded timing/memory findings are in [performance notes](flagship-performance.md).

The production build was run directly through the existing Vinext CLI after the Sites build wrapper failed to invoke npm correctly on Windows. The Sites manifest and plugin were preserved. No hosting/deployment was performed. The root page returned HTTP 200, and the actual Vite proxy reported the research engine ready with live orders disabled. A subsequent local browser acceptance pass on 11 September covered navigation, saved reports, synthetic calculations, real Yahoo downloads and allocation analysis; see [browser acceptance](flagship-browser-acceptance.md). Authenticated broker end-to-end testing remains outstanding. The original systems should remain until the user validates their representative live-data workflows and imports any origin-bound portfolio saves. Historical exports requiring the original code/dependency fingerprint must be replayed in their original environment.

## Backup and rollback

The initial integration manifest and four pre-integration Q file backups are at `.flagship-backups/20260910T174037Z`. Its `manifest.json` records each initial destination, prior hash (or null for a new file), and applied hash. `docs/flagship-source-manifest.json` records source provenance. Later fixes described here supersede those initial applied hashes; the old preparation/integration scripts must not be rerun over this checkout.

For rollback, stop Q, preserve a copy of the current source and `.data/flagship`, and export browser portfolios/workspaces first. Restore only the four files with a non-null `before` hash from their matching backup paths after comparing current changes. Newly added engine/view files can remain unused; do not mass-delete entries from the initial manifest because they may now contain follow-up work. Leave `.data/market`, browser storage, original repositories and OS credentials intact. Rebuild/restart Q after restoring its original entry points. Data written by the consolidation should remain archived for a deliberate later migration; rollback is not a request to delete it.
