from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np
import pandas as pd


@dataclass(slots=True)
class StrategyOutput:
    """Container for strategy positions and supporting diagnostics."""

    name: str
    positions: pd.DataFrame
    diagnostics: pd.DataFrame | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseStrategy(ABC):
    """Abstract base class for signal-generating trading strategies."""

    def __init__(self, name: str, assets: Sequence[str] | None = None) -> None:
        self.name = name
        self.assets = list(assets) if assets else None

    def _select_assets(self, prices: pd.DataFrame) -> pd.DataFrame:
        if self.assets is None:
            return prices.copy()

        missing_assets = sorted(set(self.assets).difference(prices.columns))
        if missing_assets:
            raise KeyError(f"Missing assets for strategy '{self.name}': {missing_assets}")

        return prices.loc[:, self.assets].copy()

    @staticmethod
    def neutral_frame(index: pd.Index, columns: pd.Index) -> pd.DataFrame:
        """Return a zero-position DataFrame."""
        return pd.DataFrame(0.0, index=index, columns=columns)

    @staticmethod
    def normalize_positions(positions: pd.DataFrame) -> pd.DataFrame:
        """Normalize raw exposures to unit gross exposure per day."""
        gross_exposure = positions.abs().sum(axis=1).replace(0.0, np.nan)
        normalized = positions.div(gross_exposure, axis=0).replace([np.inf, -np.inf], np.nan)
        return normalized.fillna(0.0)

    @staticmethod
    def _position_from_thresholds(
        z_score: pd.Series,
        entry_threshold: float,
        exit_threshold: float,
    ) -> pd.Series:
        """Generate persistent long/short positions from z-score thresholds."""
        current_position = 0.0
        positions: list[float] = []

        for value in z_score:
            if pd.isna(value):
                current_position = 0.0
            elif current_position == 0.0:
                if value < -entry_threshold:
                    current_position = 1.0
                elif value > entry_threshold:
                    current_position = -1.0
            else:
                if abs(value) <= exit_threshold:
                    current_position = 0.0
                elif current_position > 0 and value > entry_threshold:
                    current_position = -1.0
                elif current_position < 0 and value < -entry_threshold:
                    current_position = 1.0

            positions.append(current_position)

        return pd.Series(positions, index=z_score.index, dtype=float)

    @abstractmethod
    def generate_positions(self, prices: pd.DataFrame) -> StrategyOutput:
        """Generate raw positions aligned to the input price index."""

    def __repr__(self) -> str:
        asset_block = ",".join(self.assets) if self.assets else "all_assets"
        return f"{self.__class__.__name__}(name={self.name!r}, assets={asset_block})"
