# Evidence — local systematic strategy research

A Python/Streamlit research dashboard with **Yahoo Finance**, explicitly labeled
**synthetic scenarios**, **day / swing strategies**, and a separate **market-making
and latency-arbitrage simulator**. The September 8 user override in
`BUILD_PROMPT.md` supersedes the earlier real-only policy. Angel One is deferred;
no credentials are needed for the new lab.

The sidebar offers Trading lab, Market making, and Advanced daily research.
The advanced workflow preserves the previous strict NSE/calendar implementation.
All executions are simulated. A new empty data directory has no performance
statistics until a computation runs. This workspace also contains explicitly
computed, labeled demonstrations from `scripts/lab_demo.py`.

## Trading lab

1. Select **Yahoo Finance (real)** or **Synthetic scenario**. Yahoo accepts one
   ticker such as `RELIANCE.NS`; select daily or 1m/5m/15m bars and inclusive dates.
2. Inspect candlesticks, volume, source, requested/actual dates and limitations.
3. Choose **Day trade** (intraday bars required) or **Swing trade**, then Momentum,
   Moving average, or Mean reversion. Set lookback, holding bars, threshold,
   capital, allocation, per-side costs and prior-bar volume participation.
4. Set two non-overlapping periods A and B. Both reset capital and indicator
   warm-up; day indicators additionally reset each session. Signals execute at
   the next observed open. Day positions flatten at each last observed session
   close; both modes flatten at the evaluation end under a full-liquidation
   assumption. This is exploratory comparison, not untouched holdout testing.
5. Inspect normalized equity, actual-time equity, drawdown, gross buy-and-hold,
   simulated fills and exit lots. Export data and results as a ZIP for replay.

Yahoo uses adjusted OHLC, `repair=False`, regular hours and an explicit exclusive
provider end date one day beyond the inclusive UI end. The returned CSV, ticker,
download time, yfinance version, hashes and actual coverage are saved. Research
operates in adjusted-price units; dividends/splits are embedded, not separate
cash entitlements. Raw volume participation is an approximate capacity assumption.
Exchange calendars and historical universe membership are not independently
verified. Missing/non-finite prices block loading; provider failures never
generate synthetic data. This adapter conservatively limits 1m history to seven
recent days and other intraday history to 60. Yahoo may impose tighter limits.
See [yfinance documentation](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html).

Synthetic bar data uses a saved seed and lognormal process parameters. Weekdays
and 09:15–15:30 India-time sessions are modeled without holidays. Synthetic
results cannot establish a real-market edge.

## Market-making environment

Run Market making, Latency arbitrage, or their combination on a seeded two-venue
event stream. Configure volatility, venue lag, feed/order latency, quote refresh,
spread, queue ahead, inventory skew/limits, size and maker/taker fees. The same
events are replayed at several outbound latencies. Charts show net P&L, arbitrage
P&L, fees, both venue mids, live quotes, inventory and latency sensitivity.

This is a **synthetic microstructure model**. A slow venue follows a delayed
reference mid. Quotes become active after outbound latency, remain exposed until
replacement arrives, and can be rejected as post-only. Aggressive synthetic volume
consumes assumed queue ahead before fills. Arbitrage decisions use delayed data;
both market legs fill at arrival prices, so the observed edge can disappear.
Paired hedging is atomic and assumes liquidity; legging failures, hidden liquidity,
venue capital fragmentation, transfers, borrowing, financing and taxes are omitted.
Terminal inventory is liquidated at the modeled spread with taker fees. Delays
round up to event resolution; outbound latency is at least one event. Yahoo bars
are **not** an empirical input to this simulator.

## Reproducible demonstrations

```powershell
Set-Location 'C:\quant\projects\systematic swing trading bot\backtester'
.\.venv\Scripts\python.exe -m scripts.lab_demo --yahoo
.\.venv\Scripts\python.exe -m research.replay_lab 'data\lab_exports\SYNTHETIC-market-making.zip'
```

Omit `--yahoo` for deterministic offline synthetic runs only. This command saves
labeled datasets and reports to the app's registry, ZIPs and a demonstration
summary under `data/lab_exports/`. It does not replace a failed Yahoo request.
Exports include source observations, configurations, source/dependency
fingerprints and matching engine source files. Replay verifies hashes and exact
metrics with the recorded code/environment. Old reports remain immutable.

## Launch

