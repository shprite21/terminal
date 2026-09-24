from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(slots=True)
class RegimeAwarePortfolioAllocator:
    """Map inferred market regimes to strategy allocation weights."""

    regime_weight_map: dict[str, dict[str, float]]

    def build_weight_frame(self, regimes: pd.Series, strategy_names: list[str]) -> pd.DataFrame:
        """Construct a daily strategy-weight matrix from regime labels."""
        if regimes.empty:
            raise ValueError("Regime series is empty.")

        default_weights = {name: 1.0 / len(strategy_names) for name in strategy_names}
        weight_rows: list[pd.Series] = []

        for timestamp, regime in regimes.items():
            mapping = self.regime_weight_map.get(str(regime), default_weights)
            row = pd.Series(mapping, dtype=float).reindex(strategy_names).fillna(0.0)
            row_sum = row.sum()
            if np.isclose(row_sum, 0.0):
                row = pd.Series(default_weights, dtype=float)
            else:
                row = row / row_sum
            row.name = timestamp
            weight_rows.append(row)

        weights = pd.DataFrame(weight_rows)
        weights.index = regimes.index
        weights.columns = strategy_names
        return weights.sort_index()
