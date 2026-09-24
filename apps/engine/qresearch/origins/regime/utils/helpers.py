from __future__ import annotations

import json
import logging
import random
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml


LOGGER = logging.getLogger(__name__)


def ensure_directory(path: str | Path) -> Path:
    """Create a directory if it does not already exist."""
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def load_yaml_config(path: str | Path) -> dict[str, Any]:
    """Load a YAML configuration file into a dictionary."""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)

    if not isinstance(loaded, dict):
        raise ValueError("Configuration file must contain a top-level mapping.")

    return loaded


def save_dataframe(data: pd.DataFrame, path: str | Path, index: bool = True) -> Path:
    """Persist a DataFrame to CSV."""
    output_path = Path(path)
    ensure_directory(output_path.parent)
    data.to_csv(output_path, index=index)
    LOGGER.info("Saved dataframe to %s", output_path)
    return output_path


def save_series(data: pd.Series, path: str | Path, index: bool = True) -> Path:
    """Persist a Series to CSV."""
    output_path = Path(path)
    ensure_directory(output_path.parent)
    data.to_csv(output_path, index=index, header=True)
    LOGGER.info("Saved series to %s", output_path)
    return output_path


def save_json(payload: dict[str, Any], path: str | Path) -> Path:
    """Persist a dictionary to JSON with stable formatting."""
    output_path = Path(path)
    ensure_directory(output_path.parent)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, default=str)
    LOGGER.info("Saved JSON to %s", output_path)
    return output_path


def set_random_seed(seed: int) -> None:
    """Set random seeds for reproducibility."""
    random.seed(seed)
    np.random.seed(seed)


def resolve_project_path(project_root: str | Path, relative_path: str | Path) -> Path:
    """Resolve a project-relative path."""
    root = Path(project_root)
    return (root / relative_path).resolve()


def coerce_end_date(value: str | None) -> str:
    """Resolve supported end-date aliases such as 'auto' or 'today'."""
    if value is None:
        return date.today().isoformat()

    normalized = value.strip().lower()
    if normalized in {"auto", "today"}:
        return date.today().isoformat()

    try:
        return datetime.fromisoformat(value).date().isoformat()
    except ValueError as exc:
        raise ValueError(f"Unsupported date format: {value}") from exc


def format_metric_value(name: str, value: float) -> str:
    """Pretty-format a performance metric for console reporting."""
    percentage_metrics = {
        "Cumulative Return",
        "Annualized Return",
        "Annualized Volatility",
        "Maximum Drawdown",
        "Win Rate",
        "Average Turnover",
    }

    if pd.isna(value):
        return "nan"

    if name in percentage_metrics:
        return f"{value:.2%}"

    return f"{value:.4f}"