The project virtual environment is already installed on this machine:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Open <http://127.0.0.1:8501>. The server binds to loopback. For another machine,
install Python 3.12, then run:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m streamlit run app.py
```

`pyproject.toml` pins direct application dependencies. `requirements.lock.txt`
records the installed environment, including the test and research utilities.
This was tested on Windows with Python 3.12 and smartapi-python 1.5.5.

## Optional advanced workflow: secure Angel One setup (deferred)

Run this in your own local terminal, never in chat:

```powershell
.\.venv\Scripts\python.exe -m research.cli credentials
```

Hidden prompts save API key, client code and PIN in the OS credential store
under service `evidence-angel-one`. The optional TOTP seed is stored only after
typing `YES`. Otherwise enter a current TOTP in the local connection form or
CLI. The Streamlit connection form clears on submission. Session tokens stay
in server memory. The application does not write them to browser storage,
datasets, reports, SQLite or log files.

To see what you type and check it before pressing Enter, run
`.\.venv\Scripts\python.exe -m research.cli credentials --show-input`.
This makes all setup fields visible in your local terminal, including the PIN
and optional TOTP seed. Storage still uses the OS credential store.

Run the credentials command **on its own**, then wait for each prompt. Hidden
input displays neither characters nor asterisks; enter the value and press
Enter. Empty values are retried, and no entries are saved until every required
value has been collected. Press Ctrl+C to cancel before saving. Piped input or
an echoing terminal fallback is rejected. A successful local save is distinct
from authenticating with Angel One.

Environment variables listed in `.env.example` are an alternative. `.env` is
not automatically loaded. Configure it through your own environment loader
if needed. Do not commit secrets. Re-run the local credential command to
replace credentials. Disconnect by ending the local server; the current
version does not offer a persistent session-token cache.

The SDK exposes order methods, but our HTTPS transport rejects every route
outside login, token refresh, profile, logout and historical candles. Its
original error logging can include headers and credentials, so the wrapper
disables SDK logging before import and replaces its transport. IP discovery
is bounded; actual public IP replaces the SDK's hard-coded fallback. Network
requests verify TLS and do not follow redirects carrying credentials.

## Research workflow

1. **Data & connection:** connect locally, fetch the official instrument master,
   search/select NSE EQ instruments, and choose the full date range.
2. Download/resume history. Jobs support progress and cancellation. Completed
   chunks are checkpointed. Use the explicit re-fetch checkbox if an earlier
   chunk was empty, incomplete or corrected by the provider.
3. Supply an attributable session calendar, raw-price evidence and any sourced
   corporate actions. Inspect coverage; freeze only when every requested
   instrument/session is present. There is no silent shortening.
4. **Hypotheses:** fill all specification fields. Templates are untested user
   assumptions. Guided checks identify missing fields and falsification tests.
   Save a version, then record a state and reason in the audit log.
5. **Strategy:** reference frozen hypothesis and data versions. Specify the
   six chronological boundaries and effective-dated cost schedules. Include
   enough earlier real data for the feature lookback before evaluation starts.
6. **Research & validation:** run a named partition, a bounded robustness batch
   or expanding walk-forward folds. Every portfolio run also computes a
   partition-fenced signal study. Jobs and trials persist their statuses.
7. **Experiments & reports:** inspect real computed equity/drawdown, metrics,
   costs, signal diagnostics, order/fill/holding ledgers, source and code hashes.
8. **Forward review:** record evidence for eight explicit criteria and export
   the frozen specification and monitoring plan. Review outcomes are researcher
   attestations, not a statistical certificate of profitability.

No optional LLM is required. No arbitrary strategy code is executed.

`examples/hypothesis.json` is a complete **untested assumption** template.
`examples/strategy.template.json` supplies execution assumptions but deliberately
leaves dataset IDs, universe, dates and historical costs unset. Fill those from
real data before validation; the application rejects the unfinished template.

## Contracts and imports

The authoritative schemas are `research/models.py` and `research/actions.py`.
Supplemental imports require attributable real observations, a source URL,
retrieval time, a matching SHA-256 of the original uploaded CSV, an explicit
real-data attestation, instrument mappings and a session calendar. Provenance
records are auditable attestations; they cannot independently authenticate
an arbitrary user-supplied file's contents.

CSV columns, in any order:

```text
instrument,date,open,high,low,close,volume,available_at
```

`date` is an ISO exchange-local session date. `available_at` is a timezone-aware
ISO timestamp at/after the session close. Numeric fields must be finite,
prices positive, volume nonnegative, and OHLC relationships consistent.
Identical overlapping records are counted and deduplicated. Conflicting
duplicates, unexpected sessions, incomplete candles and out-of-range rows
reject freezing. Missing sessions and unexplained >25% close changes produce
a persisted blocked quality review. The 25% threshold is a heuristic, not proof
of clean corporate-action coverage. Zero-volume rows remain marked and cannot
fill orders.

CSV metadata JSON contains:

| Field | Required content |
|---|---|
| `source` | `provider` (`supplemental` or provenance-backed `Angel One SmartAPI`), `url`, `retrieved_at`, `description`, `raw_sha256`, `real_data_attestation: true` |
| `instruments` | List of `id`, `exchange: NSE`, `symbol`, `token`, `mapping_version`, `instrument_type: cash_equity`, `currency: INR` |
| `calendar` | `source_url`, `description`, `coverage_start`, `coverage_end`, `sessions` |
| `start`, `end` | Full requested date range |
| `price_note` | Evidence for raw price convention and known limitations |
| `corporate_actions` | Optional list of sourced split/dividend records |

`calendar.sessions` maps each actual session date to `[opening, closing]` ISO
timestamps with UTC offsets. Every trading session—including special sessions—
must be listed; holidays must be excluded. The declared calendar coverage must
span the entire requested range, including nontrading days. No weekday-only
calendar is silently substituted. NSE introduced closing-auction changes in
2026; use the correct dated session rules and conservative final availability.

A current instrument master is not historical membership. This release uses
an explicitly selected fixed universe and always warns of survivorship bias.
Missing/delisted instruments block the full-coverage workflow. It does not
invent liquidation prices or remove held securities from a completed result.

Cash actions require `instrument`, `kind: cash_dividend`, `ex_date`,
`available_at`, `source_url`, `source_note`, `real_data_attestation: true`,
`cash_per_share`, and `pay_date`. Splits require `kind: split` and an integer
`quantity_multiplier` instead of cash/payment fields. Only sourced actions
available before the effective session are accepted. Same-day dividends must
be explicitly consolidated. Bonus issues, rights, mergers, fractional shares,
withholding tax and delisting accounting are unsupported and must block
affected research. Users must disclose actions smaller than the jump heuristic.

## Execution and costs

- Deterministic trailing momentum, mean reversion, cross-sectional relative
  strength and volume-conditioned momentum. Signals use only observations
  available by the decision close. Labels are computed separately.
- Market entries execute at a later session opening. Orders are sized from
  decision-time capital/price/trailing volume; observed execution prices can
  reduce size to enforce cash/exposure constraints, never increase it.
- Opening sells precede opening buys. Buys sort by descending score, then stable
  instrument ID. Intrabar exits occur after opening orders, so their proceeds
  cannot fund an earlier purchase. Constraints are checked at order execution;
  subsequent price drift can change exposure.
- Explicit spread and slippage in basis points. Full-session volume caps fills
  under an assumption-dependent opening-liquidity model. Daily bars cannot
  establish actual opening liquidity or queue position. Partial remainders
  expire at that session; overdue holding-horizon exits are resubmitted.
- Optional protective stops/targets activate the session after entry. Gaps use
  the real opening price. Otherwise stop wins if both barriers are crossed;
  a mere target touch does not fill. Intrabar execution time is unknown.
- Integer splits adjust share count, cost basis, pending orders and trailing
  price ratios, without modifying stored OHLCV. Sourced dividends become
  receivables on ex-date and move to spendable cash on/after pay date, once.
  Tax and settlement timing remain explicit simplifications.
- Final positions remain open and marked at actual final observations; final
  dividend receivables are retained in NAV. Trade metrics are price P&L of exit
  lots; dividend income is in the separate cash-movement ledger.
- Effective-dated schedules calculate brokerage, STT, exchange, SEBI, IPFT,
  GST, stamp duty and DP independently. `examples/costs-current-reference.json`
  records an observed current tariff only. **Historical applicability is not
  established:** configure explicit dates and account-specific tariffs rather
  than extrapolating it silently.
- Fees round per simulated fill to paise, half-up. Brokerage is per order with
  one fill event; DP assumes one ISIN debit per exit session. Real contract-note
  aggregation, statutory rounding, discount plans and settlement debit events
  may differ. Estimated historical costs must remain labeled.

NAV reconciles cash + holdings + dividend receivables. Gross performance adds
costs and assumed spread/slippage back to the same position path; it is not an
independently resized frictionless portfolio. CAGR is unavailable below one
year, annualized volatility/Sharpe below 20 sessions. Annualization uses 252
sessions and zero risk-free rate. Undefined ratios stay unavailable.

## Validation and boundaries

Training, validation and holdout ranges are disjoint. Evaluators receive only
data through their partition end; earlier rows are available for warm-up.
Deterministic features have no learned transformations to fit. ML, learned
imputation and optimization on holdout returns are not implemented.

Walk-forward expands training, selects a bounded lookback on inner-validation
net return, freezes it, and evaluates the next interval. Final holdout dates
are excluded. Folds reset cash, are individually labeled and are not spliced
into a fictitious continuous equity curve. Label-purging/embargo utilities are
tested on real labels; no overlapping forward labels enter parameter fitting.

Holdout access is consumed at first attempted read for the research family,
even if evaluation later fails. It is excluded from automated selection.
SQLite discourages accidental reuse but cannot prevent a researcher from
copying the database, renaming a family or having viewed prices elsewhere.

Signal studies calculate price forward labels, sample counts, daily terciles,
rank IC, top-minus-bottom returns and persistence where defined. Date-level
nonoverlapping blocks provide descriptive standard errors only with at least
five blocks; this is not an IID confidence claim or multiple-testing correction.
Sector/event/point-in-time universe diagnostics, bootstrapped confidence
surfaces and advanced multiple-testing estimators remain unavailable.

## Reproduce and verify

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m research.cli status
```

