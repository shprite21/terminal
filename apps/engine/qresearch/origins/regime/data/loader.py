from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import pandas as pd
import yfinance as yf

from qresearch.origins.regime.utils.helpers import ensure_directory


LOGGER = logging.getLogger(__name__)


class DataDownloadError(RuntimeError):
    """Raised when market data cannot be downloaded or loaded from cache."""


@dataclass(slots=True)
class MarketDataLoader:
    """Load daily adjusted close prices from Yahoo Finance with local caching."""

    raw_data_dir: Path
    auto_adjust: bool = False
    progress: bool = False
    yfinance_cache_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        self.raw_data_dir = ensure_directory(self.raw_data_dir)
        self.yfinance_cache_dir = ensure_directory(self.raw_data_dir / ".yfinance_cache")
        yf.set_tz_cache_location(str(self.yfinance_cache_dir))

    def load_or_download(
        self,
        tickers: Sequence[str],
        start_date: str,
        end_date: str,
        refresh: bool = False,
    ) -> pd.DataFrame:
        """Load cached prices or download them from Yahoo Finance."""
        cache_path = self._build_cache_path(tickers, start_date, end_date)

        if cache_path.exists() and not refresh:
            LOGGER.info("Loading cached prices from %s", cache_path)
            return self._load_cached_prices(cache_path)

        try:
            prices = self.download_prices(tickers=tickers, start_date=start_date, end_date=end_date)
            prices.to_csv(cache_path, index=True)
            LOGGER.info("Saved raw prices to %s", cache_path)
            return prices
        except Exception as exc:  # pragma: no cover - exercised in integration usage
            if cache_path.exists():
                LOGGER.warning(
                    "Price download failed (%s). Falling back to cached data at %s.",
                    exc,
                    cache_path,
                )
                return self._load_cached_prices(cache_path)

            raise DataDownloadError(
                "Unable to download market data and no cached file is available. "
                "Check network access or place a cached CSV in the raw data directory."
            ) from exc

    def download_prices(self, tickers: Sequence[str], start_date: str, end_date: str) -> pd.DataFrame:
        """Download adjusted close prices from Yahoo Finance."""
        ticker_list = list(dict.fromkeys(tickers))
        if not ticker_list:
            raise ValueError("At least one ticker is required.")

        raw = yf.download(
            tickers=ticker_list,
            start=start_date,
            end=end_date,
            auto_adjust=self.auto_adjust,
            actions=False,
            progress=self.progress,
            group_by="column",
            threads=True,
        )
        if raw.empty:
            raise DataDownloadError("Yahoo Finance returned an empty dataset.")

        prices = self._extract_price_frame(raw=raw, tickers=ticker_list)
        if prices.empty:
            raise DataDownloadError("No adjusted close prices were extracted from Yahoo Finance output.")

        prices.index = pd.to_datetime(prices.index)
        prices.index.name = "Date"
        prices = prices.sort_index()
        prices = prices.apply(pd.to_numeric, errors="coerce")
        return prices

    def _build_cache_path(self, tickers: Sequence[str], start_date: str, end_date: str) -> Path:
        ticker_block = "_".join(sorted(tickers)).lower()
        file_name = f"prices_{ticker_block}_{start_date}_{end_date}.csv"
        return self.raw_data_dir / file_name

    def _load_cached_prices(self, path: Path) -> pd.DataFrame:
        data = pd.read_csv(path, index_col=0, parse_dates=True)
        data.index.name = "Date"
        return data.sort_index()

    @staticmethod
    def _extract_price_frame(raw: pd.DataFrame, tickers: Sequence[str]) -> pd.DataFrame:
        if isinstance(raw.columns, pd.MultiIndex):
            level_zero = raw.columns.get_level_values(0)
            if "Adj Close" in level_zero:
                prices = raw["Adj Close"].copy()
            elif "Close" in level_zero:
                prices = raw["Close"].copy()
            else:
                raise DataDownloadError("Could not find 'Adj Close' or 'Close' in Yahoo Finance response.")
        else:
            price_column = "Adj Close" if "Adj Close" in raw.columns else "Close"
            if price_column not in raw.columns:
                raise DataDownloadError("Could not find a usable price column in Yahoo Finance response.")
            prices = raw[[price_column]].copy()
            prices.columns = [tickers[0]]

        prices = prices.loc[:, ~prices.columns.duplicated()]
        prices.columns = [str(column) for column in prices.columns]
        return prices
