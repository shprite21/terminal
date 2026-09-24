"""Research-to-backtest orchestration pipeline."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from analytics.tearsheet import PerformanceReport
from backtesting import BacktestConfig, BacktestResult, VectorizedBacktester
from data.features import FeatureEngineer
from data.models import MarketDataBundle
from portfolio import AllocationConfig, RegimeConditionedAllocator
from regime_detection import MarketBreadthRegimeDetector, RegimeEnsemble, VolatilityRegimeClassifier
from regime_detection.base import RegimeResult
from risk import ExposureConstraint, RiskConfig, VolatilityTargeter
from strategies.base import BaseStrategy, StrategySignal
from strategies.library import StrategyPipeline


@dataclass
class ResearchResult:
    """Outputs from a complete research pipeline run."""

    features: dict[str, pd.DataFrame]
    regimes: pd.Series
    signals: dict[str, StrategySignal]
    weights: pd.DataFrame
    backtest: BacktestResult
    report: PerformanceReport


class ResearchPipeline:
    """Configurable research-to-execution pipeline."""

    def __init__(
        self,
        strategies: list[BaseStrategy],
        allocation_config: AllocationConfig | None = None,
        risk_config: RiskConfig | None = None,
        backtest_config: BacktestConfig | None = None,
        strategy_budgets: dict[str, float] | None = None,
        regime_enabled: bool = True,
    ) -> None:
        self.strategy_pipeline = StrategyPipeline(strategies)
        self.allocation_config = allocation_config or AllocationConfig(
            gross_leverage=1.0,
            min_weight=-0.20,
            max_weight=0.20,
        )
        self.risk_config = risk_config or RiskConfig(max_asset_weight=0.20)
        self.backtest_config = backtest_config or BacktestConfig()
        self.strategy_budgets = strategy_budgets
        self.regime_enabled = regime_enabled

    def run(self, bundle: MarketDataBundle) -> ResearchResult:
        """Run feature engineering, regimes, strategies, allocation, risk, and backtest."""

        features = FeatureEngineer().build(bundle)
        prices = bundle.close()
        returns = prices.pct_change().fillna(0.0)
        regimes = self._detect_regimes(prices, returns)
        signals = self.strategy_pipeline.generate(bundle)
        blended = StrategyPipeline.weighted_blend(signals, self.strategy_budgets)
        allocated = RegimeConditionedAllocator(self.allocation_config).allocate(
            blended.weights,
            regimes if self.regime_enabled else pd.Series(1, index=prices.index),
        )
        constrained = ExposureConstraint(self.risk_config).apply(allocated.weights)
        targeted = VolatilityTargeter(self.risk_config).scale_weights(constrained, returns)
        # Volatility scaling must never undo the mandate's hard exposure limits.
        targeted = ExposureConstraint(self.risk_config).apply(targeted)
        backtest = VectorizedBacktester(self.backtest_config).run(prices, targeted)
        report = PerformanceReport.from_backtest(backtest, regimes)
        return ResearchResult(
            features=features,
            regimes=regimes,
            signals=signals,
            weights=targeted,
            backtest=backtest,
            report=report,
        )

    @staticmethod
    def _detect_regimes(prices: pd.DataFrame, returns: pd.DataFrame) -> pd.Series:
        volatility = VolatilityRegimeClassifier().fit_predict(returns.mean(axis=1).to_frame("returns"))
        # Volatility labels are low/medium/high; ensemble labels are
        # defensive/neutral/constructive. High volatility is defensive.
        risk_state = RegimeResult(labels=2 - volatility.labels)
        breadth = MarketBreadthRegimeDetector(moving_average_window=100).fit_predict(prices)
        ensemble = RegimeEnsemble(weights={"volatility": 0.6, "breadth": 0.4}).combine(
            {"volatility": risk_state, "breadth": breadth}
        )
        return ensemble.labels
