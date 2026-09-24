# Flagship browser acceptance — 11 September 2026

Local Q at `http://127.0.0.1:5173`, through the existing gateway on 5174. Python research used `.data/flagship-browser-validation/20260911`, with copied experiment records and a SQLite backup of the Evidence registry. Acceptance runs did not enter `.data/flagship`. Browser checks used the in-app browser at its normal 1280 × 720 viewport.

## Verified workflows

- Trading lab: selected a migrated synthetic daily dataset, inspected OHLCV candles and coverage, changed lookback to 13, navigated through Market making and returned with the value retained.
- Market making: submitted an acknowledged 120-event synthetic scenario. Completion opened its saved result, P&L/fees, venue quotes, inventory and latency-sensitivity charts.
- Trading lab: ran a synthetic two-period comparison. Verified elapsed-bar equity rebased to 100, per-period portfolio/benchmark curves, drawdown from initial cash and paginated result tables.
- Advanced research: changed a hypothesis name, switched actions and recovered the draft; selected a formulation template and then its placeholder without losing the editor's valid contents. No hypothesis was saved during this check.
- Portfolio research: opened the migrated Yahoo run `20260906T095855Z-6d126c8d`; inspected Validation and Portfolio & risk diagnostics. An unsaved mandate name survived sidebar navigation.
- Allocation replay: loaded the starter allocation without manufactured performance; imported a local QA JSON file into the review preview, then cancelled without writing a saved portfolio. An unsaved allocation name survived sidebar navigation and the Open research workspace button.
- Allocation replay: public Yahoo analysis returned 251 daily prices spanning 2025-09-11 through 2026-09-10 in USD, with source, retrieval timestamp and modeling limitations. Provider requests initially failed under restricted networking; the same flow succeeded after restarting the local gateway with network access. Navigating away during an analysis cancels it and reports cancellation.
- Trading lab: downloaded Yahoo AAPL daily history for requested dates 2025-02-01 through 2025-03-29 into the isolated store. The saved dataset opened automatically with real-data labeling, actual coverage and UTC-converted candle labels (`ef04980d1be101445bdb3e7c901092950f5eab5e2805cbd0f53b0117485c7c71`).
- Artifact library: reopened migrated real-data report `8d3a2d9e7d5f66daff59d40938334f29f7d607b5b90c6ec9cac52c0594b74671` with comparison and drawdown charts; the Regime archive listed all 13 migrated records.
- Visual inspection: reviewed the allocation surface and comparison chart with the Codex side panel visible. After the layout fix, the main workspace's scroll width equaled its 797-pixel client width; wide tables scrolled inside their own containers.
- Portfolio research end to end: launched `QA flagship browser workflow` using the fixed synthetic fixture; run `20260911T105152Z-7997e4a2` completed. Synthetic data correctly blocked paper candidacy. Cloned the configuration, reduced the position cap from 20% to 15%, and completed variant `20260911T105248Z-53e73287` using its frozen prices. Recorded a QA-only watchlist rationale on the variant, compared both runs in Experiment book, and reopened the original. The browser reported no error/warning logs in this clean session.
- Independent snapshot check: SHA-256 hashes of the original `experiment.json`, `prices.csv`, `result.json`, `returns.csv` and `targets.csv` remained unchanged after cloning, running and reviewing the variant. Variant prices were byte-identical to the original; its result was distinct. Evidence is saved in the isolated acceptance folder as `original-run-hashes.json` and `snapshot-preservation-check.json`.

## Defects fixed during acceptance

1. Removed duplicate terminal headings beneath the five integrated research pages and nested main landmarks.
2. Converted candle labels from explicit source offsets to UTC instead of appending a misleading UTC suffix; added date-rollover and unzoned-input checks.
3. Opened completed Evidence jobs immediately when they finish before the first polling cycle; surfaced immediate failures too.
4. Guarded the empty formulation-template option so it cannot set the editor to undefined.
5. Connected allocation-to-research navigation to Q's existing navigation handler, preserving drafts and removing the unnecessary framework Link dependency. Development dependency optimization had produced a transient Link hook error before this change.
6. Constrained research grid columns so wide result tables cannot stretch charts beyond the workspace.

## Scope and remaining limits

The 60 Node tests, TypeScript check and final Vinext production build passed. No Python calculation changed in this browser pass; the preceding 146-test Python result remains the recorded numerical validation. The Sites build wrapper still fails to invoke npm on this Windows host, so the successful build used the project's existing Vinext CLI directly. Hosting metadata and the Sites Vite plugin remain intact.

These are representative acceptance checks, not an exhaustive browser matrix or a claim of broker parity. No broker login, live order, Codex message or deployment was submitted. Actual portfolio saves on the former port-3000 browser origin have not been transferred; Q's JSON import supports that separate user-owned step. Original projects remain intact. Mobile/resized viewport behavior and authenticated Angel/IBKR workflows were not tested in this pass.
