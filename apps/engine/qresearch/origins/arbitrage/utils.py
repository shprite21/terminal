"""Shared utilities for configuration, serialization, and research plots."""

from __future__ import annotations

import json
import logging
import random
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml


def configure_logging(level: str = "INFO") -> None:
    """Configure console logging for command-line research runs."""

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def set_random_seed(seed: int) -> None:
    """Set reproducible seeds for libraries used by the project."""

    random.seed(seed)
    np.random.seed(seed)


def load_config(path: Path) -> dict[str, Any]:
    """Load a YAML configuration file."""

    with path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file)
    if not isinstance(config, dict):
        raise ValueError(f"Configuration file {path} did not contain a mapping.")
    return config


def ensure_directories(project_root: Path) -> None:
    """Create the project output directories expected by the research pipeline."""

    for relative_path in [
        "data/raw",
        "data/processed",
        "results/figures",
        "results/performance_reports",
        "results/optimization_logs",
        "notebooks",
        "configs",
    ]:
        (project_root / relative_path).mkdir(parents=True, exist_ok=True)


def timestamp() -> str:
    """Return a compact timestamp for versioned research artifacts."""

    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def to_serializable(value: Any) -> Any:
    """Convert pandas and numpy objects into JSON-serializable Python objects."""

    if isinstance(value, Mapping):
        return {str(key): to_serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_serializable(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if pd.isna(value) else float(value)
    if isinstance(value, (np.ndarray,)):
        return value.tolist()
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, pd.Series):
        return value.to_dict()
    if isinstance(value, pd.DataFrame):
        return value.to_dict(orient="records")
    if isinstance(value, float) and pd.isna(value):
        return None
    return value


def save_json(data: Mapping[str, Any], path: Path) -> None:
    """Save a mapping as formatted JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(to_serializable(data), file, indent=2, sort_keys=True)


class ResearchPlotter:
    """Create publication-quality plots for strategy diagnostics."""

    def __init__(self, style: str = "seaborn-v0_8-whitegrid") -> None:
        self.style = style

    def plot_spread_and_zscore(
        self,
        spread: pd.Series,
        z_score: pd.Series,
        signals: pd.Series,
        entry_threshold: float,
        exit_threshold: float,
        output_path: Path,
    ) -> None:
        """Plot spread dynamics and z-score trading bands."""

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with plt.style.context(self.style):
            fig, axes = plt.subplots(
                2,
                1,
                figsize=(13, 8),
                sharex=True,
                gridspec_kw={"height_ratios": [1.1, 1.0]},
            )
            axes[0].plot(spread.index, spread, color="#1f2937", linewidth=1.2)
            axes[0].set_title("Cointegration Spread", fontsize=13, weight="bold")
            axes[0].set_ylabel("Spread")

            axes[1].plot(z_score.index, z_score, color="#2563eb", linewidth=1.1)
            axes[1].axhline(entry_threshold, color="#b91c1c", linestyle="--", linewidth=1.0)
            axes[1].axhline(-entry_threshold, color="#047857", linestyle="--", linewidth=1.0)
            axes[1].axhline(exit_threshold, color="#6b7280", linestyle=":", linewidth=1.0)
            axes[1].axhline(-exit_threshold, color="#6b7280", linestyle=":", linewidth=1.0)
            axes[1].axhline(0.0, color="#111827", linewidth=0.8, alpha=0.65)

            long_entries = signals[(signals == 1) & (signals.shift(1).fillna(0) != 1)]
            short_entries = signals[(signals == -1) & (signals.shift(1).fillna(0) != -1)]
            exits = signals[(signals == 0) & (signals.shift(1).fillna(0) != 0)]

            axes[1].scatter(
                long_entries.index,
                z_score.reindex(long_entries.index),
                marker="^",
                color="#047857",
                s=45,
                label="Long spread",
                zorder=3,
            )
            axes[1].scatter(
                short_entries.index,
                z_score.reindex(short_entries.index),
                marker="v",
                color="#b91c1c",
                s=45,
                label="Short spread",
                zorder=3,
            )
            axes[1].scatter(
                exits.index,
                z_score.reindex(exits.index),
                marker="x",
                color="#111827",
                s=30,
                label="Exit",
                zorder=3,
            )
            axes[1].set_title("Z-Score Signal Bands", fontsize=13, weight="bold")
            axes[1].set_ylabel("Z-score")
            axes[1].legend(loc="upper right", frameon=True)

            fig.autofmt_xdate()
            fig.tight_layout()
            fig.savefig(output_path, dpi=160)
            plt.close(fig)

    def plot_equity_and_drawdown(
        self,
        equity_curve: pd.Series,
        drawdown: pd.Series,
        output_path: Path,
    ) -> None:
        """Plot the equity curve and drawdown profile."""

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with plt.style.context(self.style):
            fig, axes = plt.subplots(
                2,
                1,
                figsize=(13, 8),
                sharex=True,
                gridspec_kw={"height_ratios": [1.2, 0.8]},
            )
            axes[0].plot(equity_curve.index, equity_curve, color="#111827", linewidth=1.4)
            axes[0].set_title("Out-of-Sample Equity Curve", fontsize=13, weight="bold")
            axes[0].set_ylabel("Portfolio value")

            axes[1].fill_between(
                drawdown.index,
                drawdown,
                0,
                color="#dc2626",
                alpha=0.32,
                linewidth=0,
            )
            axes[1].plot(drawdown.index, drawdown, color="#991b1b", linewidth=1.0)
            axes[1].set_title("Drawdown", fontsize=13, weight="bold")
            axes[1].set_ylabel("Drawdown")

            fig.autofmt_xdate()
            fig.tight_layout()
            fig.savefig(output_path, dpi=160)
            plt.close(fig)
