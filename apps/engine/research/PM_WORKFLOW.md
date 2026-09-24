# Systematic PM workflow and implementation

This design adapts publicly documented institutional investment processes to this
repository's local research engine. It is not a claim that every institution uses
the same process, or that this application replaces an institutional OMS or risk
platform. Research reviewed on 5 September 2026.

## Evidence informing the workflow

CFA Institute describes backtesting as a simulation of the investment process:
state a hypothesis, formalize rules, construct and rebalance portfolios, then
evaluate risk and performance. Its guidance also calls for sensitivity and
scenario analysis, with explicit attention to look-ahead and survivorship bias.
This supports separating the mandate, chronological validation and robustness
review in this workspace. [CFA Institute, Backtesting & Simulation](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/backtesting-and-simulation).

MSCI describes attribution as connecting investment decisions to outcomes and
combining risk and performance using consistent inputs. This supports tracing a
portfolio result back to its securities, strategy signals and benchmark, rather
than presenting disconnected charts. [MSCI, Performance Attribution](https://www.msci.com/data-and-analytics/portfolio-management/performance-attribution).

MSCI's RiskManager combines market, factor, stress and liquidity analytics.
Those are distinct requirements: a covariance estimate does not establish
liquidity capacity, and benchmark beta is not a complete equity factor model.
The dashboard therefore identifies what it actually measures and exposes the
remaining input gaps. [MSCI, RiskMetrics RiskManager](https://www.msci.com/data-and-analytics/risk-management-solutions/riskmetrics-riskmanager).

AQR's trading-cost research uses institutional execution observations and finds
that costs depend on trade and security characteristics, size, time and market.
This motivates explicit execution assumptions and cost stress; the implemented
linear cost model is a research approximation, not a calibrated impact model.
[AQR, Trading Costs](https://www.aqr.com/insights/research/working-paper/trading-costs).

The following workflow and default gate thresholds are engineering choices
inferred from these requirements. They are not thresholds prescribed by those
sources, investment recommendations, or automatic approval criteria.

## How a PM uses this workspace

| Stage | PM question | Implemented behavior and research modules |
| --- | --- | --- |
| Mandate | What is the hypothesis, universe, benchmark and risk budget? | Persisted hypothesis; same-currency universe; long-only/long-short; capital, gross/net/asset limits, target volatility and drawdown budget. |
| Alpha design | Which independent signals express the hypothesis? | Eight configurable strategy families, lookback and sleeve budgets, through `StrategyPipeline` and `ResearchPipeline`. |
| Data review | Is this the right information set? | Completed adjusted daily OHLCV; strict shared sessions; no filling or synthetic fallback; `MarketDataQualityValidator`; raw snapshot and hash. |
| Portfolio construction | How do signals become risk? | Budgeted signal blend → regime allocation → exposure constraints → volatility target → final hard constraints. Netting precedes gross normalization. |
| Backtest review | Does it survive realistic implementation assumptions? | One-session lag, scheduled trading, share drift, commission/slippage and annual short-borrow assumption in `VectorizedBacktester`. |
| Model validation | Does the result persist beyond initial history? | `WalkForwardValidator`, expanding chronological windows with fixed rules; explicit train/test dates and consistent costs. |
| Robustness | Is the result fragile? | `CostSensitivityAnalyzer` at 1×/2×/3× costs; `ParameterRobustnessTester` at 0.8×/1×/1.2× lookback; `StrategyCorrelationAnalyzer`. |
| Risk and attribution | What produced returns and where is risk concentrated? | NAV-linked security and cost attribution; `RegimeAnalytics`; benchmark `FactorExposureAnalyzer`; gross/net, effective positions, expected shortfall and component variance shares. |
| Implementation review | What would the latest targets change? | Simulated current versus target weights, indicative notional, turnover and costs; frozen-target historical and hypothetical one-day scenarios. |
| Research decision | What was accepted or rejected, and why? | Explicit watchlist / paper candidate / rejected labels, rationale, timestamped history, downloadable PM memo. No broker actions. |
| Research governance | Can I reproduce and compare it? | `ExperimentTracker`, persisted job/result, source ZIP and dependency versions; clone with archived data reuse; comparability warning for differing datasets or validation windows. |

Typical cadence:

1. Open the experiment book and inspect the last reviewed study, data dates,
   current regime and risk flags. Refresh market data as a new experiment when
   current observations are needed.
2. Write the research hypothesis before examining new parameter variants. Set
   the benchmark, universe and mandate, then select sleeves and budgets.
3. Run research. Review data diagnostics before interpreting performance.
4. Inspect OOS windows, costs, lookback sensitivity and correlations. A strategy
   with a good headline but concentrated or unstable results needs further work.
5. Review attribution, portfolio targets, factor beta, drift and scenarios. The
   latest targets are research proposals, not automatically scheduled orders.
6. Clone a completed run to reuse its exact archived data when changing a single
   assumption. The original run and evidence remain available.
7. Record the decision and rationale. Download the memo and supporting data for
   review. A paper-candidate label does not start a paper-trading service.

## Interpretation and implementation boundaries

- Headline research performance excludes `max(126, longest lookback + 2)` warmup
  observations. The initial NAV is included in the plotted curve and drawdown.
  OOS statistics cover chronological blocks after the initial history. A final
  partial block contributes returns but does not count as a complete window.
- The currently exposed rules have no learned parameters. Expanding validation
  replays fixed causal rules; it is not model fitting, nested validation or a
  sealed holdout. Repeated experimentation on those dates creates selection bias.
- Cost stress and lookback sensitivity use the full snapshot, including warmup.
  They diagnose assumptions and are not independent OOS results.
- Signal sleeves are evaluated standalone before portfolio constraints. Those
  returns do not sum to blended portfolio returns. Security P&L contributions,
  net of cost contributions, reconcile exactly to the research portfolio return.
- Model limits apply to targets. Holdings can breach them through price drift
  between scheduled trades; the risk view counts such days. A drawdown limit is
  a research gate, not an implemented stop-loss rule.
- Long-only can hold cash. Cash earns zero. Sharpe uses a zero cash hurdle and
  252 trading observations per year. Borrow is a fixed annual rate on short
  notional. Actual execution prices, financing, borrow availability/recalls,
  market impact, taxes, FX and corporate-action processing are not modeled.
- Historical and hypothetical scenarios apply one-day asset returns to frozen
  latest targets. They are not a full crisis path simulation or a forecast.
- Synthetic data is explicitly selected and always blocks paper candidacy.
  Yahoo failures remain failed experiments, never substituted observations.
- Other blockers are fewer than three full test blocks, OOS Sharpe below the
  configured floor, OOS drawdown exceeding the configured budget, target-limit
  violations or nonpositive full-history return under 3× trading costs. Data
  diagnostics and universe bias still require judgment even if hard gates pass.

## Requirements for live institutional use that remain outside this integration

| Requirement | What is needed |
| --- | --- |
| Point-in-time research universe | Licensed historical membership, delistings, identifiers and corporate actions; explicit information availability timestamps. |
| Full equity factor and sector model | Verified style-factor returns/exposures and sector classifications; risk forecasts and constraints matched to the mandate. Price proxies are not substituted for these inputs. |
| Liquidity and capacity | ADV/spread/impact estimates matched to trade size and actual execution observations. |
| Earnings, macro, HMM and pair research | Publication-lagged event/macro datasets or train-only fitting contracts. These are visible as unavailable, not executed with fabricated inputs. |
| Production monitoring | Broker/custodian positions, cash and fill reconciliation; live P&L, signal drift and alert delivery. Current comparisons use simulated holdings only. |
| Investment controls | Authenticated users, roles, independent review, immutable external audit, compliance checks and approval routing. Local timestamped decisions are not an institutional audit service. |
| Live implementation | OMS/EMS integration, order staging, pre-trade checks, kill switches and operational reconciliation. No execution endpoint is provided. |

The job queue is for a single local API process. Completed records survive a
restart; interrupted jobs become failed. Do not run multiple API workers against
the same local experiment directory. The dashboard and Python service remain
local, preserving the repository's existing deployment model.
