"""Market data ingestion and cleaning utilities."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
import yfinance as yf


MissingPolicy = Literal["ffill_drop", "ffill_bfill", "drop_rows", "interpolate"]


@dataclass(frozen=True)
class DataConfig:
    """Configuration for historical adjusted close data."""

    tickers: list[str]
    start: str
    end: str | None
    raw_dir: Path
    processed_dir: Path
    missing_policy: MissingPolicy = "ffill_drop"
    forward_fill_limit: int = 5
    min_history: int = 252


class MarketDataLoader:
    """Download, align, clean, and persist adjusted close time series."""

    def __init__(self, config: DataConfig) -> None:
        if len(config.tickers) < 2:
            raise ValueError("At least two assets are required for cointegration research.")
        self.config = config

    @classmethod
    def from_config(cls, config: dict, project_root: Path) -> "MarketDataLoader":
        """Create a loader from the project YAML configuration."""

        data_config = config["data"]
        return cls(
            DataConfig(
                tickers=list(data_config["tickers"]),
                start=str(data_config["start"]),
                end=data_config.get("end"),
                raw_dir=project_root / "data" / "raw",
                processed_dir=project_root / "data" / "processed",
                missing_policy=data_config.get("missing_policy", "ffill_drop"),
                forward_fill_limit=int(data_config.get("forward_fill_limit", 5)),
                min_history=int(data_config.get("min_history", 252)),
            )
        )

    @property
    def processed_prices_path(self) -> Path:
        """Path where cleaned adjusted close data is stored."""

        return self.config.processed_dir / "adjusted_close_clean.csv"

    def download(self) -> pd.DataFrame:
        """Download adjusted close data from Yahoo Finance via yfinance."""

        self.config.raw_dir.mkdir(parents=True, exist_ok=True)
        raw = yf.download(
            tickers=self.config.tickers,
            start=self.config.start,
            end=self.config.end,
            auto_adjust=False,
            progress=False,
            group_by="column",
            threads=True,
        )
        if raw.empty:
            raise ValueError("No market data was returned by yfinance.")

        raw.to_csv(self.config.raw_dir / "yfinance_download.csv")
        prices = self._extract_adjusted_close(raw)
        return prices

    def _extract_adjusted_close(self, raw: pd.DataFrame) -> pd.DataFrame:
        """Extract adjusted close prices from yfinance's single or multi-index format."""

        if isinstance(raw.columns, pd.MultiIndex):
            field_level = raw.columns.get_level_values(0)
            if "Adj Close" in field_level:
                prices = raw["Adj Close"].copy()
            elif "Close" in field_level:
                prices = raw["Close"].copy()
            else:
                raise ValueError("Could not find adjusted close or close columns in yfinance data.")
        else:
            price_column = "Adj Close" if "Adj Close" in raw.columns else "Close"
            prices = raw[[price_column]].copy()
            prices.columns = [self.config.tickers[0]]

        prices = prices.reindex(columns=self.config.tickers)
        prices.index = pd.to_datetime(prices.index)
        return prices.apply(pd.to_numeric, errors="coerce")

    def clean(self, prices: pd.DataFrame) -> pd.DataFrame:
        """Clean and align prices according to the configured missing-data policy."""

        prices = prices.copy()
        prices = prices.sort_index()
        prices = prices[~prices.index.duplicated(keep="last")]
        prices = prices.replace([np.inf, -np.inf], np.nan)
        prices = prices.dropna(axis=1, how="all")

        missing_policy = self.config.missing_policy
        if missing_policy == "ffill_drop":
            prices = prices.ffill(limit=self.config.forward_fill_limit).dropna(how="any")
        elif missing_policy == "ffill_bfill":
            prices = prices.ffill(limit=self.config.forward_fill_limit).bfill().dropna(how="any")
        elif missing_policy == "drop_rows":
            prices = prices.dropna(how="any")
        elif missing_policy == "interpolate":
            prices = prices.interpolate(method="time").ffill().bfill().dropna(how="any")
        else:
            raise ValueError(f"Unsupported missing data policy: {missing_policy}")

        if prices.shape[1] < 2:
            raise ValueError("Fewer than two assets remain after cleaning.")
        if len(prices) < self.config.min_history:
            raise ValueError(
                f"Only {len(prices)} observations remain after cleaning; "
                f"minimum required is {self.config.min_history}."
            )
        return prices

    def load_or_download(self, use_cached: bool = False) -> pd.DataFrame:
        """Load cached cleaned data or download and process a fresh dataset."""

        if use_cached and self.processed_prices_path.exists():
            return self.load_processed()

        prices = self.download()
        cleaned = self.clean(prices)
        self.save_processed(cleaned)
        return cleaned

    def save_processed(self, prices: pd.DataFrame) -> None:
        """Persist cleaned adjusted close prices."""

        self.config.processed_dir.mkdir(parents=True, exist_ok=True)
        prices.to_csv(self.processed_prices_path)

    def load_processed(self) -> pd.DataFrame:
        """Load cleaned adjusted close prices from disk."""

        prices = pd.read_csv(self.processed_prices_path, index_col=0, parse_dates=True)
        return prices.apply(pd.to_numeric, errors="coerce")

