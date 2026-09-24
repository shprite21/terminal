"""Performance metrics for quantitative trading research."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class MetricsConfig:
    """Performance metric assumptions."""

    annualization_factor: int = 252
    risk_free_rate: float = 0.0


class PerformanceAnalyzer:
    """Compute professional-grade trading performance metrics."""

    def __init__(self, config: MetricsConfig) -> None:
        self.config = config

    def calculate(
        self,
        returns: pd.Series,
        equity_curve: pd.Series,
        trade_log: pd.DataFrame | None = None,
    ) -> dict[str, Any]:
        """Compute Sharpe, Sortino, CAGR, drawdown, volatility, and win rate."""

        returns = returns.dropna()
        equity_curve = equity_curve.dropna()
        if returns.empty or equity_curve.empty:
            raise ValueError("Returns and equity curve are required for performance analysis.")

        periods = max(len(returns), 1)
        annual_factor = self.config.annualization_factor
        daily_risk_free = self.config.risk_free_rate / annual_factor
        excess_returns = returns - daily_risk_free

        volatility = float(returns.std(ddof=0) * np.sqrt(annual_factor))
        sharpe = self._safe_ratio(
            float(excess_returns.mean() * annual_factor),
            float(excess_returns.std(ddof=0) * np.sqrt(annual_factor)),
        )
        downside_returns = np.minimum(excess_returns, 0.0)
        sortino = self._safe_ratio(
            float(excess_returns.mean() * annual_factor),
            float(pd.Series(downside_returns).std(ddof=0) * np.sqrt(annual_factor)),
        )

        total_return = float(equity_curve.iloc[-1] / equity_curve.iloc[0] - 1.0)
        years = periods / annual_factor
        cagr = float((equity_curve.iloc[-1] / equity_curve.iloc[0]) ** (1.0 / years) - 1.0) if years > 0 else np.nan
        drawdown = self.drawdown(equity_curve)
        max_drawdown = float(drawdown.min())

        win_rate = np.nan
        trade_count = 0
        average_trade_return = np.nan
        if trade_log is not None and not trade_log.empty and "net_return" in trade_log:
            trade_count = int(len(trade_log))
            win_rate = float((trade_log["net_return"] > 0).mean())
            average_trade_return = float(trade_log["net_return"].mean())

        return {
            "start_date": equity_curve.index[0],
            "end_date": equity_curve.index[-1],
            "observations": int(periods),
            "final_equity": float(equity_curve.iloc[-1]),
            "total_return": total_return,
            "cagr": cagr,
            "volatility": volatility,
            "sharpe_ratio": sharpe,
            "sortino_ratio": sortino,
            "max_drawdown": max_drawdown,
            "win_rate": win_rate,
            "trade_count": trade_count,
            "average_trade_return": average_trade_return,
        }

    @staticmethod
    def drawdown(equity_curve: pd.Series) -> pd.Series:
        """Compute drawdown from an equity curve."""

        running_max = equity_curve.cummax()
        return (equity_curve / running_max - 1.0).rename("drawdown")

    @staticmethod
    def _safe_ratio(numerator: float, denominator: float) -> float:
        """Return a ratio while guarding against division by zero."""

        if np.isclose(denominator, 0.0) or not np.isfinite(denominator):
            return np.nan
        return float(numerator / denominator)

