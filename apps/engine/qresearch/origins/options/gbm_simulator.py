"""Geometric Brownian Motion simulator for underlying stock paths."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class GBMConfig:
    """Configuration for a single GBM stock path."""

    initial_price: float = 100.0
    drift: float = 0.05
    volatility: float = 0.22
    dt: float = 1.0 / (252.0 * 78.0)
    n_steps: int = 780
    seed: int = 42
    realized_vol_window: int = 39


class GBMSimulator:
    """Simulate stock paths under dS/S = mu dt + sigma dW."""

    def __init__(self, config: GBMConfig):
        if config.initial_price <= 0.0:
            raise ValueError("initial_price must be positive")
        if config.volatility < 0.0:
            raise ValueError("volatility cannot be negative")
        if config.dt <= 0.0:
            raise ValueError("dt must be positive")
        if config.n_steps <= 0:
            raise ValueError("n_steps must be positive")
        self.config = config

    def simulate_path(self) -> pd.DataFrame:
        """Return a DataFrame containing simulated prices and realized volatility."""

        cfg = self.config
        rng = np.random.default_rng(cfg.seed)
        shocks = rng.standard_normal(cfg.n_steps)
        log_increments = (
            (cfg.drift - 0.5 * cfg.volatility * cfg.volatility) * cfg.dt
            + cfg.volatility * np.sqrt(cfg.dt) * shocks
        )
        log_prices = np.log(cfg.initial_price) + np.concatenate(([0.0], np.cumsum(log_increments)))
        spots = np.exp(log_prices)
        log_returns = np.concatenate(([0.0], log_increments))
        simple_returns = np.exp(log_returns) - 1.0
        times = np.arange(cfg.n_steps + 1) * cfg.dt

        realized_vol = rolling_realized_volatility(
            log_returns=log_returns,
            dt=cfg.dt,
            window=cfg.realized_vol_window,
        )

        return pd.DataFrame(
            {
                "step": np.arange(cfg.n_steps + 1, dtype=int),
                "time_years": times,
                "spot": spots,
                "log_return": log_returns,
                "simple_return": simple_returns,
                "realized_volatility": realized_vol,
            }
        )


def rolling_realized_volatility(log_returns: np.ndarray, dt: float, window: int) -> np.ndarray:
    """Annualized rolling realized volatility from log returns."""

    if window <= 1:
        raise ValueError("window must be greater than one")
    series = pd.Series(log_returns)
    realized = series.rolling(window=window, min_periods=2).std(ddof=1) / np.sqrt(dt)
    return realized.bfill().fillna(0.0).to_numpy()


def simulate_gbm_path(config: Optional[GBMConfig] = None) -> pd.DataFrame:
    """Convenience wrapper for a single simulated path."""

    return GBMSimulator(config or GBMConfig()).simulate_path()


def save_path(df: pd.DataFrame, output_path: Path) -> None:
    """Persist a simulated path to CSV."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