Tests use 40 real NSE observations (four equities, January 1–12, 2024), six
Nestle observations spanning the real split, four real Angel master mappings,
and sourced Nestle/TCS action facts. `tests/fixtures/provenance.json` and related
manifests contain URLs and hashes. `tests/fixtures/CALCULATIONS.md` explains
hand-checked expectations. All test computations use temporary stores; the
application database remains empty. Only retry jitter uses randomness.

On Windows, test runs allocate a unique `evidence-pytest-<id>` directory under
the invoking user's temporary directory. They avoid the shared
`pytest-of-<username>` root, which may belong to a different execution identity.
Pytest's optional persistent cache is disabled for the same reason. Existing
private temp/cache directories do not need to be deleted or have their access
permissions changed. An explicitly supplied `--basetemp` is still respected.

Every report embeds strategy/hypothesis versions, source/dataset hashes, exact
boundaries, source-file fingerprints, Git revision when available, Python and
dependency versions. Repeated runs compare deterministic result hashes.
SQLite artifact/event records reject updates and deletes. Back up the entire
`data/` folder, including `raw/`, before moving research between machines.

Reports are written to `data/reports/<report-id>/report.md` and `artifacts.zip`.
The archive contains a self-contained report JSON, specifications and CSV
ledgers. Failed/cancelled jobs are not completed reports.

