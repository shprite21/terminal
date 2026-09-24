# Q | Quantitative Research Terminal

**Systematic equities research, portfolio construction, and strategy validation.**

Q is a local research environment for developing market hypotheses, constructing portfolios, testing strategies, and reviewing the evidence behind an allocation decision. It brings a Python research engine, a TypeScript daily backtester, and a common terminal interface into one repository.

The research process centers on explicit data provenance, chronological evaluation, transaction costs, immutable experiment records, and independent accounting checks. Q is under active development. Broker adapters provide read-only account access; live order submission is disabled.

## Research framework

| Area | Implemented scope |
| --- | --- |
| Strategy research | Momentum, mean reversion, trend, breakout, event-driven and sector strategies; pairs and cointegration libraries with workflow-specific restrictions. |
| Regime analysis | Trend, volatility, breadth and ensemble models; HMM research with explicit calibration and provenance requirements. |
| Portfolio construction | Equal and inverse-volatility weights, risk-parity and constrained-allocation libraries, exposure limits, and historical allocation replay. |
| Backtesting | Daily next-open share accounting, lagged portfolio-return accounting, and separate bar/event simulation engines. |
| Validation | Chronological walk-forward evaluation, parameter and cost sensitivity, benchmark and factor diagnostics, and an 18-layer Strategy Survival pipeline. |
| Research records | Frozen inputs, source/configuration fingerprints, versioned hypotheses, experiment comparisons, saved artifacts and decision history. |
| Advanced studies | Cointegration, option pricing and Greeks, hedging, regime models, and explicitly synthetic market-making/latency scenarios. |

Capabilities differ across engines and interfaces. Python library availability does not imply a validated real-data terminal workflow. In particular, the retained full-library synthetic scenario selects pairs on its complete sample: its output is an in-sample diagnostic, not out-of-sample evidence.

## Research methodology

A typical study proceeds from a written hypothesis to a specified universe, source, price convention, signal, portfolio rule and cost model. Historical evaluation then separates development and holdout periods, examines sensitivity to assumptions, and retains both favorable and negative results.

- **Chronology:** signals use information available at the decision time. The terminal daily engine fills no earlier than the next eligible supplied bar; portfolio engines use lagged exposures.
- **Accounting:** share-based simulations enforce available cash and whole-share rounding. Fractional portfolio-weight research is a separate model. Fees, slippage, corporate actions and benchmark conventions are reported by engine.
- **Provenance:** dataset versions and strategy/configuration identities accompany results. Editing a strategy does not rewrite historical snapshots.
- **Validation:** the Strategy Survival pipeline exposes integrity failures, statistical diagnostics, warnings and unmet prerequisites individually. It does not collapse them into an opaque score or authorize execution.
- **Reproducibility:** synthetic scenarios are explicitly selected and seeded. Provider failures remain failures; synthetic data is never substituted silently.

### Accounting boundaries

| Engine / workflow | Convention |
| --- | --- |
| Terminal daily backtests | Raw OHLC, next-open whole-share fills, cash constraints, per-side costs, splits and dividend receivables. |
| Portfolio research | Lagged portfolio weights, fractional exposures, configurable allocation/risk rules and transaction costs. |
| Allocation replay | Historical weighted allocation using provider-specific adjusted prices; research allocations are not broker orders. |
| Strict daily research | Explicit sessions and data availability, raw prices, effective-dated costs and a corporate-action ledger. |
| Bar lab | Adjusted provider bars or seeded synthetic bars, independent period warm-up/cash, next observed open and prior-volume participation. |
| Market-making studies | Seeded event, queue and latency simulations with modeled fills and inventory constraints. |

Results across these engines are comparable only after reconciling price basis, currency, dividends, costs, timing and sizing. See [data conventions](docs/real-market-data.md) and [validation methodology](docs/strategy-survival.md).

## Architecture

```text
terminal/
├── apps/
│   ├── engine/          Python research, portfolio, validation and simulation
│   │   ├── data/        Providers, normalized containers and quality checks
│   │   ├── strategies/  Modular signal families
│   │   ├── backtesting/ Historical accounting and walk-forward evaluation
│   │   ├── portfolio/   Allocation and portfolio construction
│   │   ├── research/    Experiments, robustness and survival validation
│   │   ├── qresearch/   Integrated advanced research modules
│   │   ├── evidence/    Versioned studies and bar/event simulations
│   │   └── tests/       Numerical, chronology and service tests
│   ├── gateway/         Local data, compute and integration boundaries
│   └── web/             React/TypeScript terminal and daily quant engine
├── docs/                Methodology, architecture and operating instructions
├── setup-flagship.ps1    Locked Python environment setup
└── start-q21.ps1         Local terminal launcher
```

