from __future__ import annotations

from datetime import date, timedelta
import hashlib
import ipaddress
import json
import logging
import os
import random
import socket
import threading
import time
from typing import Protocol
import requests

from .models import Instrument
from .storage import Store, atomic_json, digest, now

MASTER_URL = "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json"
DOCS_URL = "https://smartapi.angelone.in/docs"
WINDOWS = {"ONE_MINUTE": 30, "THREE_MINUTE": 60, "FIVE_MINUTE": 100, "TEN_MINUTE": 100,
           "FIFTEEN_MINUTE": 200, "THIRTY_MINUTE": 200, "ONE_HOUR": 400, "ONE_DAY": 2000}


class ProviderError(Exception):
    messages = {"credentials": "Configure Angel One credentials locally before connecting.",
                "auth": "Authentication/session unavailable. Reconnect with a fresh local TOTP.",
                "throttle": "Provider rate limit or access restriction. Retry later.",
                "transient": "Market-data connection unavailable. Retry or resume later.",
                "invalid": "Provider rejected the request. Check instrument, interval, and dates.",
                "malformed": "Provider response failed schema validation.",
                "cancelled": "Download cancelled; completed chunks retained for resume."}

    def __init__(self, kind, detail=None):
        self.kind = kind
        self.detail = detail
        super().__init__(self.messages[kind] + (" " + detail if detail else ""))


class DataProvider(Protocol):
    def candles(self, params: dict) -> list: ...


def credentials():
    import keyring
    result = {}
    for field in ("API_KEY", "CLIENT_CODE", "PIN", "TOTP_SEED"):
        value = os.environ.get("ANGEL_" + field)
        if not value:
            try:
                value = keyring.get_password("evidence-angel-one", field)
            except Exception:
                value = None
        result[field] = value
    return result


def credentials_ready():
    values = credentials()
    return all(values[k] for k in ("API_KEY", "CLIENT_CODE", "PIN"))


class SharedThrottle:
    """SQLite reservations serialize client-wide requests across local workers/processes."""
    def __init__(self, store, account, clock=time.time, sleeper=time.sleep):
        self.store, self.account, self.clock, self.sleep = store, account, clock, sleeper

    def acquire(self, cancelled=lambda: False):
        while True:
            if cancelled():
                raise ProviderError("cancelled")
            ts = self.clock()
            with self.store.db() as con:
                con.execute("BEGIN IMMEDIATE")
                con.execute("DELETE FROM requests WHERE ts < ?", (ts - 3601,))
                stamps = [r[0] for r in con.execute("SELECT ts FROM requests WHERE account=? ORDER BY ts", (self.account,))]
                waits = []
                # Stricter of conflicting official documentation: 150, not 180/minute.
                for seconds, limit in ((1, 3), (60, 150), (3600, 5000)):
                    window = [v for v in stamps if v > ts - seconds]
                    if len(window) >= limit:
                        waits.append(window[-limit] + seconds - ts + .01)
                if not waits:
                    con.execute("INSERT INTO requests VALUES(?,?)", (self.account, ts))
                    return
            self.sleep(min(max(waits), .5))


_sdk_lock = threading.Lock()


def make_sdk(api_key):
    """Use official entry points with a strict read-only, sanitized HTTPS transport.

    SDK 1.5.5 has import-time IP discovery without a timeout and logs secrets on
    failures. Bound import-time GETs, suppress its logger before import, bypass
    its log-file constructor, and deny every route outside this allowlist.
    """
    import logzero
    logzero.logger.disabled = True
    logging.getLogger("SmartApi.smartConnect").disabled = True
    with _sdk_lock:
        original_get = requests.get
        def bounded_get(*args, **kwargs):
            kwargs.setdefault("timeout", 5)
            return original_get(*args, **kwargs)
        requests.get = bounded_get
        try:
            from SmartApi import SmartConnect
        finally:
            requests.get = original_get

    class ReadOnlySmartConnect(SmartConnect):
        allowed = {"api.login", "api.token", "api.user.profile", "api.logout", "api.candle.data"}

        def __init__(self):
            self.api_key = self.privateKey = api_key
            self.access_token = self.refresh_token = self.feed_token = None
            self.userId = None
            self.debug = False
            self.clientLocalIp = socket.gethostbyname(socket.gethostname())
            try:
                response = original_get("https://api.ipify.org", timeout=5)
                response.raise_for_status()
                self.clientPublicIp = str(ipaddress.ip_address(response.text.strip()))
            except Exception:
                raise ProviderError("transient") from None

        def _request(self, route, method, parameters=None):
            if route not in self.allowed:
                raise ProviderError("invalid")
            headers = self.requestHeaders()
            if self.access_token:
                headers["Authorization"] = "Bearer " + self.access_token
            try:
                response = requests.request(method, self._rootUrl + self._routes[route],
                    json=parameters if method == "POST" else None,
                    params=parameters if method == "GET" else None,
                    headers=headers, timeout=(5, 20), allow_redirects=False)
                if response.status_code == 401:
                    raise ProviderError("auth")
                if response.status_code in (403, 429):
                    raise ProviderError("throttle")
                if response.status_code >= 500:
                    raise ProviderError("transient")
                if response.status_code != 200:
                    raise ProviderError("invalid")
                try:
                    data = response.json()
                except ValueError:
                    raise ProviderError("malformed", "HTTP 200 body was not valid JSON.") from None
                check_response(data)
                return data
            except requests.RequestException:
                raise ProviderError("transient") from None

    return ReadOnlySmartConnect()


