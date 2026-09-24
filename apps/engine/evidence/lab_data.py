"""Explicit real/synthetic bar datasets for the exploratory research lab."""
from datetime import date, timedelta
import re
import numpy as np
import pandas as pd
from .storage import digest, now

INTERVALS = {"1m": 1, "5m": 5, "15m": 15, "1d": 1440}
BAR_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def validate_bars(frame):
    if not set(BAR_COLUMNS).issubset(frame.columns) or frame.empty:
        raise ValueError("No usable OHLCV observations returned; no substitute was generated.")
    frame = frame[BAR_COLUMNS].copy()
    timestamps = pd.to_datetime(frame.timestamp, utc=True)
    if timestamps.isna().any() or timestamps.duplicated().any() or not timestamps.is_monotonic_increasing:
        raise ValueError("Bar timestamps must be unique and increasing.")
    numeric = frame[BAR_COLUMNS[1:]].astype(float)
    if not np.isfinite(numeric.to_numpy()).all():
        raise ValueError("Missing or non-finite market fields; dataset blocked.")
    if (numeric[["open", "high", "low", "close"]] <= 0).any().any() or (numeric.volume < 0).any():
        raise ValueError("Invalid price or volume.")
    if ((numeric.high < numeric[["open", "close", "low"]].max(axis=1)) |
            (numeric.low > numeric[["open", "close", "high"]].min(axis=1))).any():
        raise ValueError("Inconsistent OHLC observations.")
    frame[BAR_COLUMNS[1:]] = numeric
    return frame


def save_bars(store, frame, source, request, timezone, currency, limitations):
    frame = validate_bars(frame)
    rows = frame.to_dict("records")
    local = pd.to_datetime(frame.timestamp, utc=True).dt.tz_convert(timezone)
    actual = {"first": str(local.iloc[0]), "last": str(local.iloc[-1]), "bars": len(frame),
              "sessions": local.dt.date.nunique()}
    warnings = list(limitations)
    if str(local.iloc[0].date()) != request["start"] or str(local.iloc[-1].date()) != request["end"]:
        warnings.append("Returned first/last dates differ from requested bounds (holidays, listings or provider coverage). Review actual coverage before running.")
    delta = local.diff().dt.total_seconds()
    same_day = local.dt.date == local.shift().dt.date
    gaps = int(((delta > INTERVALS[request["interval"]] * 60) & same_day).sum())
    if gaps:
        warnings.append(f"{gaps} within-session timestamp gaps; no observations were filled in.")
    body = {"name": f"{source['kind']} · {request['symbol']} · {request['interval']}",
            "source": source, "request": request, "timezone": timezone, "currency": currency,
            "actual": actual, "limitations": warnings, "rows": rows, "rows_sha256": digest(rows)}
    return store.put("lab_dataset", body)


def yahoo_history(store, symbol, start, end, interval="1d"):
    """Dates inclusive in our UI; Yahoo's end parameter is exclusive."""
    import yfinance as yf
    from data.yahoo_runtime import configure_yahoo_cache
    configure_yahoo_cache()
    symbol = symbol.strip().upper()
    if not re.fullmatch(r"[A-Z0-9.^=\-]{1,30}", symbol):
        raise ValueError("Enter a single Yahoo ticker, e.g. RELIANCE.NS.")
    if interval not in INTERVALS or start > end or end >= date.today():
        raise ValueError("Choose a valid interval and completed dates ending before today.")
    retention = 7 if interval == "1m" else 60
    if interval != "1d" and start < date.today() - timedelta(days=retention):
        raise ValueError(f"This adapter limits {interval} requests to the last {retention} days. Choose a recent range; it will not shorten your request.")
    if interval == "1d" and (end - start).days > 7300:
        raise ValueError("Limit a daily request to 20 years.")
    request = {"symbol": symbol, "start": str(start), "end": str(end), "interval": interval}
    ticker = yf.Ticker(symbol)
    try:
        history = ticker.history(start=str(start), end=str(end + timedelta(days=1)), interval=interval,
                                 auto_adjust=True, back_adjust=False, repair=False, actions=True,
                                 prepost=False, keepna=True, timeout=20, raise_errors=True)
        metadata = ticker.get_history_metadata()
    except Exception as exc:
        raise ValueError(f"Yahoo download unavailable ({type(exc).__name__}). Retry later or explicitly select Synthetic; no fallback occurred.") from None
    if history.empty:
        raise ValueError("Yahoo returned no observations. No fallback occurred.")
    tz = str(history.index.tz) if history.index.tz is not None else metadata.get("exchangeTimezoneName")
    if not tz:
        raise ValueError("Yahoo did not supply an exchange timezone.")
    if history.index.tz is None:
        history.index = history.index.tz_localize(tz)
    frame = history.rename(columns=str.lower).copy()
    frame["timestamp"] = [t.isoformat() for t in history.index]
    local_dates = history.index.date
    if any(d < start or d > end for d in local_dates):
        raise ValueError("Yahoo returned observations outside the requested dates.")
    source = {"kind": "REAL · Yahoo Finance", "provider": "Yahoo Finance via yfinance", "synthetic": False,
              "url": "https://finance.yahoo.com/quote/" + symbol + "/history/", "retrieved_at": now(),
              "yfinance_version": yf.__version__, "auto_adjust": True, "repair": False,
              "returned_payload_sha256": digest(history.to_csv().encode()),
              "returned_payload_csv": history.to_csv()}
    return save_bars(store, frame, source, request, tz, metadata.get("currency", "quote units"), [
        "Yahoo adjusted OHLC: research in adjusted-price units; dividends/splits are embedded, not separate cash entitlements.",
        "No independently verified exchange calendar or historical universe. Missing sessions and delisted instruments may be absent.",
        "OHLCV has no order-book, queue or exchange latency observations. Not suitable for empirical latency-arbitrage testing.",
        "Yahoo data through yfinance is intended for personal research; availability and intraday retention vary."])


