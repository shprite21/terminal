"""Causal long-only bar studies; independent cash and warm-up per period."""
from datetime import date
from typing import Literal
import numpy as np
import pandas as pd
from pydantic import Field
from .models import Contract
from .lab_data import validate_bars, load_bars
from .storage import digest
from .lab_provenance import lab_fingerprint


class BarConfig(Contract):
    mode: Literal["Day trade", "Swing trade"] = "Swing trade"
    strategy: Literal["Momentum", "Moving average", "Mean reversion"] = "Momentum"
    lookback: int = Field(default=10, ge=2, le=200)
    threshold: float = Field(default=0, ge=0, le=.5)
    holding_bars: int = Field(default=5, ge=1, le=500)
    initial_cash: float = Field(default=100000, ge=100, le=1e9)
    allocation: float = Field(default=.5, gt=0, le=1)
    fee_bps: float = Field(default=5, ge=0, le=100)
    slippage_bps: float = Field(default=3, ge=0, le=100)
    participation: float = Field(default=.01, gt=0, le=.25)


def bar_study(frame, config, start, end, interval, timezone):
    config = BarConfig.model_validate(config)
    if start > end:
        raise ValueError("Period start must precede end.")
    if config.mode == "Day trade" and interval == "1d":
        raise ValueError("Day trades require intraday bars. Load 1m, 5m or 15m data.")
    frame = validate_bars(frame)
    dates = pd.to_datetime(frame.timestamp, utc=True).dt.tz_convert(timezone).dt.date
    selected = (dates >= start) & (dates <= end)
    bars = frame.loc[selected].reset_index(drop=True)
    days = dates.loc[selected].reset_index(drop=True)
    if len(bars) < config.lookback + 2:
        raise ValueError("Period has too few bars for warm-up and next-bar execution.")
    if config.mode == "Day trade":
        groups = bars.groupby(days.to_numpy(), sort=False)
        momentum = groups.close.transform(lambda s: s.pct_change(config.lookback, fill_method=None))
        average = groups.close.transform(lambda s: s.rolling(config.lookback).mean())
    else:
        momentum = bars.close.pct_change(config.lookback, fill_method=None)
        average = bars.close.rolling(config.lookback).mean()
    score = momentum if config.strategy == "Momentum" else bars.close / average - 1
    if config.strategy == "Mean reversion":
        score = -score
    signal = (score > config.threshold) & score.notna()
    if not score.notna().any():
        raise ValueError("No session contains enough bars for this day-trade lookback.")
    cash, quantity, entry = config.initial_cash, 0, None
    fees = impact = 0.0
    equity, fills, trades = [], [], []

    def fill(side, qty, reference, i, reason, when="open"):
        nonlocal cash, quantity, fees, impact, entry
        sign = 1 if side == "BUY" else -1
        price = reference * (1 + sign * config.slippage_bps / 10000)
        fee = qty * price * config.fee_bps / 10000
        cash -= sign * qty * price + fee
        fees += fee
        impact += qty * abs(price-reference)
        quantity += sign * qty
        fills.append({"timestamp": bars.timestamp.iloc[i], "bar_execution": when, "side": side,
                      "quantity": qty, "price": price, "fee": fee, "reason": reason,
                      "execution_kind": "simulated execution"})
        if side == "BUY":
            entry = {"price": price, "fee_per_unit": fee/qty, "index": i, "timestamp": bars.timestamp.iloc[i]}
        else:
            trades.append({"entry": entry["timestamp"], "exit": bars.timestamp.iloc[i], "quantity": qty,
                           "holding_bars": i-entry["index"],
                           "net_pnl": qty*(price-entry["price"]-entry["fee_per_unit"])-fee})
            if not quantity:
                entry = None

    for i, row in enumerate(bars.itertuples()):
        final = i == len(bars)-1
        session_end = final or days.iloc[i+1] != days.iloc[i]
        same_session = i > 0 and days.iloc[i] == days.iloc[i-1]
        capacity = int(bars.volume.iloc[i-1]*config.participation) if i else 0
        exited = False
        if quantity and (i-entry["index"] >= config.holding_bars or not signal.iloc[i-1]):
            qty = min(quantity, capacity)
            if qty:
                fill("SELL", qty, row.open, i, "horizon_or_signal")
                exited = True
        permitted = config.mode == "Swing trade" or (same_session and not session_end)
        if not quantity and not exited and i > 0 and not final and permitted and signal.iloc[i-1]:
            unit_cost = row.open*(1+config.slippage_bps/10000)*(1+config.fee_bps/10000)
            qty = min(int(cash*config.allocation/unit_cost), capacity)
            if qty:
                fill("BUY", qty, row.open, i, "previous_completed_bar_signal")
        if quantity and (final or (config.mode == "Day trade" and session_end)):
            fill("SELL", quantity, row.close, i, "scheduled_flatten", "close")
        nav = cash + quantity*row.close
        if cash < -1e-6 or nav <= 0:
            raise ValueError("Accounting/solvency check failed.")
        equity.append({"timestamp": row.timestamp, "equity": nav, "cash": cash, "inventory": quantity,
                       "costs": fees, "slippage": impact,
                       "gross_same_positions": nav+fees+impact,
                       "buy_hold_gross": config.initial_cash*(1-config.allocation+config.allocation*row.close/bars.open.iloc[0])})
    values = np.r_[config.initial_cash, [e["equity"] for e in equity]]
    pnl = [t["net_pnl"] for t in trades]
    metrics = {"net_return": float(values[-1]/values[0]-1), "net_pnl": float(values[-1]-values[0]),
               "max_drawdown": float((values/np.maximum.accumulate(values)-1).min()), "fees": fees,
               "slippage": impact, "fills": len(fills), "exit_lots": len(trades),
               "win_rate": sum(p>0 for p in pnl)/len(pnl) if pnl else None,
               "bars": len(bars), "sessions": days.nunique(), "ending_inventory": quantity}
    return {"configuration": config.model_dump(), "requested_period": {"start": str(start), "end": str(end)},
            "actual_period": {"first": bars.timestamp.iloc[0], "last": bars.timestamp.iloc[-1]},
            "metrics": metrics, "equity": equity, "fills": fills, "trades": trades,
            "execution_label": "Simulated executions; exploratory comparison, not held-out validation",
            "assumptions": ["Long-only, no leverage; independent cash and warm-up for each period. Day features reset each session.",
                "Completed bar signal executes at next observed open; capacity uses prior bar volume. Missing bars are not reconstructed.",
                "Flat at last observed close each day in Day mode and at each evaluation end. Assumes scheduled closing execution with full liquidation capacity.",
                "Fees and slippage are user assumptions per side, not verified exchange charges. No tax schedule or financing model.",
                "Hold horizon counts bars (sessions for daily bars). Benchmark is gross adjusted buy-and-hold at the configured allocation."]}


def compare_periods(store, dataset_id, config, a_start, a_end, b_start, b_end, acknowledge=False):
    if not acknowledge:
        raise ValueError("Acknowledge source, actual coverage and execution assumptions.")
    if not (a_start <= a_end < b_start <= b_end):
        raise ValueError("Use two non-overlapping chronological periods: A ends before B starts.")
    dataset, frame = load_bars(store, dataset_id)
    earliest = date.fromisoformat(dataset["request"]["start"])
    latest = date.fromisoformat(dataset["request"]["end"])
    if a_start < earliest or b_end > latest:
        raise ValueError("Periods must stay inside the dataset's requested range.")
    results = {label: bar_study(frame, config, start, end, dataset["request"]["interval"], dataset["timezone"])
               for label, start, end in [("Period A", a_start, a_end), ("Period B", b_start, b_end)]}
    body = {"name": f"{config['mode']} · {config['strategy']} · {dataset['source']['kind']}",
            "dataset_id": dataset_id, "source": dataset["source"], "dataset_sha256": dataset["rows_sha256"],
            "engine_version": "bar-lab-v1", "code": lab_fingerprint(), "results": results,
            "limitations": dataset["limitations"], "configuration_sha256": digest(config)}
    return store.put("lab_report", body)