### Historical Angel One demonstration — deferred by the September 8 override

Once credentials are configured, use the UI workflow above or CLI:

```powershell
.\.venv\Scripts\python.exe -m research.cli master
.\.venv\Scripts\python.exe -m research.cli search <mapping-version> <symbol>
.\.venv\Scripts\python.exe -m research.cli download <request.json>
.\.venv\Scripts\python.exe -m research.cli freeze-download <download-id> <calendar.json> --price-note '<verified raw-price evidence>'
.\.venv\Scripts\python.exe -m research.cli hypothesis <hypothesis.json>
.\.venv\Scripts\python.exe -m research.cli strategy <strategy.json>
.\.venv\Scripts\python.exe -m research.cli run <strategy-id> --partition validation
```

The request JSON contains returned `instruments`, `start`, and `end`. CLI
mapping checks require actual saved master entries. No tokens from examples
are hard-coded. The final demonstration must disclose full coverage, quality
limitations, actual configured cost assumptions and reproducible computed
results. It remains incomplete until that authenticated path is verified.

## Official references checked for this build

- [Official SDK](https://github.com/angel-one/smartapi-python), pinned 1.5.5.
- [SmartAPI documentation](https://smartapi.angelone.in/docs): daily request
  spans up to 2,000 days, not a promise of 2,000 available history days.
  Shared per-client limits enforced: 3/second, 150/minute, 5,000/hour. Some
  official pages state 180/minute; this implementation uses 150 conservatively.
- [Official instrument master](https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json).
- [Angel One charges](https://www.angelone.in/exchange-transaction-charges).
- [NSE session information](https://www.nseindia.com/resources/exchange-communication-holidays).
- [Nestle split listing notice](https://nsearchives.nseindia.com/content/circulars/CML59895.pdf).
- [TCS dividend records](https://www.tcs.com/investor-relations/dividend-payment-details).
