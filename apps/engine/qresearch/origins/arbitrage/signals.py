"""Mean-reversion signal engine for spread trading."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SignalConfig:
    """Trading thresholds for z-score spread signals."""

    entry_threshold: float
    exit_threshold: float


class SignalEngine:
    """Generate long, short, and flat spread positions from z-scores."""

    def generate(
        self,
        z_score: pd.Series,
        entry_threshold: float,
        exit_threshold: float,
    ) -> pd.DataFrame:
        """Generate position states and event labels from a z-score series."""

        if entry_threshold <= 0:
            raise ValueError("Entry threshold must be positive.")
        if exit_threshold < 0:
            raise ValueError("Exit threshold cannot be negative.")
        if exit_threshold >= entry_threshold:
            raise ValueError("Exit threshold must be lower than entry threshold.")

        position = 0
        positions: list[int] = []
        events: list[str] = []

        for value in z_score:
            event = "hold"
            if np.isnan(value):
                positions.append(position)
                events.append("warmup")
                continue

            previous = position
            if position == 0:
                if value < -entry_threshold:
                    position = 1
                    event = "long_entry"
                elif value > entry_threshold:
                    position = -1
                    event = "short_entry"
                else:
                    event = "flat"
            elif position == 1:
                if value >= -exit_threshold:
                    position = 0
                    event = "exit_long"
            elif position == -1:
                if value <= exit_threshold:
                    position = 0
                    event = "exit_short"

            if previous != position and event == "hold":
                event = "position_change"
            positions.append(position)
            events.append(event)

        output = pd.DataFrame(
            {
                "signal": pd.Series(positions, index=z_score.index, dtype=float),
                "event": pd.Series(events, index=z_score.index, dtype="object"),
            }
        )
        output["is_entry"] = output["event"].isin(["long_entry", "short_entry"])
        output["is_exit"] = output["event"].isin(["exit_long", "exit_short"])
        return output

