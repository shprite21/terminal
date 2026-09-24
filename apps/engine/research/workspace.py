"""PM research workflow using the repository's research and analytics modules."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from analytics.correlation import StrategyCorrelationAnalyzer
from analytics.cost_sensitivity import CostSensitivityAnalyzer, CostSensitivityConfig
from analytics.factor_exposure import FactorExposureAnalyzer, FactorExposureConfig
from analytics.metrics import aggregate_metrics, drawdown_series
from analytics.portfolio_diagnostics import (
    expected_shortfall,
    exposure_concentration,
    leverage_utilization,
)
from analytics.regime_analysis import RegimeAnalytics
from backtesting import (
    BacktestConfig,
    VectorizedBacktester,
    WalkForwardConfig,
    WalkForwardValidator,
)
from data.models import MarketDataBundle
from data.research_source import load_research_bundle, make_demo_bundle
from data.validation import MarketDataQualityValidator
from portfolio import AllocationConfig
from portfolio.custom import HoldingInput, MarketDataError
from research.pipeline import ResearchPipeline
from research.robustness import ParameterRobustnessTester
from risk import RiskConfig
from strategies import (
    ATRBreakoutStrategy,
    BollingerBandStrategy,
    CrossSectionalMomentumStrategy,
    MeanReversionStrategy,
    MovingAverageTrendStrategy,
    RSIReversalStrategy,
    TimeSeriesMomentumStrategy,
    VolatilityCompressionStrategy,
)
from strategies.base import StrategyConfig, StrategySignal

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGIMES = {0: "Defensive", 1: "Neutral", 2: "Constructive"}
CATALOG = {
    "cross_sectional_momentum": (
        CrossSectionalMomentumStrategy,
        "Cross-sectional momentum",
        "Momentum",
        126,
        "Ranks trailing returns; buys winners and optionally shorts losers.",
    ),
    "time_series_momentum": (
        TimeSeriesMomentumStrategy,
        "Time-series momentum",
        "Momentum",
        126,
        "Own-price trend, sized by trailing realized volatility.",
    ),
    "moving_average_trend": (
        MovingAverageTrendStrategy,
        "Moving-average trend",
        "Momentum",
        200,
        "Quarter-window versus full-window moving-average trend.",
    ),
    "mean_reversion": (
        MeanReversionStrategy,
        "Return mean reversion",
        "Reversal",
        20,
        "Reverses extreme trailing return z-scores (entry 1.5).",
    ),
    "bollinger_band": (
        BollingerBandStrategy,
        "Bollinger reversal",
        "Reversal",
        20,
        "Trades deviations beyond two rolling standard deviations.",
    ),
    "rsi_reversal": (
        RSIReversalStrategy,
        "RSI reversal",
        "Reversal",
        14,
        "Buys below RSI 30 and optionally shorts above RSI 70.",
    ),
    "atr_breakout": (
        ATRBreakoutStrategy,
        "ATR breakout",
        "Volatility",
        20,
        "Breakouts beyond 1.5 ATR from the rolling midpoint; uses actual OHLC.",
    ),
    "volatility_compression": (
        VolatilityCompressionStrategy,
        "Volatility compression",
        "Volatility",
        63,
        "Trades 20-session breakouts following compressed 10-session volatility.",
    ),
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Sleeve(StrictModel):
    strategy: str
    budget: float = Field(gt=0, le=100)
    lookback: int = Field(ge=5, le=252)

    @field_validator("strategy")
    @classmethod
    def available_strategy(cls, value: str) -> str:
        if value not in CATALOG:
            raise ValueError("Select an available, data-supported research strategy")
        return value


class ResearchRequest(StrictModel):
    name: str = Field(default="Regime allocation study", min_length=1, max_length=80)
    hypothesis: str = Field(min_length=10, max_length=2000)
    data_mode: Literal["yahoo", "massive", "synthetic", "demo"] = "yahoo"
    symbols: list[str] = Field(min_length=2, max_length=30)
    benchmark: str = "SPY"
    period: Literal["2y", "5y", "10y"] = "5y"
    sleeves: list[Sleeve] = Field(min_length=1, max_length=8)
    long_only: bool = True
    initial_capital: float = Field(default=1_000_000, ge=1000, le=1e9)
    volatility_target: float = Field(default=0.10, ge=0.01, le=0.60)
    max_asset_weight: float = Field(default=0.20, ge=0.01, le=1)
    max_gross_exposure: float = Field(default=1.0, ge=0.1, le=2)
    max_net_exposure: float = Field(default=1.0, ge=0, le=2)
    drawdown_limit: float = Field(default=0.15, ge=0.01, le=0.80)
    rebalance: Literal["daily", "weekly", "monthly"] = "weekly"
    commission_bps: float = Field(default=2.0, ge=0, le=100)
    slippage_bps: float = Field(default=3.0, ge=0, le=100)
    annual_borrow_bps: float = Field(default=100, ge=0, le=5000)
    regime_enabled: bool = True
    defensive_multiplier: float = Field(default=0.5, ge=0, le=1)
    constructive_multiplier: float = Field(default=1.0, ge=0, le=1.5)
    train_window: int = Field(default=252, ge=126, le=756)
    test_window: int = Field(default=63, ge=21, le=252)
    min_oos_sharpe: float = Field(default=0.5, ge=-2, le=5)
    snapshot_run_id: str | None = Field(default=None, pattern=r"^\d{8}T\d{6}Z-[a-f0-9]{8}$")

    @field_validator("symbols", mode="before")
    @classmethod
    def normalize_symbols(cls, value):
        if not isinstance(value, list):
            raise ValueError("Universe must be a list of tickers")  # noqa: TRY004 - Pydantic validation
        return [HoldingInput(ticker=symbol, weight=100).ticker for symbol in value]

    @field_validator("benchmark", mode="before")
    @classmethod
    def normalize_benchmark(cls, value):
        return HoldingInput(ticker=value, weight=100).ticker

    @field_validator("name", "hypothesis")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Name and hypothesis cannot be blank")
        return value.strip()

    @model_validator(mode="after")
    def consistent_mandate(self):
        if len(self.symbols) != len(set(self.symbols)):
            raise ValueError("Universe tickers must be unique")
        if len({s.strategy for s in self.sleeves}) != len(self.sleeves):
            raise ValueError("Each strategy can appear only once")
        if abs(sum(s.budget for s in self.sleeves) - 100) > 1e-6:
            raise ValueError("Strategy budgets must total 100%")
        if self.max_net_exposure > self.max_gross_exposure:
            raise ValueError("Net limit cannot exceed the gross limit")
        if self.long_only and self.max_net_exposure == 0:
            raise ValueError("A long-only mandate needs a positive net limit")
        if self.train_window < max(s.lookback for s in self.sleeves) + 2:
            raise ValueError(
                "Training window must exceed the longest signal lookback by at least 2 sessions"
            )
        return self


def strategy_catalog() -> dict:
    return {
        "strategies": [
            {"id": key, "name": row[1], "family": row[2], "lookback": row[3], "description": row[4]}
            for key, row in CATALOG.items()
        ],
        "unavailable": [
            {
                "name": "Earnings / PEAD",
                "reason": "Needs point-in-time earnings surprises and release timestamps.",
            },
            {
                "name": "Pairs / cointegration",
                "reason": "Needs a train-only pair-selection and hedge-ratio calibration contract.",
            },
            {
                "name": "Macro / HMM regimes",
                "reason": "Needs publication-lagged macro inputs and train-only state calibration.",
            },
            {
                "name": "Sector rotation",
                "reason": "Needs a verified sector ETF universe and benchmark mapping.",
            },
        ],
        "demo_symbols": ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "JPM", "XOM", "UNH"],
    }


def pipeline_for(request: ResearchRequest, lookback_scale: float = 1) -> ResearchPipeline:
    strategies = []
    for sleeve in request.sleeves:
        lookback = max(5, round(sleeve.lookback * lookback_scale))
        params = {}
        if sleeve.strategy == "moving_average_trend":
            params = {"short_window": max(2, lookback // 4), "long_window": lookback}
        config = StrategyConfig(
            name=sleeve.strategy, lookback=lookback, long_short=not request.long_only, params=params
        )
        strategies.append(CATALOG[sleeve.strategy][0](config))
    return ResearchPipeline(
        strategies,
        allocation_config=AllocationConfig(
            gross_leverage=request.max_gross_exposure,
            long_only=request.long_only,
            min_weight=0 if request.long_only else -request.max_asset_weight,
            max_weight=request.max_asset_weight,
            regime_multipliers={
                0: request.defensive_multiplier,
                1: 1.0,
                2: request.constructive_multiplier,
            },
        ),
        risk_config=RiskConfig(
            volatility_target=request.volatility_target,
            max_asset_weight=request.max_asset_weight,
            max_gross_exposure=request.max_gross_exposure,
            max_net_exposure=request.max_net_exposure,
            drawdown_alert=request.drawdown_limit,
        ),
        backtest_config=BacktestConfig(
            initial_capital=request.initial_capital,
            rebalance_frequency={"daily": None, "weekly": "W-FRI", "monthly": "ME"}[
                request.rebalance
            ],
            execution_lag=1,
            transaction_cost_bps=request.commission_bps,
            slippage_bps=request.slippage_bps,
            allow_short=not request.long_only,
            annual_borrow_bps=request.annual_borrow_bps,
            drift_between_rebalances=True,
        ),
        strategy_budgets={s.strategy: s.budget for s in request.sleeves},
        regime_enabled=request.regime_enabled,
    )


def subset_bundle(bundle: MarketDataBundle, index: pd.Index) -> MarketDataBundle:
    return MarketDataBundle(
        ohlcv={key: frame.loc[index].copy() for key, frame in bundle.ohlcv.items()},
        benchmark=bundle.benchmark.loc[index].copy() if bundle.benchmark is not None else None,
        metadata=bundle.metadata.copy(),
    )


def clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(item) for item in value]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if value is pd.NA or value is pd.NaT:
        return None
    return value


def rows(frame: pd.DataFrame, index_name: str | None = None) -> list[dict]:
    if index_name:
        frame = frame.rename_axis(index_name).reset_index()
    return clean_json(frame.to_dict(orient="records"))


def code_provenance(output_dir: Path) -> dict:
    digest = hashlib.sha256()
    paths = [PROJECT_ROOT / name for name in ("pyproject.toml", "flagship_api.py", "serve.py", "requirements.lock.txt") if (PROJECT_ROOT / name).is_file()]
    for directory in (
        "analytics",
        "evidence",
        "execution",
        "qresearch",
        "backtesting",
        "configs",
        "data",
        "portfolio",
        "research",
        "risk",
        "strategies",
        "regime_detection",
        "apps",
        "scripts",
    ):
        paths.extend(sorted((PROJECT_ROOT / directory).glob("**/*.py")))
    with zipfile.ZipFile(
        output_dir / "source.zip", "w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for path in paths:
            relative = path.relative_to(PROJECT_ROOT).as_posix()
            content = path.read_bytes()
            digest.update(relative.encode())
            digest.update(content)
            archive.writestr(relative, content)
    try:
        revision = (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3
            )
            .decode()
            .strip()
        )
        dirty = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"],
                cwd=PROJECT_ROOT,
                stdin=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
            ).strip()
        )
    except (OSError, subprocess.SubprocessError):
        revision, dirty = "unavailable", None
    return {
        "git_revision": revision,
        "working_tree_dirty": dirty,
        "source_sha256": digest.hexdigest(),
        "python": sys.version,
        "dependencies": {
            name: version(name) for name in ("numpy", "pandas", "scipy", "pydantic", "yfinance", "statsmodels", "scikit-learn", "hmmlearn")
        },
    }


def research_metrics(returns: pd.Series) -> dict:
    """Include starting capital in drawdown even when the first return is a loss."""
    equity = pd.Series(np.r_[1.0, (1 + returns).cumprod().to_numpy()])
    return aggregate_metrics(returns, equity)


def run_research(
    request: ResearchRequest,
    output_dir: Path,
    progress=lambda stage: None,
    bundle: MarketDataBundle | None = None,
) -> dict:
    """Compute and archive one immutable research result from a single data snapshot."""
    output_dir.mkdir(parents=True, exist_ok=True)
    progress("Loading and validating OHLCV")
    bundle = bundle or (
        make_demo_bundle()
        if request.data_mode == "demo"
        else load_research_bundle(request.symbols, request.benchmark, request.period, source=request.data_mode)
    )
    prices = bundle.close()
    warmup = max(126, max(s.lookback for s in request.sleeves) + 2)
    if len(prices) < request.train_window + request.test_window * 2:
        raise MarketDataError(
            "Need at least two full validation windows after training. Increase history or reduce window lengths."
        )
    if bundle.benchmark is None:
        raise MarketDataError("A verified benchmark series is required.")
    if request.data_mode != "demo" and set(prices.columns) != set(request.symbols):
        raise MarketDataError("Loaded universe does not match the requested mandate.")
    quality = MarketDataQualityValidator().validate(bundle.ohlcv)
    snapshot = pd.concat(bundle.ohlcv, names=["symbol", "date"]).sort_index()
    snapshot.to_csv(output_dir / "prices.csv", float_format="%.17g")
    bundle.benchmark.to_csv(output_dir / "benchmark.csv", float_format="%.17g")
    snapshot_hash = hashlib.sha256(
        (output_dir / "prices.csv").read_bytes() + (output_dir / "benchmark.csv").read_bytes()
    ).hexdigest()
    provenance = code_provenance(output_dir)
    progress("Generating signals, regimes and constrained portfolio")
    pipeline = pipeline_for(request)
    result = pipeline.run(bundle)
    backtest = result.backtest
    evaluation_index = prices.index[warmup:]
    net = backtest.returns.loc[evaluation_index]
    gross = backtest.gross_returns.loc[evaluation_index]
    benchmark_returns = bundle.benchmark["Close"].pct_change(fill_method=None).fillna(0)
    benchmark = benchmark_returns.loc[evaluation_index]
    metrics = research_metrics(net)
    active = net - benchmark
    tracking_error = float(active.std() * np.sqrt(252))
    metrics.update(
        {
            "benchmark_return": float((1 + benchmark).prod() - 1),
            "active_return": float((1 + net).prod() - (1 + benchmark).prod()),
            "tracking_error": tracking_error,
            "information_ratio": float(active.mean() * 252 / tracking_error)
            if tracking_error > 0
            else None,
            "gross_return": float((1 + gross).prod() - 1),
            "annual_turnover": float(backtest.turnover.loc[evaluation_index].mean() * 252),
            "expected_shortfall_95": expected_shortfall(net),
        }
    )
    result.weights.to_csv(output_dir / "targets.csv", float_format="%.17g")
    backtest.weights.to_csv(output_dir / "executed_weights.csv", float_format="%.17g")
    progress("Walk-forward validation with frozen strategy rules")

    def factory(frame, parameters=None):
        run = pipeline_for(request).run(subset_bundle(bundle, frame.index))
        return StrategySignal("research_portfolio", run.weights)

    validation = WalkForwardValidator(
        WalkForwardConfig(
            train_window=request.train_window,
            min_train_window=request.train_window,
            test_window=request.test_window,
            mode="expanding",
        ),
        backtest_config=pipeline.backtest_config,
    ).evaluate(prices, factory, regimes=result.regimes.shift(1))
    progress("Cost stress, parameter sensitivity and attribution")
    cost_stress = []
    for multiplier in (1, 2, 3):
        analyzer = CostSensitivityAnalyzer(
            CostSensitivityConfig(
                commission_bps=(request.commission_bps * multiplier,),
                slippage_bps=(request.slippage_bps * multiplier,),
                spread_bps=(0,),
                initial_capital=request.initial_capital,
            ),
            pipeline.backtest_config,
        )
        # Run on the complete snapshot to retain execution history; cost sweep
        # is explicitly full-history, separate from warmup-excluded headline.
        scenario = rows(analyzer.sweep(prices, result.weights))[0]
        cost_stress.append({"multiplier": multiplier, **scenario})
    robustness = ParameterRobustnessTester(backtest_config=pipeline.backtest_config).grid_search(
        prices,
        {"lookback_scale": [0.8, 1.0, 1.2]},
        lambda parameters: StrategySignal(
            "sensitivity",
            pipeline_for(request, float(parameters["lookback_scale"])).run(bundle).weights,
        ),
    )
    sleeve_returns, sleeve_rows = {}, []
    for sleeve in request.sleeves:
        signal = result.signals[sleeve.strategy]
        standalone = VectorizedBacktester(pipeline.backtest_config).run(prices, signal.weights)
        sleeve_net = standalone.returns.loc[evaluation_index]
        sleeve_returns[sleeve.strategy] = sleeve_net
        sleeve_rows.append(
            {
                "strategy": sleeve.strategy,
                "name": CATALOG[sleeve.strategy][1],
                "budget": sleeve.budget,
                "lookback": sleeve.lookback,
                **research_metrics(sleeve_net),
            }
        )
    sleeve_panel = pd.DataFrame(sleeve_returns)
    correlations = StrategyCorrelationAnalyzer().analyze(sleeve_panel)
    lagged_regimes = result.regimes.shift(1).reindex(evaluation_index).fillna(1)
    regimes = RegimeAnalytics().analyze(
        lagged_regimes, net, sleeve_panel, backtest.weights.loc[evaluation_index]
    )
    factors = FactorExposureAnalyzer(FactorExposureConfig(rolling_window=63)).analyze(
        net, benchmark.to_frame("benchmark"), lagged_regimes
    )
    exposures = leverage_utilization(backtest.weights)
    current = pd.Series(backtest.metadata["ending_weights"])
    target = result.weights.iloc[-1].reindex(prices.columns)
    changes = target - current
    returns = prices.pct_change(fill_method=None).fillna(0)
    covariance = returns.tail(63).cov() * 252
    variance = float(target @ covariance @ target)
    risk_contribution = (
        (target * (covariance @ target) / variance) if variance > 0 else target * np.nan
    )
    equity_before = backtest.equity_curve.shift(1).fillna(request.initial_capital)
    baseline = float(equity_before.loc[evaluation_index[0]])
    attribution = (
        backtest.attribution.loc[evaluation_index]
        .mul(equity_before.loc[evaluation_index], axis=0)
        .sum()
        / baseline
    )
    drag = float(
        (
            (backtest.costs + backtest.slippage).loc[evaluation_index]
            * equity_before.loc[evaluation_index]
        ).sum()
        / baseline
    )
    # Current holdings risk on observed historical shocks, with frozen targets.
    shocks = []
    worst_market = benchmark_returns.iloc[1:].idxmin()
    for label, vector in [
        ("Benchmark's worst observed day", returns.loc[worst_market]),
        ("All equities down 5%", pd.Series(-0.05, index=prices.columns)),
        ("All equities up 5%", pd.Series(0.05, index=prices.columns)),
    ]:
        shocks.append(
            {
                "scenario": label,
                "return": float(target @ vector),
                "date": worst_market.strftime("%Y-%m-%d")
                if label.startswith("Benchmark")
                else None,
            }
        )
    oos = validation.summary()
    oos_metrics = research_metrics(validation.oos_returns)
    full_folds = sum(len(w.test_result.returns) == request.test_window for w in validation.windows)
    quality_issues = (
        len(quality.stale_prices) + len(quality.outliers) + len(quality.adjustment_warnings)
    )
    targets_ok = (
        result.weights.abs().max().max() <= request.max_asset_weight + 1e-8
        and result.weights.abs().sum(axis=1).max() <= request.max_gross_exposure + 1e-8
        and result.weights.sum(axis=1).abs().max() <= request.max_net_exposure + 1e-8
    )
    gates = [
        {
            "name": "Market observations",
            "status": "pass" if request.data_mode in {"yahoo", "massive"} else "blocked",
            "detail": f"Frozen {request.data_mode} market snapshot; provider coverage limitations apply"
            if request.data_mode in {"yahoo", "massive"}
            else "Synthetic data is for exercising the workflow only.",
        },
        {
            "name": "Complete validation windows",
            "status": "pass" if full_folds >= 3 else "blocked",
            "detail": f"{full_folds} complete chronological test windows; at least 3 required.",
        },
        {
            "name": "Out-of-sample Sharpe",
            "status": "pass" if oos_metrics["sharpe"] >= request.min_oos_sharpe else "blocked",
            "detail": f"{oos_metrics['sharpe']:.2f} versus mandate floor {request.min_oos_sharpe:.2f}.",
        },
        {
            "name": "Drawdown budget",
            "status": "pass"
            if abs(oos_metrics["max_drawdown"]) <= request.drawdown_limit
            else "blocked",
            "detail": f"OOS drawdown {oos_metrics['max_drawdown']:.1%}; limit {request.drawdown_limit:.1%}.",
        },
        {
            "name": "Hard target constraints",
            "status": "pass" if targets_ok else "blocked",
            "detail": "Checks every target date after volatility scaling; holdings may drift between trades.",
        },
        {
            "name": "3× trading costs",
            "status": "pass" if cost_stress[-1]["total_return"] > 0 else "blocked",
            "detail": f"Full-history stressed net return {cost_stress[-1]['total_return']:.1%}; borrow rate held constant.",
        },
        {
            "name": "Data diagnostics",
            "status": "review" if quality_issues else "pass",
            "detail": f"{quality_issues} stale-price, return-outlier or adjustment flags.",
        },
        {
            "name": "Universe provenance",
            "status": "review",
            "detail": "Selected constituents are not a point-in-time historical universe. Review selection/survivorship bias.",
        },
    ]
    curve = pd.DataFrame(
        {
            "portfolio": (1 + net).cumprod() * request.initial_capital,
            "benchmark": (1 + benchmark).cumprod() * request.initial_capital,
            "gross": (1 + gross).cumprod() * request.initial_capital,
        }
    )
    # Include an explicit starting NAV, so first-day losses enter drawdown.
    curve.loc[prices.index[warmup - 1]] = request.initial_capital
    curve = curve.sort_index()
    curve["drawdown"] = drawdown_series(curve["portfolio"])
    curve["regime"] = result.regimes.shift(1).reindex(curve.index)
    curve["date"] = curve.index.strftime("%Y-%m-%d")
    curve.to_csv(output_dir / "returns.csv", index=False)
    progress("Archiving evidence and research gates")
    latest_date = prices.index[-1]
    data_age_days = (pd.Timestamp.now().normalize() - latest_date.normalize()).days
    target_gross = float(target.abs().sum())
    holdings = [
        {
            "symbol": symbol,
            "current_weight": float(current[symbol]),
            "target_weight": float(target[symbol]),
            "change": float(changes[symbol]),
            "indicative_notional": float(changes[symbol] * backtest.equity_curve.iloc[-1]),
            "risk_contribution": float(risk_contribution[symbol]),
            "return_contribution": float(attribution[symbol]),
            "signals": {
                name: float(signal.weights.iloc[-1].get(symbol, 0))
                for name, signal in result.signals.items()
            },
        }
        for symbol in prices.columns
    ]
    response = {
        "request": request.model_dump(),
        "data": {
            **bundle.metadata,
            "start_date": prices.index[0].strftime("%Y-%m-%d"),
            "end_date": latest_date.strftime("%Y-%m-%d"),
            "evaluation_start": evaluation_index[0].strftime("%Y-%m-%d"),
            "observations": len(prices),
            "warmup_observations": warmup,
            "age_calendar_days": data_age_days,
            "symbols": list(prices.columns),
            "snapshot_sha256": snapshot_hash,
        },
        "provenance": {**provenance, "execution": asdict(pipeline.backtest_config)},
        "metrics": metrics,
        "equity_curve": rows(curve),
        "validation": {
            "method": "Expanding chronological walk-forward; fixed rules, no parameter fitting",
            "metrics": oos_metrics,
            "stability": oos,
            "complete_windows": full_folds,
            "observations": len(validation.oos_returns),
            "windows": rows(validation.window_metrics, "window_id"),
        },
        "cost_stress": cost_stress,
        "robustness": rows(robustness.results),
        "sleeves": sleeve_rows,
        "correlations": rows(correlations.static_correlation, "strategy"),
        "regime": {
            "current": REGIMES[int(result.regimes.iloc[-1])],
            "enabled": request.regime_enabled,
            "multiplier": pipeline.allocation_config.regime_multipliers[
                int(result.regimes.iloc[-1])
            ]
            if request.regime_enabled
            else 1,
            "performance": rows(regimes.conditional_performance, "regime"),
            "transitions": rows(regimes.transition_probabilities, "regime"),
        },
        "risk": {
            "target_gross": target_gross,
            "target_net": float(target.sum()),
            "current_gross": float(current.abs().sum()),
            "current_net": float(current.sum()),
            "predicted_volatility": float(np.sqrt(max(0, variance))),
            "effective_positions": float(1 / exposure_concentration(target.to_frame().T).iloc[0])
            if target_gross > 0
            else 0,
            "benchmark_beta": factors.static_betas.get("benchmark"),
            "rolling_benchmark_beta": factors.rolling_betas["benchmark"].iloc[-1]
            if not factors.rolling_betas.empty
            else None,
            "gross_limit_days": int(
                (exposures.gross_exposure > request.max_gross_exposure + 1e-8).sum()
            ),
            "net_limit_days": int(
                (exposures.net_exposure.abs() > request.max_net_exposure + 1e-8).sum()
            ),
            "asset_limit_days": int(
                (backtest.weights.abs().max(axis=1) > request.max_asset_weight + 1e-8).sum()
            ),
        },
        "holdings": holdings,
        "attribution": {
            "cost_contribution": -drag,
            "total_return": metrics["total_return"],
            "asset_contribution": float(attribution.sum()),
        },
        "proposal": {
            "as_of": latest_date.strftime("%Y-%m-%d"),
            "turnover": float(changes.abs().sum()),
            "estimated_cost": float(
                changes.abs().sum() * (request.commission_bps + request.slippage_bps) / 10000
            ),
            "basis": "Latest research targets versus simulated end-of-day holdings. Indicative only; not broker positions or orders.",
        },
        "scenarios": shocks,
        "gates": gates,
        "paper_candidate_eligible": not any(g["status"] == "blocked" for g in gates),
        "quality": {
            "stale_prices": rows(quality.stale_prices)[:100],
            "outliers": rows(quality.outliers)[:100],
            "adjustment_warnings": rows(quality.adjustment_warnings)[:100],
            "flag_count": quality_issues,
        },
        "limitations": [
            "Daily adjusted OHLCV, one quote currency, 252-session annualization. Cash earns zero; Sharpe uses zero cash hurdle.",
            "Headline metrics exclude a common warmup. Walk-forward keeps pre-test signal and position history; parameters are fixed, not optimized on training windows.",
            "Repeated examination of the test period makes it research data. No unseen holdout, multiple-testing correction or investment approval is implied.",
            "Positions drift between rebalances. Trades use prior completed-close targets with a one-session lag and linear costs. Borrow is a constant annual assumption; recalls, financing, taxes and market impact are unmodeled.",
            "Standalone sleeve returns use their own unconstrained positions and costs; they do not add to blended portfolio attribution. Asset and cost contributions reconcile to portfolio return.",
            "Parameter sensitivity and cost stress use the full historical snapshot, including warmup; they are diagnostics, not independent out-of-sample evidence.",
            "Only benchmark beta is estimated. No verified style-factor, sector, liquidity-capacity or broker risk model is connected.",
            "Rebalance proposals compare with simulated holdings. Current signals can be stale; fresh data and actual holdings are required before implementation.",
        ],
    }
    response = clean_json(response)
    (output_dir / "result.json").write_text(
        json.dumps(response, indent=2, allow_nan=False), encoding="utf-8"
    )
    return response
