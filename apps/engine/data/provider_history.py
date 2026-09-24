"""Explicit research providers. Massive credentials stay in the local gateway."""
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

LABELS = {'yahoo': 'Yahoo Finance · adjusted OHLCV',
          'massive': 'Massive · split-adjusted OHLCV (cash dividends excluded)',
          'synthetic': 'SYNTHETIC · seeded lognormal scenario v1'}
PERIOD_DAYS = {'6mo': 183, '1y': 365, '2y': 729, '3y': 1095, '5y': 1826, '10y': 3652}


def load_provider_ohlcv(symbol, period='2y', source='yahoo', seed=42):
    from data.research_source import OHLCVHistory, load_yahoo_ohlcv
    from portfolio.custom import MarketDataError
    if source not in LABELS or period not in PERIOD_DAYS:
        raise MarketDataError('Choose Yahoo, Massive or Synthetic and a supported period.')
    if not re.fullmatch(r'[A-Z0-9^][A-Z0-9.^&=_-]{0,39}', symbol):
        raise MarketDataError('Invalid history symbol.')
    if source == 'yahoo':
        return load_yahoo_ohlcv(symbol, period)
    if source == 'massive':
        if PERIOD_DAYS[period] > 729:
            raise MarketDataError('This Massive adapter supports up to two years. Select 2y or less.')
        base = os.environ.get('Q_MARKET_GATEWAY_URL', '')
        address = urlsplit(base)
        token = os.environ.get('Q_ENGINE_TOKEN', '')
        if address.scheme != 'http' or address.hostname != '127.0.0.1' or not token:
            raise MarketDataError('Massive requires the local Q gateway. Connect its API key under Connections.')
        request = Request(base + '/internal/market-history?' + urlencode({'symbol': symbol}),
                          headers={'x-q-engine-token': token})
        try:
            with urlopen(request, timeout=180) as response:
                dataset = json.load(response)
        except Exception:
            raise MarketDataError('Massive history unavailable. Check Connections, US symbol coverage and plan limits; no fallback occurred.') from None
        frame = pd.DataFrame(dataset['chartBars']).rename(columns=str.title)
        frame.index = pd.to_datetime(frame.pop('Date'))
        end = pd.Timestamp(datetime.now(timezone.utc).date())
        frame = frame.loc[(frame.index >= end-pd.Timedelta(days=PERIOD_DAYS[period])) & (frame.index < end)]
        return OHLCVHistory(frame[['Open','High','Low','Close','Volume']], dataset['instrument']['currency'], 'EQUITY')
    if not isinstance(seed, int) or not 0 <= seed < 2**32:
        raise MarketDataError('Synthetic seed must be an integer from 0 to 4294967295.')
    # Fixed end date makes a given symbol/period/seed reproducible on every run.
    end = pd.Timestamp('2025-12-31')
    index = pd.bdate_range(end-pd.Timedelta(days=PERIOD_DAYS[period]), end)
    symbol_seed = int.from_bytes(hashlib.sha256(symbol.encode()).digest()[:4], 'big')
    rng = np.random.default_rng(np.random.SeedSequence([seed, symbol_seed]))
    close = 100*np.exp(np.cumsum(rng.normal(.0002, .02, len(index))))
    opening = np.r_[100, close[:-1]]
    wick = np.abs(rng.normal(0, .01, len(index)))
    frame = pd.DataFrame({'Open': opening, 'High': np.maximum(opening,close)*(1+wick),
                          'Low': np.minimum(opening,close)/(1+wick), 'Close': close,
                          'Volume': rng.integers(10000,1000000,len(index))}, index=index)
    return OHLCVHistory(frame, 'INR' if symbol.endswith('.NS') or symbol=='^NSEI' else 'USD', 'EQUITY')


def terminal_history(symbol, source, period='2y', seed=42):
    if source not in {'yahoo','synthetic'}:
        raise ValueError('This endpoint supports Yahoo or Synthetic; Massive is owned by the gateway.')
    history = load_provider_ohlcv(symbol, period, source, seed)
    frame = history.frame
    rows = [dict(date=day.strftime('%Y-%m-%d'), **{k.lower():float(row[k]) for k in ['Open','High','Low','Close','Volume']}) for day,row in frame.iterrows()]
    return dict(bars=rows, chartBars=rows, currency=history.currency, source=LABELS[source],
                synthetic=source=='synthetic', seed=seed if source=='synthetic' else None,
                priceBasis='Artificial OHLCV; no corporate actions' if source=='synthetic' else 'Yahoo adjusted OHLCV; corporate actions embedded, not separate cash entitlements',
                warnings=['SYNTHETIC: artificial prices and volume; fixed end 2025-12-31; weekday labels are not exchange sessions; not evidence of trading profitability.'] if source=='synthetic' else ['Yahoo adjusted-price research units; splits and dividends are embedded. Whole shares represent adjusted units, not historical deliverable shares.', 'Provider coverage and calendars are not independently verified. No missing observations are filled.'])
