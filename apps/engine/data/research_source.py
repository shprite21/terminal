"""Strict OHLCV acquisition for the research workspace; no implicit demo fallback."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

from data.models import MarketDataBundle
from data.yahoo_runtime import configure_yahoo_cache
from portfolio.custom import MarketDataError


@dataclass
class OHLCVHistory:
    frame: pd.DataFrame
    currency: str
    instrument_type: str


def load_yahoo_ohlcv(symbol: str, period: str) -> OHLCVHistory:
    try:
        configure_yahoo_cache()
        ticker = yf.Ticker(symbol)
        frame = ticker.history(
            period=period,
            interval="1d",
            auto_adjust=True,
            actions=False,
            timeout=20,
            raise_errors=True,
        )
        metadata = ticker.get_history_metadata()
        if frame.empty or not metadata.get("currency"):
            raise MarketDataError(f"No verified price history or currency for {symbol}.")
        today = pd.Timestamp.now(tz=frame.index.tz).normalize()
        frame = frame.loc[frame.index.normalize() < today].copy()
        frame.index = frame.index.tz_localize(None).normalize()
        if frame.index.has_duplicates:
            raise MarketDataError(f"Duplicate daily observations for {symbol}.")
        # yfinance auto_adjust scales OHLC together; preserve that convention.
        return OHLCVHistory(
            frame.sort_index(), str(metadata["currency"]), str(metadata.get("instrumentType", ""))
        )
    except MarketDataError:
        raise
    except Exception as exc:
        raise MarketDataError(
            f"Yahoo Finance could not load {symbol}. Verify the ticker and connection or retry."
        ) from exc


def load_research_bundle(
    symbols: list[str], benchmark: str, period: str, loader=None, source="yahoo"
) -> MarketDataBundle:
    from data.provider_history import load_provider_ohlcv, LABELS
    if loader is None:
        loader = lambda symbol, period: load_provider_ohlcv(symbol, period, source)
    names = list(dict.fromkeys([*symbols, benchmark]))
    with ThreadPoolExecutor(max_workers=1 if source == "massive" else min(6, len(names))) as pool:
        histories = dict(zip(names, pool.map(lambda s: loader(s, period), names)))
    currencies = {history.currency for history in histories.values()}
    if len(currencies) != 1 or not all(currencies):
        raise MarketDataError(
            "Universe and benchmark must have one verified quote currency; FX is not implemented."
        )
    fields = ["Open", "High", "Low", "Close", "Volume"]
    for name, history in histories.items():
        frame = history.frame
        if name in symbols and history.instrument_type not in {"EQUITY", "ETF"}:
            raise MarketDataError(f"{name} is not a supported equity or ETF.")
        if frame.empty or frame.index.has_duplicates or any(field not in frame for field in fields):
            raise MarketDataError(f"Incomplete or duplicate OHLCV history for {name}.")
        numeric = frame[fields].apply(pd.to_numeric, errors="coerce")
        if (
            not np.isfinite(numeric.to_numpy()).all()
            or (numeric[fields[:4]] <= 0).any().any()
            or (numeric["Volume"] < 0).any()
            or (numeric["High"] < numeric[["Open", "Close", "Low"]].max(axis=1)).any()
            or (numeric["Low"] > numeric[["Open", "Close", "High"]].min(axis=1)).any()
        ):
            raise MarketDataError(f"Invalid OHLCV values for {name}; no prices were filled.")
    start = max(h.frame.index.min() for h in histories.values())
    end = min(h.frame.index.max() for h in histories.values())
    aligned = {name: h.frame.loc[start:end, fields].copy() for name, h in histories.items()}
    close = pd.concat({name: f["Close"] for name, f in aligned.items()}, axis=1)
    if close.empty or close.isna().any().any():
        raise MarketDataError(
            "Missing sessions within the shared universe/benchmark window; calendars must align. No forward filling is applied."
        )
    return MarketDataBundle(
        ohlcv={name: aligned[name] for name in symbols},
        benchmark=aligned[benchmark],
        metadata={
            "source": LABELS[source],
            "data_mode": source,
            "currency": next(iter(currencies)),
            "benchmark": benchmark,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "requested_period": period,
            "survivorship_bias": True,
        },
    )


def make_demo_bundle() -> MarketDataBundle:
    # Reuse the repository's seeded research fixture, rather than inventing
    # another set of displayed performance numbers in the frontend.
    from scripts.run_research import make_synthetic_bundle

    bundle = make_synthetic_bundle(seed=7)
    bundle.metadata.update(
        {
            "source": "Seeded synthetic research fixture (seed 7)",
            "data_mode": "demo",
            "currency": "USD",
            "benchmark": "Synthetic equal-price index",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "seed": 7,
        }
    )
    return bundle