def check_response(response):
    if not isinstance(response, dict):
        raise ProviderError("malformed", "Expected a JSON object for the response envelope.")
    if not isinstance(response.get("status"), bool):
        raise ProviderError("malformed", "Response status is missing or is not a boolean.")
    if not response["status"]:
        code = response.get("errorcode")
        if code in {"AG8001", "AG8002", "AG8003", "AB1007", "AB1010", "AB1050"}:
            raise ProviderError("auth")
        if code in {"AB1004", "AB2000"}:
            raise ProviderError("transient")
        raise ProviderError("invalid")
    if "data" not in response:
        raise ProviderError("malformed", "Successful response is missing its data field.")


class AngelOneDataProvider:
    def __init__(self, store, sdk=None, account=None, sleeper=time.sleep):
        self.store, self.sdk, self.sleep = store, sdk, sleeper
        self.account = account
        self.throttle = SharedThrottle(store, account) if account else None
        self.connected = sdk is not None

    def connect(self, totp=None):
        values = credentials()
        if not all(values[k] for k in ("API_KEY", "CLIENT_CODE", "PIN")):
            raise ProviderError("credentials")
        if not totp and values["TOTP_SEED"]:
            import pyotp
            try:
                totp = pyotp.TOTP(values["TOTP_SEED"]).now()
            except Exception:
                raise ProviderError("credentials") from None
        if not totp or len(totp) != 6 or not totp.isdigit():
            raise ProviderError("auth")
        try:
            self.sdk = make_sdk(values["API_KEY"])
            check_response(self.sdk.generateSession(values["CLIENT_CODE"], values["PIN"], totp))
        except ProviderError:
            self.connected = False
            raise
        except Exception:
            self.connected = False
            raise ProviderError("auth") from None
        self.account = hashlib.sha256(values["CLIENT_CODE"].encode()).hexdigest()
        self.throttle = SharedThrottle(self.store, self.account)
        self.connected = True

    def candles(self, params, cancelled=lambda: False):
        if not self.connected or not self.sdk:
            raise ProviderError("credentials")
        refreshed = False
        for attempt in range(4):
            if cancelled():
                raise ProviderError("cancelled")
            self.throttle.acquire(cancelled)
            try:
                response = self.sdk.getCandleData(dict(params))
                check_response(response)
                rows = response["data"]
                if rows is None:
                    return []
                if not isinstance(rows, list):
                    raise ProviderError("malformed", "Candle data is not an array.")
                for index, row in enumerate(rows):
                    if not isinstance(row, list):
                        raise ProviderError("malformed", f"Candle row {index + 1} is not an array.")
                    if len(row) != 6:
                        raise ProviderError("malformed", f"Candle row {index + 1} has {len(row)} fields; expected timestamp and five OHLCV fields.")
                return rows
            except (TimeoutError, ConnectionError, requests.RequestException):
                error = ProviderError("transient")
            except ProviderError as exc:
                error = exc
            except Exception as exc:
                # Use fixed categories only: SDK exception messages can contain secrets.
                category = "attribute access" if isinstance(exc, AttributeError) else "type handling" if isinstance(exc, TypeError) else "internal SDK processing"
                error = ProviderError("malformed", "Failed during " + category + "; no candle response was accepted.")
            if error.kind == "auth" and not refreshed and getattr(self.sdk, "refresh_token", None):
                refreshed = True
                try:
                    self.sleep(1.05)
                    check_response(self.sdk.generateToken(self.sdk.refresh_token))
                    continue
                except Exception:
                    self.connected = False
                    raise ProviderError("auth") from None
            if error.kind not in {"throttle", "transient"} or attempt == 3:
                if error.kind == "auth":
                    self.connected = False
                raise error from None
            # Randomness is solely transport retry jitter; never market observations.
            for _ in range(2 ** attempt * 2):
                if cancelled():
                    raise ProviderError("cancelled")
                self.sleep(.5 + random.SystemRandom().random() * .1)
        raise ProviderError("transient")


