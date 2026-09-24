from __future__ import annotations

import numpy as np
import pandas as pd

from qresearch.origins.regime.strategies.base import BaseStrategy, StrategyOutput


class MeanReversionStrategy(BaseStrategy):
    """Cross-sectional mean reversion strategy based on rolling z-scores."""

    def __init__(
        self,
        window: int = 20,
        entry_threshold: float = 1.5,
        exit_threshold: float = 0.5,
        assets: list[str] | None = None,
        name: str = "mean_reversion",
    ) -> None:
        if window < 2:
            raise ValueError("window must be at least 2.")

        super().__init__(name=name, assets=assets)
        self.window = window
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold

    def generate_positions(self, prices: pd.DataFrame) -> StrategyOutput:
        selected = self._select_assets(prices)
        rolling_mean = selected.rolling(self.window, min_periods=self.window).mean()
        rolling_std = selected.rolling(self.window, min_periods=self.window).std()
        z_scores = (selected - rolling_mean) / rolling_std.replace(0.0, np.nan)

        positions = pd.DataFrame(0.0, index=selected.index, columns=selected.columns)
        for column in selected.columns:
            positions[column] = self._position_from_thresholds(
                z_score=z_scores[column],
                entry_threshold=self.entry_threshold,
                exit_threshold=self.exit_threshold,
            )

        aligned_positions = self.neutral_frame(index=prices.index, columns=prices.columns)
        aligned_positions.loc[:, selected.columns] = positions.fillna(0.0)

        diagnostics = pd.concat(
            {
                "rolling_mean": rolling_mean,
                "rolling_std": rolling_std,
                "z_score": z_scores.replace([np.inf, -np.inf], np.nan),
            },
            axis=1,
        )
        return StrategyOutput(
            name=self.name,
            positions=aligned_positions,
            diagnostics=diagnostics,
            metadata={
                "assets": list(selected.columns),
                "window": self.window,
                "entry_threshold": self.entry_threshold,
                "exit_threshold": self.exit_threshold,
                "strategy_type": "mean_reversion",
            },
        )
