from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(slots=True)
class DataPreprocessor:
    """Clean price data and build downstream research features."""

    volatility_window: int = 20
    momentum_window: int = 20
    short_ma_window: int = 50
    long_ma_window: int = 200

    def clean_prices(self, prices: pd.DataFrame) -> pd.DataFrame:
        """Sort, de-duplicate, forward-fill, and validate price data."""
        if prices.empty:
            raise ValueError("Price data is empty.")

        cleaned = prices.copy()
        cleaned.index = pd.to_datetime(cleaned.index)
        cleaned = cleaned.sort_index()
        cleaned = cleaned.loc[~cleaned.index.duplicated(keep="last")]
        cleaned = cleaned.apply(pd.to_numeric, errors="coerce")
        cleaned = cleaned.replace([np.inf, -np.inf], np.nan)
        cleaned = cleaned.ffill()
        cleaned = cleaned.dropna(how="all")
        cleaned = cleaned.dropna(axis=1, how="all")
        cleaned = cleaned.dropna(how="any")

        if cleaned.empty:
            raise ValueError("All price observations were dropped during cleaning.")

        return cleaned

    @staticmethod
    def compute_returns(prices: pd.DataFrame) -> pd.DataFrame:
        """Compute simple daily returns."""
        returns = prices.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
        returns.index = prices.index
        return returns

    def build_regime_features(self, prices: pd.DataFrame, benchmark: str) -> pd.DataFrame:
        """Construct HMM features from a benchmark asset."""
        if benchmark not in prices.columns:
            raise KeyError(f"Benchmark ticker '{benchmark}' not present in the price data.")

        benchmark_prices = prices[benchmark].copy()
        daily_returns = benchmark_prices.pct_change()
        rolling_vol = daily_returns.rolling(self.volatility_window).std()
        ma_short = benchmark_prices.rolling(self.short_ma_window).mean()
        ma_long = benchmark_prices.rolling(self.long_ma_window).mean()
        ma_spread = (ma_short - ma_long) / ma_long.replace(0.0, np.nan)
        momentum = benchmark_prices.pct_change(self.momentum_window)

        features = pd.DataFrame(
            {
                "daily_return": daily_returns,
                "rolling_volatility_20d": rolling_vol,
                "ma_spread_50_200": ma_spread,
                "momentum_20d": momentum,
            },
            index=prices.index,
        )
        features = features.replace([np.inf, -np.inf], np.nan).dropna(how="any")
        return features
