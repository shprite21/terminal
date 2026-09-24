"""Keep Yahoo's SQLite metadata/cookie cache inside the local workspace."""

import threading
import os
from pathlib import Path

import yfinance as yf

_lock = threading.Lock()
_configured = False


def configure_yahoo_cache() -> None:
    global _configured
    with _lock:
        if not _configured:
            cache = Path(os.environ.get('Q_FLAGSHIP_DATA', Path(__file__).resolve().parents[3] / '.data/flagship')) / 'cache/yfinance'
            cache.mkdir(parents=True, exist_ok=True)
            yf.set_tz_cache_location(str(cache))
            _configured = True
