from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd

from qresearch.origins.regime.strategies.base import BaseStrategy, StrategyOutput


@dataclass(slots=True)
class BacktestResult:
    """Container for backtest time series outputs."""

    asset_returns: pd.DataFrame
    strategy_returns: pd.DataFrame
    strategy_weights: pd.DataFrame
    combined_positions: pd.DataFrame
    gross_returns: pd.Series
    portfolio_returns: pd.Series
    transaction_costs: pd.Series
    turnover: pd.Series
    pnl: pd.Series
    equity_curve: pd.Series
    drawdown: pd.Series
    regime_series: pd.Series | None = None


class VectorizedBacktester:
    """Vectorized portfolio backtester with transaction-cost modeling."""

    def __init__(self, transaction_cost_bps: float = 5.0) -> None:
        self.transaction_cost_rate = transaction_cost_bps / 10_000.0

    def run(
        self,
        prices: pd.DataFrame,
        strategy_outputs: Mapping[str, StrategyOutput | pd.DataFrame],
        strategy_allocations: pd.DataFrame,
        initial_capital: float = 1.0,
        regimes: pd.Series | None = None,
    ) -> BacktestResult:
        """Backtest a dynamically allocated multi-strategy portfolio."""
        if prices.empty:
            raise ValueError("Price data is empty.")
        if not strategy_outputs:
            raise ValueError("At least one strategy output is required.")

        asset_returns = prices.pct_change().fillna(0.0)
        strategy_names = list(strategy_outputs.keys())

        normalized_strategy_positions: dict[str, pd.DataFrame] = {}
        strategy_returns = pd.DataFrame(index=prices.index, columns=strategy_names, dtype=float)
        for name, output in strategy_outputs.items():
            positions = output.positions if isinstance(output, StrategyOutput) else output
            aligned_positions = positions.reindex(index=prices.index, columns=prices.columns, fill_value=0.0).fillna(0.0)
            normalized_positions = BaseStrategy.normalize_positions(aligned_positions).shift(1).fillna(0.0)
            normalized_strategy_positions[name] = normalized_positions
            strategy_returns[name] = (normalized_positions * asset_returns).sum(axis=1)

        strategy_weights = strategy_allocations.reindex(index=prices.index, columns=strategy_names).ffill()
        strategy_weights = strategy_weights.fillna(0.0)
        strategy_weights = strategy_weights.div(strategy_weights.sum(axis=1).replace(0.0, pd.NA), axis=0).fillna(0.0)
        strategy_weights = strategy_weights.shift(1).fillna(0.0)

        combined_positions = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
        for name in strategy_names:
            combined_positions = combined_positions.add(
                normalized_strategy_positions[name].mul(strategy_weights[name], axis=0),
                fill_value=0.0,
            )

        gross_returns = (combined_positions * asset_returns).sum(axis=1).rename("gross_return")
        turnover = combined_positions.diff().abs().sum(axis=1).fillna(0.0).rename("turnover")
        transaction_costs = (turnover * self.transaction_cost_rate).rename("transaction_cost")
        portfolio_returns = (gross_returns - transaction_costs).rename("portfolio_return")
        equity_curve = (1.0 + portfolio_returns).cumprod().mul(initial_capital).rename("equity_curve")
        running_peak = equity_curve.cummax()
        drawdown = (equity_curve / running_peak - 1.0).rename("drawdown")
        pnl = portfolio_returns.mul(equity_curve.shift(1).fillna(initial_capital)).rename("pnl")

        aligned_regimes = None
        if regimes is not None:
            aligned_regimes = regimes.reindex(prices.index).ffill().rename("regime")

        return BacktestResult(
            asset_returns=asset_returns,
            strategy_returns=strategy_returns,
            strategy_weights=strategy_weights,
            combined_positions=combined_positions,
            gross_returns=gross_returns,
            portfolio_returns=portfolio_returns,
            transaction_costs=transaction_costs,
            turnover=turnover,
            pnl=pnl,
            equity_curve=equity_curve,
            drawdown=drawdown,
            regime_series=aligned_regimes,
        )