def synthetic_history(store, start, end, interval="1d", seed=42, volatility=0.02, drift=0.0002):
    if interval not in INTERVALS or start > end or (end-start).days > 3650:
        raise ValueError("Choose valid dates within ten years and a supported interval.")
    if not 0 <= seed < 2**32 or not 0 <= volatility <= .2 or not -.1 <= drift <= .1:
        raise ValueError("Invalid synthetic process parameters.")
    days = pd.bdate_range(start, end, tz="Asia/Kolkata")
    if not len(days):
        raise ValueError("No synthetic weekday sessions in the selected period.")
    if interval == "1d":
        index = days + pd.Timedelta(hours=9, minutes=15)
        scale = 1
    else:
        index = pd.DatetimeIndex([t for d in days for t in pd.date_range(
            d + pd.Timedelta(hours=9, minutes=15), d + pd.Timedelta(hours=15, minutes=30),
            freq=f"{INTERVALS[interval]}min", inclusive="left")])
        scale = INTERVALS[interval] / 375
    if len(index) > 100000:
        raise ValueError("Synthetic request exceeds 100,000 bars; reduce the range.")
    rng = np.random.default_rng(seed)
    returns = rng.normal((drift - volatility**2/2)*scale, volatility*np.sqrt(scale), len(index))
    close = 100 * np.exp(np.cumsum(returns))
    opening = np.r_[100, close[:-1]]
    wick = np.abs(rng.normal(0, volatility*np.sqrt(scale)/2, len(index)))
    frame = pd.DataFrame({"timestamp": [t.isoformat() for t in index], "open": opening,
                          "high": np.maximum(opening, close)*(1+wick), "low": np.minimum(opening, close)/(1+wick),
                          "close": close, "volume": rng.integers(1000, 10000, len(index))})
    source = {"kind": "SYNTHETIC", "provider": "Seeded lognormal scenario v1", "synthetic": True,
              "seed": seed, "daily_volatility": volatility, "daily_drift": drift,
              "numpy_version": np.__version__}
    return save_bars(store, frame, source, {"symbol": "SYNTH", "start": str(start), "end": str(end), "interval": interval},
                     "Asia/Kolkata", "scenario units", ["SYNTHETIC MARKET: artificial prices and volume, not evidence of a real trading edge.",
                     "Weekday 09:15–15:30 sessions are assumed; holidays are not modeled."])


def load_bars(store, key):
    dataset = store.get(key, "lab_dataset")
    if digest(dataset["rows"]) != dataset["rows_sha256"]:
        raise ValueError("Dataset integrity check failed.")
    return dataset, validate_bars(pd.DataFrame(dataset["rows"]))


def massive_history(store, symbol, start, end, interval='1d'):
    from data.provider_history import load_provider_ohlcv, LABELS
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date()
    if interval != '1d' or start > end or end >= today or start < today-timedelta(days=729):
        raise ValueError('Massive supports completed US daily history within the last 729 days. Select 1d and a supported range.')
    history = load_provider_ohlcv(symbol.strip().upper(), '2y', 'massive')
    frame = history.frame.loc[str(start):str(end)].rename(columns=str.lower).copy()
    # Daily research labels in UTC, never timestamps implying intraday execution.
    frame['timestamp'] = [t.tz_localize('UTC').isoformat() for t in frame.index]
    return save_bars(store, frame, {'kind':'REAL · Massive','provider':LABELS['massive'],'synthetic':False,'retrieved_at':now()},
                     {'symbol':symbol.strip().upper(),'start':str(start),'end':str(end),'interval':interval},
                     'UTC', history.currency, ['Massive split-adjusted daily research units; cash dividends are excluded.',
                     'Daily timestamps are session-date labels, not intraday quotes. No order-book, latency or independently verified exchange calendar.'])