The browser presents research state. A loopback Node gateway handles provider access and bounded daily-backtest workers; an authenticated Python service starts on demand and shares a bounded research executor. Local datasets and artifacts live under `.data/`, outside source control. Broker access and account simulation remain separate from research calculations.

The web application uses React, TypeScript, Tailwind and Vinext. The Python engine uses NumPy, pandas, SciPy, statsmodels, scikit-learn, CVXPY and related research libraries. The Sites hosting manifest and Vite plugin are retained; a hosted web build does not provision the local Python/gateway services.

## Data and scope

Q supports explicit Yahoo, Massive, CSV and synthetic inputs where the selected workflow allows them. Massive integration currently requests US daily history within a two-year window. NSE history can be imported explicitly. Provider-specific adjustment conventions are preserved: terminal Massive backtests account for raw-price splits and dividend receivables, while Python Massive views use split-adjusted prices and exclude cash dividends.

Synthetic prices, order books, option flows and latency scenarios are research fixtures. They are not observed market data or evidence of executable performance. Complete historical constituents, delisted coverage, point-in-time fundamentals, production session controls and broker-grade reconciliation remain limitations. Current exchange catalogues are not historical universe membership.

## Run locally

Prerequisites: **Node.js 24+**, npm, **Python 3.12+**, Git and PowerShell for the supplied launchers. A fresh clone contains source and fixtures, not a preinstalled environment or private research history.

```powershell
git clone https://github.com/shprite21/terminal.git
cd terminal
cd apps/web
npm run install:ci
cd ../..
./setup-flagship.ps1 -Python python
./start-q21.ps1
```

Open `http://127.0.0.1:5173`. The gateway listens on loopback port 5174 and starts Python when research is requested. Select a synthetic source explicitly to explore supported scenarios without market-data credentials. Paid-provider access, Codex conversations and read-only broker connections require their own setup; see [connections](docs/connections.md).

For an offline Python library diagnostic after setup:

```powershell
./apps/engine/.venv/Scripts/python.exe apps/engine/scripts/run_research.py
```

This writes generated research reports under `apps/engine/reports/` and experiment records under `apps/engine/outputs/`. It is the synthetic full-library scenario described above; its headline results must not be presented as investable or out-of-sample performance.

## Validation

From `apps/web`:

```sh
node --test tests/*.test.mjs
npx tsc --noEmit --incremental false
npm run build
```

From the repository root, after Python setup:

```powershell
./apps/engine/.venv/Scripts/python.exe -m pytest apps/engine
node --test apps/gateway/tests/*.test.mjs
```

The suites cover temporal leakage, cash/share reconciliation, costs, corporate actions, deterministic fixtures, artifact preservation and service boundaries. Runtime gateway tests launch the local Python service. The superseded standalone Streamlit UI suite is excluded by the engine's pytest configuration.

## Repository scope

The public repository contains implementation source, required assets, numerical tests, small documented fixtures, dependency locks, source provenance, and reproducibility instructions. Provider downloads, account records, strategy-development workspaces, credentials, local databases, generated reports, dependency installations, caches, internal design prompts and machine-specific acceptance records remain local and ignored.

Q is the active system. `q21`, `flagship` and `evidence` identifiers remain for stored-data and import compatibility. Earlier projects are preserved as research origins:

- [Quant Research](https://github.com/shprite21/quant-research)
- [Regime-Aware Systematic Equities Trading Platform](https://github.com/shprite21/Regime-Aware-Systematic-Equities-Trading-Platform)
- [Systematic Equities Research Lab](https://github.com/shprite21/systematic-equities-research-lab)

Further documentation: [architecture](docs/implementation.md), [operation and workflow map](docs/flagship.md), [advanced research integration](docs/q-research-integration.md), and [Strategy Survival](docs/strategy-survival.md).

**Author:** Arnaav Raj. Research software; results depend on data and modeling assumptions and are not investment recommendations. Live execution remains disabled pending deterministic risk, compliance, settlement, reconciliation and approval services.
