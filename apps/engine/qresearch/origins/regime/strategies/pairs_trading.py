from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.regression.rolling import RollingOLS

from qresearch.origins.regime.strategies.base import BaseStrategy, StrategyOutput


class PairsTradingStrategy(BaseStrategy):
    """Pairs trading strategy using a rolling OLS hedge ratio and spread z-score."""

    def __init__(
        self,
        asset_x: str,
        asset_y: str,
        lookback_window: int = 63,
        zscore_window: int = 20,
        entry_threshold: float = 2.0,
        exit_threshold: float = 0.5,
        name: str = "pairs_trading",
    ) -> None:
        if asset_x == asset_y:
            raise ValueError("Pairs trading requires two distinct assets.")

        super().__init__(name=name, assets=[asset_x, asset_y])
        self.asset_x = asset_x
        self.asset_y = asset_y
        self.lookback_window = lookback_window
        self.zscore_window = zscore_window
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold

    def generate_positions(self, prices: pd.DataFrame) -> StrategyOutput:
        selected = self._select_assets(prices)
        pair_frame = selected[[self.asset_x, self.asset_y]].dropna(how="any")
        exog = sm.add_constant(pair_frame[self.asset_x])
        rolling_model = RollingOLS(
            endog=pair_frame[self.asset_y],
            exog=exog,
            window=self.lookback_window,
        )
        fit_result = rolling_model.fit(params_only=True)
        params = fit_result.params.reindex(pair_frame.index)
        hedge_ratio = params[self.asset_x]

        spread = pair_frame[self.asset_y] - hedge_ratio * pair_frame[self.asset_x]
        spread_mean = spread.rolling(self.zscore_window, min_periods=self.zscore_window).mean()
        spread_std = spread.rolling(self.zscore_window, min_periods=self.zscore_window).std()
        z_score = (spread - spread_mean) / spread_std.replace(0.0, np.nan)
        spread_position = self._position_from_thresholds(
            z_score=z_score,
            entry_threshold=self.entry_threshold,
            exit_threshold=self.exit_threshold,
        )

        aligned_positions = self.neutral_frame(index=prices.index, columns=prices.columns)
        aligned_positions.loc[pair_frame.index, self.asset_y] = spread_position
        aligned_positions.loc[pair_frame.index, self.asset_x] = -spread_position * hedge_ratio.fillna(1.0)
        aligned_positions = aligned_positions.fillna(0.0)

        diagnostics = pd.DataFrame(
            {
                "hedge_ratio": hedge_ratio.reindex(prices.index),
                "spread": spread.reindex(prices.index),
                "spread_z_score": z_score.reindex(prices.index),
                "pair_position": spread_position.reindex(prices.index),
            },
            index=prices.index,
        )
        return StrategyOutput(
            name=self.name,
            positions=aligned_positions,
            diagnostics=diagnostics,
            metadata={
                "asset_x": self.asset_x,
                "asset_y": self.asset_y,
                "lookback_window": self.lookback_window,
                "zscore_window": self.zscore_window,
                "entry_threshold": self.entry_threshold,
                "exit_threshold": self.exit_threshold,
                "strategy_type": "pairs_trading",
            },
        )
