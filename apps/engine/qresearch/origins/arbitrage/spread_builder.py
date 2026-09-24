"""Spread construction and rolling z-score calculation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SpreadStatistics:
    """Container for spread and rolling standardization series."""

    spread: pd.Series
    rolling_mean: pd.Series
    rolling_std: pd.Series
    z_score: pd.Series
    weights: pd.Series


class WeightedSpreadBuilder:
    """Build weighted linear spreads from adjusted close prices."""

    def __init__(self, use_log_prices: bool = True, shift_statistics: bool = True) -> None:
        self.use_log_prices = use_log_prices
        self.shift_statistics = shift_statistics

    def prepare_prices(self, prices: pd.DataFrame) -> pd.DataFrame:
        """Return prices in the representation used for spread construction."""

        data = prices.copy().dropna(how="any")
        if self.use_log_prices:
            if (data <= 0).any().any():
                raise ValueError("Log spread construction requires positive prices.")
            data = np.log(data)
        return data

    @staticmethod
    def normalize_weights(weights: Mapping[str, float] | pd.Series, columns: pd.Index) -> pd.Series:
        """Normalize weights to unit gross exposure and align them to price columns."""

        weight_series = pd.Series(weights, dtype=float).reindex(columns).fillna(0.0)
        gross = float(weight_series.abs().sum())
        if gross <= 1e-12:
            raise ValueError("Spread weights must have non-zero gross exposure.")
        return weight_series / gross

    def build_spread(
        self,
        prices: pd.DataFrame,
        weights: Mapping[str, float] | pd.Series,
        normalize: bool = True,
    ) -> pd.Series:
        """Build a weighted spread series."""

        data = self.prepare_prices(prices)
        weight_series = pd.Series(weights, dtype=float).reindex(data.columns).fillna(0.0)
        if normalize:
            weight_series = self.normalize_weights(weight_series, data.columns)
        spread = data.dot(weight_series)
        spread.name = "spread"
        return spread

    def compute_statistics(
        self,
        prices: pd.DataFrame,
        weights: Mapping[str, float] | pd.Series,
        rolling_window: int,
        min_periods: int | None = None,
    ) -> SpreadStatistics:
        """Compute spread, rolling mean, rolling standard deviation, and z-score."""

        if rolling_window < 2:
            raise ValueError("Rolling window must be at least 2.")

        data = self.prepare_prices(prices)
        weight_series = self.normalize_weights(weights, data.columns)
        spread = data.dot(weight_series)
        spread.name = "spread"

        effective_min_periods = min_periods or rolling_window
        rolling_mean = spread.rolling(rolling_window, min_periods=effective_min_periods).mean()
        rolling_std = spread.rolling(rolling_window, min_periods=effective_min_periods).std(ddof=0)
        if self.shift_statistics:
            rolling_mean = rolling_mean.shift(1)
            rolling_std = rolling_std.shift(1)
        z_score = (spread - rolling_mean) / rolling_std.replace(0.0, np.nan)
        z_score.name = "z_score"

        return SpreadStatistics(
            spread=spread,
            rolling_mean=rolling_mean.rename("rolling_mean"),
            rolling_std=rolling_std.rename("rolling_std"),
            z_score=z_score.replace([np.inf, -np.inf], np.nan),
            weights=weight_series,
        )

