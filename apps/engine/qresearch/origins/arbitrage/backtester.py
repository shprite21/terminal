"""Vectorized portfolio accounting for spread trading strategies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BacktestConfig:
    """Portfolio accounting assumptions."""

    initial_capital: float = 1_000_000.0
    transaction_cost_bps: float = 1.0
    slippage_bps: float = 1.0
    annualization_factor: int = 252

    @property
    def total_cost_rate(self) -> float:
        """Combined proportional trading cost per unit of turnover."""

        return (self.transaction_cost_bps + self.slippage_bps) / 10_000.0


@dataclass
class BacktestResult:
    """Full backtest output bundle."""

    equity_curve: pd.Series
    returns: pd.Series
    positions: pd.DataFrame
    trade_log: pd.DataFrame
    costs: pd.Series
    turnover: pd.Series
    spread: pd.Series
    z_score: pd.Series
    signals: pd.Series
    weights: pd.Series


class BasketBacktester:
    """Backtest spread signals as tradable gross-normalized asset weights."""

    def __init__(self, config: BacktestConfig) -> None:
        self.config = config

    def run(
        self,
        prices: pd.DataFrame,
        weights: Mapping[str, float] | pd.Series,
        signal_frame: pd.DataFrame,
        spread: pd.Series,
        z_score: pd.Series,
        position_size: float,
    ) -> BacktestResult:
        """Run a close-to-close vectorized backtest with turnover-based costs."""

        if position_size <= 0:
            raise ValueError("Position size must be positive.")

        prices = prices.copy().dropna(how="any")
        columns = prices.columns
        weight_series = pd.Series(weights, dtype=float).reindex(columns).fillna(0.0)
        gross = float(weight_series.abs().sum())
        if gross <= 1e-12:
            raise ValueError("Weights must have non-zero gross exposure.")
        normalized_weights = weight_series / gross

        signals = signal_frame["signal"].reindex(prices.index).fillna(0.0)
        target_weights = pd.DataFrame(
            np.outer(signals.to_numpy() * position_size, normalized_weights.to_numpy()),
            index=prices.index,
            columns=columns,
        )

        asset_returns = prices.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
        executed_weights = target_weights.shift(1).fillna(0.0)
        gross_returns = (executed_weights * asset_returns).sum(axis=1)

        turnover = target_weights.diff().abs().sum(axis=1)
        turnover.iloc[0] = target_weights.iloc[0].abs().sum()
        costs = turnover * self.config.total_cost_rate
        strategy_returns = (gross_returns - costs).rename("strategy_return")
        equity_curve = (self.config.initial_capital * (1.0 + strategy_returns).cumprod()).rename("equity")

        positions = target_weights.add_prefix("target_weight_")
        for column in columns:
            positions[f"executed_weight_{column}"] = executed_weights[column]
        positions["spread_signal"] = signals
        positions["gross_exposure"] = target_weights.abs().sum(axis=1)
        positions["turnover"] = turnover
        positions["cost"] = costs

        trade_log = self._build_trade_log(
            signals=signals,
            equity_curve=equity_curve,
            spread=spread.reindex(prices.index),
            z_score=z_score.reindex(prices.index),
            strategy_returns=strategy_returns,
            costs=costs,
        )

        return BacktestResult(
            equity_curve=equity_curve,
            returns=strategy_returns,
            positions=positions,
            trade_log=trade_log,
            costs=costs.rename("cost"),
            turnover=turnover.rename("turnover"),
            spread=spread.reindex(prices.index).rename("spread"),
            z_score=z_score.reindex(prices.index).rename("z_score"),
            signals=signals.rename("signal"),
            weights=normalized_weights.rename("weight"),
        )

    @staticmethod
    def _build_trade_log(
        signals: pd.Series,
        equity_curve: pd.Series,
        spread: pd.Series,
        z_score: pd.Series,
        strategy_returns: pd.Series,
        costs: pd.Series,
    ) -> pd.DataFrame:
        """Create a trade-level log from signal state changes."""

        trades: list[dict[str, object]] = []
        current_signal = 0.0
        entry_date: pd.Timestamp | None = None
        entry_equity = np.nan
        entry_spread = np.nan
        entry_z = np.nan

        for date, signal in signals.items():
            signal = float(signal)
            if signal == current_signal:
                continue

            if current_signal != 0.0 and entry_date is not None:
                period_returns = strategy_returns.loc[entry_date:date]
                period_costs = costs.loc[entry_date:date]
                net_return = float(equity_curve.loc[date] / entry_equity - 1.0)
                trades.append(
                    {
                        "entry_date": entry_date,
                        "exit_date": date,
                        "direction": "long_spread" if current_signal > 0 else "short_spread",
                        "entry_spread": float(entry_spread),
                        "exit_spread": float(spread.loc[date]),
                        "entry_z_score": float(entry_z),
                        "exit_z_score": float(z_score.loc[date]),
                        "bars_held": int(len(period_returns)),
                        "gross_return": float((1.0 + period_returns + period_costs).prod() - 1.0),
                        "net_return": net_return,
                        "total_cost": float(period_costs.sum()),
                        "exit_reason": "signal_change",
                    }
                )

            if signal != 0.0:
                entry_date = date
                entry_equity = float(equity_curve.loc[date])
                entry_spread = float(spread.loc[date])
                entry_z = float(z_score.loc[date])
            else:
                entry_date = None
                entry_equity = np.nan
                entry_spread = np.nan
                entry_z = np.nan
            current_signal = signal

        if current_signal != 0.0 and entry_date is not None:
            final_date = signals.index[-1]
            period_returns = strategy_returns.loc[entry_date:final_date]
            period_costs = costs.loc[entry_date:final_date]
            trades.append(
                {
                    "entry_date": entry_date,
                    "exit_date": final_date,
                    "direction": "long_spread" if current_signal > 0 else "short_spread",
                    "entry_spread": float(entry_spread),
                    "exit_spread": float(spread.loc[final_date]),
                    "entry_z_score": float(entry_z),
                    "exit_z_score": float(z_score.loc[final_date]),
                    "bars_held": int(len(period_returns)),
                    "gross_return": float((1.0 + period_returns + period_costs).prod() - 1.0),
                    "net_return": float(equity_curve.loc[final_date] / entry_equity - 1.0),
                    "total_cost": float(period_costs.sum()),
                    "exit_reason": "end_of_sample",
                }
            )

        return pd.DataFrame(trades)

