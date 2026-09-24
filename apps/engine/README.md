# Q research engine

Python implementation of Q's systematic research, portfolio construction, validation and simulation workflows. This engine integrates the earlier regime platform and Evidence; their technical module names remain for compatibility. Q is the active product.

See the [project README](../../README.md) for research scope and [architecture](../../docs/implementation.md) for service boundaries.

## Modules

| Path | Responsibility |
| --- | --- |
| `data/`, `configs/` | Provider histories, quality checks, data containers and experiment configuration. |
| `strategies/`, `regime_detection/` | Signal families and regime classifiers. |
| `backtesting/`, `portfolio/`, `risk/`, `execution/` | Historical accounting, allocation, exposure controls and modeled fills. |
| `analytics/`, `visualization/` | Attribution, benchmark/factor diagnostics and reports. |
| `research/` | Experiment records, mandates, robustness and Strategy Survival. |
| `evidence/` | Versioned hypotheses, strict daily studies and bar/event simulations. |
| `qresearch/` | Integrated options, cointegration, regime and risk studies; retained source provenance. |
| `legacy_evidence/` | Historical standalone UI and packaging reference, outside the active Q interface. |
| `tests/`, `evidence_tests/` | Numerical invariants, chronology, provenance and API contracts. |

## Setup and validation

From the repository root, with Python 3.12+ available:

```powershell
./setup-flagship.ps1 -Python python
./apps/engine/.venv/Scripts/python.exe -m pytest apps/engine
./apps/engine/.venv/Scripts/python.exe apps/engine/scripts/run_research.py
```

Setup uses `requirements.lock.txt`. The diagnostic script uses seeded synthetic inputs and writes ignored reports and experiment records. Its full-sample pairs selection is an in-sample diagnostic limitation. It is not a validated trading strategy.

The gateway starts `serve.py` on an authenticated loopback connection when needed. Run the full interface through `start-q21.ps1`; do not expose this local research service as a public trading API.

## Reproducibility boundaries

Share accounting, fractional portfolio weights, adjusted bars and synthetic event models are distinct conventions. Preserve those distinctions when comparing results. Historical artifacts and dataset versions remain immutable; generated records belong under ignored local storage, not in source control.

Provider availability, historical universe coverage and adjustment assumptions constrain conclusions. Live broker order submission is disabled. See [data conventions](../../docs/real-market-data.md) and [Strategy Survival methodology](../../docs/strategy-survival.md).
