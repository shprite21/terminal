"""User-defined, long-only portfolios: adjusted-price buy-and-hold research.

This is a retrospective allocation replay, not an executable strategy or an
out-of-sample backtest. No orders are created by this module.
"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

import numpy as np
import pandas as pd
import yfinance as yf
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from analytics.metrics import aggregate_metrics, drawdown_series, sharpe_ratio
from data.yahoo_runtime import configure_yahoo_cache


class HoldingInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    ticker: str = Field(min_length=1, max_length=20, pattern=r"^[A-Z0-9^][A-Z0-9.^=-]*$")
    weight: float = Field(gt=0, le=100)

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_ticker(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value


class PortfolioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    holdings: list[HoldingInput] = Field(min_length=1, max_length=30)
    source: Literal["yahoo", "massive", "synthetic"] = "yahoo"
    period: Literal["6mo", "1y", "2y", "5y"] = "1y"
    benchmark: str = "SPY"
    initial_capital: float = Field(default=100_000, ge=1, le=1_000_000_000)
    risk_free_rate: float = Field(default=0, ge=0, le=25)

    @field_validator("benchmark", mode="before")
    @classmethod
    def validate_benchmark(cls, value: Any) -> str:
        return HoldingInput(ticker=value, weight=100).ticker

    @model_validator(mode="after")
    def validate_allocation(self) -> "PortfolioRequest":
        symbols = [item.ticker for item in self.holdings]
        if len(symbols) != len(set(symbols)):
            raise ValueError("Each ticker must appear only once.")
        if abs(sum(item.weight for item in self.holdings) - 100) > 0.000001:
            raise ValueError("Portfolio weights must total 100%.")
        return self


class MarketDataError(ValueError):
    """A recoverable upstream data or coverage failure safe to show in the UI."""


@dataclass(frozen=True)
class PriceHistory:
    close: pd.Series
    currency: str
    instrument_type: str = "EQUITY"


def load_yahoo_history(symbol: str, period: str) -> PriceHistory:
    """Read adjusted daily closes and their quote currency; never fabricate data."""
    try:
        configure_yahoo_cache()
        ticker = yf.Ticker(symbol)
        frame = ticker.history(
            period=period,
            interval="1d",
            auto_adjust=True,
            actions=False,
            timeout=15,
            raise_errors=True,
        )
        if frame.empty or "Close" not in frame:
            raise MarketDataError(f"No price history for {symbol}. Check the Yahoo Finance ticker.")
        metadata = ticker.get_history_metadata()
        currency = metadata.get("currency")
        if not currency:
            raise MarketDataError(f"Cannot verify the quote currency for {symbol}.")
        close = pd.to_numeric(frame["Close"], errors="coerce").copy()
        # Exclude the exchange's current calendar day, even after close, so an
        # intraday partial bar can never masquerade as a completed daily return.
        today = pd.Timestamp.now(tz=close.index.tz).normalize()
        close = close.loc[close.index.normalize() < today]
        close.index = close.index.tz_localize(None).normalize()
        close = close[~close.index.duplicated(keep="last")].sort_index()
        close.name = symbol
        return PriceHistory(close, str(currency), str(metadata.get("instrumentType", "")))
    except MarketDataError:
        raise
    except Exception as exc:
        # yfinance has multiple transport/provider exception types. Preserve the
        # cause for server logs without exposing internal details to the browser.
        raise MarketDataError(
            f"Yahoo Finance could not load {symbol}. Check the ticker and connection, "
            "or retry later if Yahoo is rate-limiting requests."
        ) from exc


def analyze_portfolio(
    request: PortfolioRequest,
    loader: Callable[[str, str], PriceHistory] | None = None,
) -> dict[str, Any]:
    from data.provider_history import load_provider_ohlcv, LABELS
    if loader is None:
        def loader(symbol, period):
            history = load_provider_ohlcv(symbol, period, request.source)
            return PriceHistory(history.frame["Close"], history.currency, history.instrument_type)
    symbols = list(dict.fromkeys([item.ticker for item in request.holdings] + [request.benchmark]))
    with ThreadPoolExecutor(max_workers=1 if request.source == "massive" else min(6, len(symbols))) as pool:
        histories = dict(zip(symbols, pool.map(lambda s: loader(s, request.period), symbols)))
    currencies = {item.currency for item in histories.values()}
    if len(currencies) != 1:
        raise MarketDataError(
            "All holdings and the benchmark must use the same quote currency. "
            "FX conversion is not implemented; use SPY for USD or ^NSEI for INR."
        )
    for holding in request.holdings:
        if histories[holding.ticker].instrument_type not in {"EQUITY", "ETF"}:
            raise MarketDataError(f"{holding.ticker} is not a supported equity or ETF.")
    for symbol, history in histories.items():
        observed = history.close.dropna()
        if observed.empty or not np.isfinite(observed).all() or (observed <= 0).any():
            raise MarketDataError(f"Invalid or missing prices for {symbol}.")
    raw = pd.concat({symbol: history.close for symbol, history in histories.items()}, axis=1, sort=True)
    raw = raw.sort_index()
    prices = raw.dropna(how="any")
    if len(prices) < 22:
        raise MarketDataError("At least 22 common daily prices are required across all tickers.")
    internal = raw.loc[prices.index[0] : prices.index[-1]]
    if len(internal) != len(prices):
        missing = internal.isna().sum()
        detail = ", ".join(f"{symbol}: {int(count)}" for symbol, count in missing.items() if count)
        raise MarketDataError(
            f"Missing daily prices inside the common history window ({detail}). "
            "Provider coverage or trading calendars differ. Try another same-currency "
            "benchmark or history window; missing prices have not been filled."
        )
    holdings = [item.ticker for item in request.holdings]
    weights = pd.Series({item.ticker: item.weight / 100 for item in request.holdings})
    relatives = prices[holdings].div(prices[holdings].iloc[0])
    values = relatives.mul(weights).mul(request.initial_capital)
    equity = values.sum(axis=1)
    returns = equity.pct_change(fill_method=None).dropna()
    benchmark = prices[request.benchmark].div(prices[request.benchmark].iloc[0])
    benchmark_equity = benchmark * request.initial_capital
    benchmark_returns = benchmark_equity.pct_change(fill_method=None).dropna()
    metrics = aggregate_metrics(returns, equity)
    metrics["sharpe"] = sharpe_ratio(returns, risk_free_rate=request.risk_free_rate / 100)
    variance = float(benchmark_returns.var())
    metrics.update(
        {
            "benchmark_return": float(benchmark.iloc[-1] - 1),
            "excess_return": float(equity.iloc[-1] / request.initial_capital - benchmark.iloc[-1]),
            "beta": float(returns.cov(benchmark_returns) / variance) if variance > 0 else np.nan,
            "ending_value": float(equity.iloc[-1]),
            "effective_holdings": float(1 / weights.pow(2).sum()),
        }
    )
    drawdowns = drawdown_series(equity)
    asset_returns = prices[holdings].pct_change(fill_method=None).dropna()
    warnings = [
        (
            "Retrospective buy-and-hold replay of today's selected tickers, not an out-of-sample "
            "strategy test. Selection and survivorship bias can materially affect results."
        ),
        (
            f"{LABELS[request.source]}. Fractional "
            "allocations are assumed; fees, taxes, slippage, FX and live execution are excluded."
        ),
        (
            "Targets apply only on the first date. Positions drift without rebalancing. "
            "The current exchange calendar day's bar is excluded; quotes are not real-time."
        ),
        (
            "Risk statistics use 252 observations per year; Sharpe uses your constant annual "
            "risk-free rate. These assumptions may not match every market."
        ),
    ]
    if request.source == "synthetic":
        warnings.insert(0, "SYNTHETIC: artificial per-symbol scenarios, seed 42, fixed end 2025-12-31; weekday labels are not exchange sessions. No observed market performance.")
    if len(raw) != len(prices):
        warnings.insert(
            0,
            "History was shortened to the shared coverage of all holdings and "
            "the benchmark. No missing prices were forward-filled.",
        )
    return {
        "source": LABELS[request.source],
        "synthetic": request.source == "synthetic",
        "seed": 42 if request.source == "synthetic" else None,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "currency": next(iter(currencies)),
        "start_date": prices.index[0].strftime("%Y-%m-%d"),
        "end_date": prices.index[-1].strftime("%Y-%m-%d"),
        "observations": len(prices),
        "method": "buy_and_hold",
        "request": request.model_dump(),
        "metrics": {
            key: float(value) if np.isfinite(value) else None for key, value in metrics.items()
        },
        "holdings": [
            {
                "ticker": symbol,
                "target_weight": float(weights[symbol] * 100),
                "ending_weight": float(values[symbol].iloc[-1] / equity.iloc[-1] * 100),
                "latest_adjusted_close": float(prices[symbol].iloc[-1]),
                "total_return": float(relatives[symbol].iloc[-1] - 1),
                "return_contribution": float(weights[symbol] * (relatives[symbol].iloc[-1] - 1)),
                "annualized_volatility": float(asset_returns[symbol].std() * np.sqrt(252)),
                "initial_allocation": float(weights[symbol] * request.initial_capital),
                "ending_value": float(values[symbol].iloc[-1]),
            }
            for symbol in holdings
        ],
        "equity_curve": [
            {
                "date": date.strftime("%Y-%m-%d"),
                "portfolio": float(equity.loc[date]),
                "benchmark": float(benchmark_equity.loc[date]),
                "drawdown": float(drawdowns.loc[date]),
            }
            for date in prices.index
        ],
        "warnings": warnings,
    }