def fetch_master(store):
    try:
        response = requests.get(MASTER_URL, timeout=(5, 30))
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list):
            raise ValueError()
        raw_hash = digest(response.content)
        version = store.put("instrument_master", {"source": MASTER_URL, "retrieved_at": now(), "raw_sha256": raw_hash, "rows": rows})
        return version
    except Exception:
        raise ProviderError("transient") from None


def search_master(store, version, query):
    rows = store.get(version, "instrument_master")["rows"]
    matches = []
    for row in rows:
        if row.get("exch_seg") != "NSE" or not row.get("symbol", "").endswith("-EQ") or row.get("instrumenttype", "") not in ("", "EQ"):
            continue
        if query.upper() not in row["symbol"]:
            continue
        matches.append(Instrument(id=f"NSE:{row['token']}:{row['symbol']}", symbol=row["symbol"], token=str(row["token"]), mapping_version=version))
    if len({m.id for m in matches}) != len(matches):
        raise ValueError("Ambiguous instrument master: duplicate mappings")
    return matches


def validate_mappings(store, instruments):
    for instrument in instruments:
        master = store.get(instrument.mapping_version, "instrument_master")
        matches = [r for r in master["rows"] if r.get("exch_seg") == instrument.exchange and r.get("symbol") == instrument.symbol and str(r.get("token")) == instrument.token]
        if len(matches) != 1 or instrument.instrument_type != "cash_equity" or not instrument.symbol.endswith("-EQ"):
            raise ValueError("Missing or ambiguous instrument mapping; refresh and reselect")


def chunks(start, end, interval="ONE_DAY"):
    if start > end or interval not in WINDOWS:
        raise ValueError("Invalid range or interval")
    while start <= end:
        stop = min(start + timedelta(days=WINDOWS[interval] - 1), end)
        yield start, stop
        start = stop + timedelta(days=1)


def download(provider, store, instruments, start: date, end: date, cancelled=lambda: False, progress=lambda a,b: None, refresh=False):
    if not instruments or len({i.id for i in instruments}) != len(instruments):
        raise ValueError("Select unique real instruments")
    if start > end:
        raise ValueError("Start must precede end")
    request = {"instruments": [i.model_dump(mode="json") for i in instruments], "start": str(start), "end": str(end), "interval": "ONE_DAY"}
    key = digest(request)
    checkpoint = store.root / "downloads" / (key + ".json")
    state = json.loads(checkpoint.read_text()) if checkpoint.exists() and not refresh else {"request": request, "chunks": {}}
    if state["request"] != request:
        raise ValueError("Checkpoint request does not match")
    work = [(i, a, b) for i in instruments for a, b in chunks(start, end)]
    store.event(key, "download_started", request)
    try:
        for index, (instrument, first, last) in enumerate(work):
            if cancelled():
                raise ProviderError("cancelled")
            chunk_key = digest([instrument.id, first, last])
            if chunk_key not in state["chunks"]:
                params = {"exchange": "NSE", "symboltoken": instrument.token, "interval": "ONE_DAY", "fromdate": str(first) + " 00:00", "todate": str(last) + " 23:59"}
                rows = provider.candles(params, cancelled)
                state["chunks"][chunk_key] = {"instrument": instrument.id, "request": params, "retrieved_at": now(), "rows": rows, "sha256": digest(rows)}
                atomic_json(checkpoint, state)
            progress(index + 1, len(work))
        store.event(key, "download_completed", {"chunks": len(work)})
    except ProviderError as exc:
        store.event(key, "download_" + ("cancelled" if exc.kind == "cancelled" else "failed"), {"reason": exc.kind})
        raise
    return state
