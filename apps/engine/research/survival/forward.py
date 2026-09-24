"""Append-only forward paper evidence and a read-only live-monitor calculation contract.

No broker calls, scheduler, execution, or backfilled historical records live here.
Paper observations are explicitly user-supplied and are not broker verification.
"""
from datetime import datetime, timezone
from typing import Literal

import numpy as np
from pydantic import Field, model_validator

from evidence.storage import now
from .models import Strict
from .statistics import metrics


class PaperRegistration(Strict):
    experiment_id: str = Field(pattern=r"^\d{8}T\d{6}Z-[a-f0-9]{8}$")
    initial_nav: float = Field(gt=0, le=1e9)


class PaperEvent(Strict):
    kind: Literal["signal", "observation"]
    observed_at: datetime
    signal_id: str | None = Field(None, pattern=r"^[a-f0-9]{64}$")
    weights: dict[str, float] = Field(default_factory=dict)
    expected_return: float | None = Field(None, gt=-1, le=10)
    cost_bps: float = Field(0, ge=0, le=10000)
    nav: float | None = Field(None, gt=0, le=1e12)
    fills: list[dict] = Field(default_factory=list, max_length=200)
    regime: str | None = Field(None, max_length=100)

    @model_validator(mode="after")
    def contract(self):
        if self.observed_at.tzinfo is None:
            raise ValueError("Forward evidence requires timezone-aware UTC timestamps")
        if self.kind == "observation" and (self.signal_id is None or self.nav is None):
            raise ValueError("Observation requires a previously recorded signal and marked NAV")
        if self.kind == "signal" and (self.signal_id is not None or self.nav is not None or self.fills):
            raise ValueError("Signals cannot contain future realized observations")
        for fill in self.fills:
            if set(fill) != {"symbol", "quantity", "price"}:
                raise ValueError("Fills require symbol, whole-share quantity and positive price")
            if (not isinstance(fill['symbol'], str) or not isinstance(fill['quantity'], int)
                    or isinstance(fill['quantity'], bool) or not isinstance(fill['price'], (int, float))
                    or not np.isfinite(fill['price']) or fill['price'] <= 0):
                raise ValueError("Invalid recorded paper fill")
        return self


def record_event(store, record_id, event: PaperEvent):
    """Caller serializes registration/event writes with the workspace lock."""
    record = store.get(record_id, "survival_paper")
    entries = paper_events(store, record_id)
    received = datetime.now(timezone.utc)
    latest = max([record['created_at']] + [e['observed_at'] for e in entries])
    if event.observed_at <= datetime.fromisoformat(latest) or event.observed_at > received:
        raise ValueError("Paper observations must advance strictly beyond registration/latest observation and cannot be future-dated")
    if set(event.weights) - set(record['universe']):
        raise ValueError("Paper weights must use the frozen universe")
    if any(f['symbol'] not in record['universe'] for f in event.fills):
        raise ValueError("Paper fill is outside the frozen universe")
    if event.kind == "observation":
        signal = next((e for e in entries if e['id'] == event.signal_id and e['kind'] == 'signal'), None)
        if signal is None or event.observed_at <= datetime.fromisoformat(signal['received_at']):
            raise ValueError("Fill/mark must occur after the signal was recorded; backfilled signals are prohibited")
        if any(e.get('signal_id') == event.signal_id for e in entries):
            raise ValueError("A signal already has an observation; submit a new signal/mark pair")
    body = {**event.model_dump(mode="json"), "observed_at": event.observed_at.astimezone(timezone.utc).isoformat(),
            "record_id": record_id, "received_at": received.isoformat(), "source": "user_recorded_paper", "broker_verified": False}
    key = store.put("survival_paper_event", body)
    store.event(record_id, "paper_event", {"id": key})
    return {"id": key, **body}


def paper_events(store, record_id):
    return [{"id": event['body']['id'], **store.get(event['body']['id'], "survival_paper_event")}
            for event in store.events(record_id) if event['action'] == 'paper_event']


def monitor(observations, expected, limits):
    """Pure monitoring; caller must authenticate provenance before labeling data live.

    Includes cost/return drift, exposure breaches, recent decay and regime changes.
    Thresholds come from the frozen mandate/explicit limits, never universal values.
    """
    breaches = []
    for row in observations:
        weights = list(row.get('weights', {}).values())
        checks = {"gross": sum(abs(w) for w in weights), "net": abs(sum(weights)), "asset": max([0.] + [abs(w) for w in weights])}
        for key, value in checks.items():
            if value > limits[key] + 1e-10:
                breaches.append({"at": row['observed_at'], "limit": key, "value": value, "threshold": limits[key]})
    cost = [row['cost_bps'] - expected.get(row['signal_id'], {}).get('cost_bps', 0) for row in observations]
    nav = [limits['initial_nav']] + [row['nav'] for row in observations]
    realized = np.diff(nav) / np.array(nav[:-1]) if observations else np.array([])
    expected_values = [expected.get(row['signal_id'], {}).get('expected_return') for row in observations]
    paired = [(float(r), e) for r, e in zip(realized, expected_values) if e is not None]
    deviations = []
    for row in observations:
        target = expected.get(row['signal_id'], {}).get('weights', {})
        actual = row.get('weights', {})
        deviations.append(sum(abs(actual.get(symbol, 0)-target.get(symbol, 0)) for symbol in set(target) | set(actual)))
    regime_changes = sum(a.get('regime') is not None and b.get('regime') is not None and a['regime'] != b['regime'] for a, b in zip(observations, observations[1:]))
    cost_drift = float(np.mean(cost)) if cost else None
    return_drift = float(np.mean([r-e for r,e in paired])) if paired else None
    recent = float(np.prod(1 + realized[-20:]) - 1) if len(realized) >= 20 else None
    alerts = []
    for name, value, threshold, breached in (
        ('execution_cost_drift', cost_drift, limits.get('max_cost_drift_bps'), lambda a,b: a>b),
        ('performance_decay', return_drift, limits.get('min_return_drift'), lambda a,b: a<b),
        ('recent_performance', recent, limits.get('min_recent_return'), lambda a,b: a<b),
    ):
        if value is not None and threshold is not None and breached(value, threshold):
            alerts.append({'kind': name, 'value': value, 'threshold': threshold})
    performance = metrics(realized, limits.get('annualization', 252)) if len(realized) >= 2 else None
    if performance is not None and 'annualization' not in limits:
        # User-recorded marks may be intraday or irregular. Do not manufacture a
        # daily Sharpe/CAGR by counting arbitrary events as 252 trading sessions.
        performance.update(cagr=None, sharpe=None, volatility=None,
                           annualization_reason='Verified observation cadence/exchange calendar unavailable')
    return {"observations": len(observations), "breaches": breaches, "alerts": alerts,
            "mean_cost_drift_bps": cost_drift,
            "mean_return_drift": return_drift,
            "matched_expectations": len(paired), "regime_changes": regime_changes,
            "mean_absolute_weight_deviation": float(np.mean(deviations)) if deviations else None,
            "recorded_fills": sum(len(row.get('fills', [])) for row in observations),
            "recent_return": recent,
            "performance": performance,
            "returns": realized.tolist(), "as_of": observations[-1]['observed_at'] if observations else None,
            "evaluated_at": now(), "live_order_submission": False}
