from __future__ import annotations

from datetime import date, datetime, timezone
import json
from zoneinfo import ZoneInfo
import pandas as pd
import numpy as np
from .models import Source, Instrument, Calendar
from .storage import Store, digest, now
from .actions import validated_actions, split_factor

TZ = ZoneInfo("Asia/Kolkata")
COLUMNS = ["instrument", "date", "open", "high", "low", "close", "volume", "available_at"]


def normalize_download(state, calendar):
    rows = []
    for chunk in state["chunks"].values():
        if digest(chunk["rows"]) != chunk["sha256"]:
            raise ValueError("Download checkpoint integrity failure")
        for timestamp, opening, high, low, close, volume in chunk["rows"]:
            stamp = datetime.fromisoformat(timestamp)
            if stamp.tzinfo is None:
                raise ValueError("Provider timestamp lacks timezone")
            day = stamp.astimezone(TZ).date()
            session = calendar.sessions.get(day)
            if session is None:
                raise ValueError("Provider returned a session absent from the supplied calendar")
            rows.append([chunk["instrument"], day.isoformat(), opening, high, low, close, volume, session[1].isoformat()])
    return pd.DataFrame(rows, columns=COLUMNS)


def validate_bars(frame, instruments, calendar, start, end, asof=None, actions=()):
    asof = asof or datetime.now(timezone.utc)
    if set(frame.columns) != set(COLUMNS):
        raise ValueError("Required columns: " + ", ".join(COLUMNS))
    data = frame.copy()
    if data.empty:
        raise ValueError("Unavailable: no real historical observations")
    if not calendar.coverage_start <= start <= end <= calendar.coverage_end:
        raise ValueError("Calendar does not cover the full requested period")
    ids = {i.id for i in instruments}
    actions = validated_actions(actions, calendar, ids)
    if not set(data.instrument).issubset(ids):
        raise ValueError("Unknown instruments")
    data["date"] = data["date"].map(lambda v: date.fromisoformat(str(v)))
    data["available_at"] = data.available_at.map(lambda v: datetime.fromisoformat(str(v)))
    for col in ["open", "high", "low", "close", "volume"]:
        data[col] = pd.to_numeric(data[col], errors="raise")
    if not np.isfinite(data[["open", "high", "low", "close", "volume"]].to_numpy(dtype=float)).all():
        raise ValueError("Non-finite market observations")
    if ((data[["open", "high", "low", "close"]] <= 0).any().any() or (data.volume < 0).any()
        or (data.high < data[["open", "close", "low"]].max(axis=1)).any()
        or (data.low > data[["open", "close", "high"]].min(axis=1)).any()):
        raise ValueError("Invalid OHLC relationships, prices, or volume")
    # Identical overlap is explicitly counted and deduplicated; conflicts reject.
    overlaps = int(data.duplicated(["instrument", "date"]).sum())
    for _, group in data.groupby(["instrument", "date"]):
        if len(group.drop_duplicates()) > 1:
            raise ValueError("Conflicting duplicate observations")
    data = data.drop_duplicates().sort_values(["date", "instrument"]).reset_index(drop=True)
    if ((data.date < start) | (data.date > end)).any():
        raise ValueError("Returned data outside requested range")
    expected = {d for d in calendar.sessions if start <= d <= end}
    if not expected:
        raise ValueError("No eligible exchange sessions in requested period")
    for row in data.itertuples():
        if row.date not in expected:
            raise ValueError("Unexpected session; inspect the exchange calendar")
        if row.available_at.tzinfo is None or row.available_at < calendar.sessions[row.date][1]:
            raise ValueError("Daily candle cannot be available before session close")
        if calendar.sessions[row.date][1] >= asof or row.available_at > asof:
            raise ValueError("Incomplete or not-yet-available candles are quarantined; freezing blocked")
    missing = {i: sorted(str(d) for d in expected - set(data[data.instrument == i].date)) for i in sorted(ids)}
    discontinuities = []
    for instrument, group in data.groupby("instrument"):
        history = list(group.sort_values("date").itertuples())
        for previous, current in zip(history, history[1:]):
            value = current.close * split_factor(actions, instrument, previous.date, current.date) / previous.close - 1
            if abs(value) > .25:
                discontinuities.append({"instrument": instrument, "date": str(current.date), "return": float(value)})
    report = {"status": "blocked" if any(missing.values()) or discontinuities else "ready_with_limitations",
              "requested_start": str(start), "requested_end": str(end), "returned_start": str(data.date.min()), "returned_end": str(data.date.max()),
              "rows": len(data), "expected_sessions": len(expected), "missing_sessions": missing,
              "identical_overlaps_removed": overlaps, "unexplained_discontinuities": discontinuities,
              "zero_volume_rows": int((data.volume == 0).sum())}
    data["date"] = data.date.map(str)
    data["available_at"] = data.available_at.map(lambda v: v.isoformat())
    return data, report


def freeze_dataset(store, frame, source, instruments, calendar, start, end, price_note, raw_payload=None, actions=()):
    source = Source.model_validate(source)
    instruments = [Instrument.model_validate(i) for i in instruments]
    calendar = Calendar.model_validate(calendar)
    if len(price_note.strip()) < 20:
        raise ValueError("Document evidence for raw-price convention; adjustment status must be verified")
    if raw_payload is None or digest(raw_payload) != source.raw_sha256:
        raise ValueError("Original source payload and matching SHA-256 required")
    normalized, quality = validate_bars(frame, instruments, calendar, start, end, actions=actions)
    actions = validated_actions(actions, calendar, {i.id for i in instruments})
    # Persist rejected quality reviews as first-class artifacts, without sample results.
    if quality["status"] == "blocked":
        review = store.put("quality_review", {"source": source.model_dump(mode="json"), "quality": quality})
        raise ValueError("Dataset blocked: missing sessions or unexplained discontinuities. Review " + review[:12])
    rows = normalized.to_dict("records")
    body = {"source": source.model_dump(mode="json"), "instruments": [i.model_dump(mode="json") for i in instruments],
            "calendar": calendar.model_dump(mode="json"), "quality": quality, "rows_sha256": digest(rows), "rows": rows,
            "ingestion_version": "1", "price_convention": "raw_price_return", "price_note": price_note,
            "corporate_actions": [a.model_dump(mode="json") for a in actions],
            "limitations": ["Selected instruments may have survivorship bias: historical membership and delisted coverage unverified.",
                             "Raw prices; only explicitly sourced splits and cash dividends are accounted for. Completeness of corporate-action coverage is unverified; not a certified total-return history. Bonus, rights, mergers, fractional entitlements and delistings are blocked until modeled.",
                             "Daily candles do not establish bid-ask spreads, intrabar sequence, or executable opening liquidity."]}
    key = store.put("dataset", body)
    payload_path = store.root / "raw" / (source.raw_sha256 + ".bin")
    payload_path.parent.mkdir(exist_ok=True)
    if not payload_path.exists():
        payload_path.write_bytes(raw_payload)
    return key


def load_dataset(store, key):
    body = store.get(key, "dataset")
    if digest(body["rows"]) != body["rows_sha256"]:
        raise ValueError("Dataset integrity failure")
    raw = store.root / "raw" / (body["source"]["raw_sha256"] + ".bin")
    if not raw.exists() or digest(raw.read_bytes()) != body["source"]["raw_sha256"]:
        raise ValueError("Source payload missing or altered")
    return body, pd.DataFrame(body["rows"])
