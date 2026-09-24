from __future__ import annotations

import numpy as np
import pandas as pd

from qresearch.origins.regime.strategies.base import BaseStrategy, StrategyOutput


class MomentumStrategy(BaseStrategy):
    """Moving-average crossover momentum strategy."""

    def __init__(
        self,
        short_window: int = 50,
        long_window: int = 200,
        assets: list[str] | None = None,
        name: str = "momentum",
    ) -> None:
        if short_window >= long_window:
            raise ValueError("short_window must be smaller than long_window.")

        super().__init__(name=name, assets=assets)
        self.short_window = short_window
        self.long_window = long_window

    def generate_positions(self, prices: pd.DataFrame) -> StrategyOutput:
        selected = self._select_assets(prices)
        short_ma = selected.rolling(self.short_window, min_periods=self.short_window).mean()
        long_ma = selected.rolling(self.long_window, min_periods=self.long_window).mean()

        raw_signals = np.where(short_ma > long_ma, 1.0, -1.0)
        positions = pd.DataFrame(raw_signals, index=selected.index, columns=selected.columns)
        positions = positions.where(long_ma.notna(), 0.0)

        aligned_positions = self.neutral_frame(index=prices.index, columns=prices.columns)
        aligned_positions.loc[:, selected.columns] = positions

        diagnostics = pd.concat(
            {
                "short_ma": short_ma,
                "long_ma": long_ma,
            },
            axis=1,
        )
        return StrategyOutput(
            name=self.name,
            positions=aligned_positions,
            diagnostics=diagnostics,
            metadata={
                "assets": list(selected.columns),
                "short_window": self.short_window,
                "long_window": self.long_window,
                "strategy_type": "momentum",
            },
        )
