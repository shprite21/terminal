"""Synthetic test fixtures explicitly authorized for the exploratory lab."""
from datetime import date
import numpy as np
import pandas as pd
import pytest
from evidence.storage import Store, digest
from evidence.lab_data import synthetic_history, load_bars, validate_bars, yahoo_history
from evidence.bar_lab import BarConfig, bar_study, compare_periods
from evidence.market_making import MMConfig, make_events, simulate_mm, run_mm
from evidence.export import export_bundle
from evidence.replay_lab import replay


def arithmetic_bars():
    # Artificial prices for hand-calculated ledger tests only.
    close = [100, 100, 102, 104, 108, 112]
    opening = [100] + close[:-1]
    return pd.DataFrame({"timestamp": pd.date_range("2025-01-06", periods=6, tz="Asia/Kolkata").map(lambda t:t.isoformat()),
                         "open": opening, "high": close, "low": opening, "close": close, "volume": 10000})


def test_hand_calculated_next_open_ledger():
    config = BarConfig(lookback=2, holding_bars=100, initial_cash=1000, allocation=1, fee_bps=0, slippage_bps=0, participation=.25)
    result = bar_study(arithmetic_bars(), config, date(2025,1,6), date(2025,1,11), "1d", "Asia/Kolkata")
    # First positive two-bar momentum known Jan 8 close; buy Jan 9 open 102.
    # floor(1000/102)=9 units; terminal sell at 112 => cash 1090.
    assert result["fills"][0]["price"] == 102
    assert result["fills"][0]["quantity"] == 9
    assert result["metrics"]["net_pnl"] == pytest.approx(90)
    assert result["metrics"]["ending_inventory"] == 0


def test_fees_reconcile_cash_and_trade_pnl():
    config = BarConfig(lookback=2, holding_bars=100, initial_cash=1000, allocation=1, fee_bps=10, slippage_bps=5, participation=.25)
    result = bar_study(arithmetic_bars(), config, date(2025,1,6), date(2025,1,11), "1d", "Asia/Kolkata")
    cash = 1000
    for f in result["fills"]:
        cash += (1 if f["side"] == "SELL" else -1)*f["quantity"]*f["price"]-f["fee"]
    assert cash == pytest.approx(result["equity"][-1]["equity"])
    assert sum(t["net_pnl"] for t in result["trades"]) == pytest.approx(cash-1000)
    assert result["metrics"]["net_pnl"] < 90


def test_bar_future_change_does_not_affect_earlier_fills():
    frame = arithmetic_bars()
    cfg = BarConfig(lookback=2)
    original = bar_study(frame, cfg, date(2025,1,6), date(2025,1,11), "1d", "Asia/Kolkata")
    frame.loc[5, ["high", "close"]] = 200
    changed = bar_study(frame, cfg, date(2025,1,6), date(2025,1,11), "1d", "Asia/Kolkata")
    assert original["fills"][:-1] == changed["fills"][:-1]


def test_day_rejects_daily():
    with pytest.raises(ValueError, match="intraday"):
        bar_study(arithmetic_bars(), BarConfig(mode="Day trade"), date(2025,1,6), date(2025,1,11), "1d", "Asia/Kolkata")


def test_seed_provenance_day_flatten_and_replay(tmp_path):
    store = Store(tmp_path)
    key = synthetic_history(store, date(2025,1,6), date(2025,1,17), "5m", 7)
    assert key == synthetic_history(store, date(2025,1,6), date(2025,1,17), "5m", 7)
    dataset, frame = load_bars(store, key)
    assert dataset["source"]["synthetic"] is True
    assert dataset["rows_sha256"] == digest(frame.to_dict("records"))
    config = BarConfig(mode="Day trade", lookback=3, holding_bars=100)
    result = bar_study(frame, config, date(2025,1,6), date(2025,1,17), "5m", "Asia/Kolkata")
    eq = pd.DataFrame(result["equity"])
    assert (eq.groupby(eq.timestamp.str[:10]).tail(1).inventory == 0).all()
    assert all(t["entry"][:10] == t["exit"][:10] for t in result["trades"])
    report_id = compare_periods(store, key, config.model_dump(), date(2025,1,6), date(2025,1,10), date(2025,1,13), date(2025,1,17), True)
    report = store.get(report_id, "lab_report")
    path = tmp_path/"comparison.zip"
    path.write_bytes(export_bundle(store, report, "lab_dataset"))
    assert replay(path)["verified"]


@pytest.mark.parametrize("bad", ["nan", "duplicate", "ohlc", "negative"])
def test_data_quality_rejects(bad):
    frame = arithmetic_bars()
    if bad == "nan": frame.loc[0,"volume"] = np.nan
    if bad == "duplicate": frame.loc[1,"timestamp"] = frame.timestamp.iloc[0]
    if bad == "ohlc": frame.loc[0,"low"] = 200
    if bad == "negative": frame.loc[0,"volume"] = -1
    with pytest.raises(ValueError): validate_bars(frame)


def test_yahoo_transport_failure_does_not_generate_synthetic(tmp_path, monkeypatch):
    import yfinance as yf
    def failed(*args, **kwargs): raise TimeoutError("injected transport failure")
    monkeypatch.setattr(yf.Ticker, "history", failed)
    store = Store(tmp_path)
    with pytest.raises(ValueError, match="no fallback"):
        yahoo_history(store, "RELIANCE.NS", date(2025,1,1), date(2025,2,1))
    assert not store.list("lab_dataset")


def test_yahoo_old_intraday_request_not_shortened(tmp_path):
    with pytest.raises(ValueError, match="will not shorten"):
        yahoo_history(Store(tmp_path), "RELIANCE.NS", date(2020,1,1), date(2020,1,31), "5m")


def test_comparison_requires_nonoverlap_and_acknowledgement(tmp_path):
    store = Store(tmp_path)
    key = synthetic_history(store, date(2025,1,1), date(2025,6,30))
    cfg = BarConfig().model_dump()
    with pytest.raises(ValueError, match="Acknowledge"):
        compare_periods(store,key,cfg,date(2025,1,1),date(2025,3,31),date(2025,4,1),date(2025,6,30))
    with pytest.raises(ValueError, match="non-overlapping"):
        compare_periods(store,key,cfg,date(2025,1,1),date(2025,4,1),date(2025,4,1),date(2025,6,30),True)


def test_mm_no_arbitrage_in_identical_venues():
    cfg = MMConfig(events=200, strategy="Latency arbitrage", venue_lag_ms=0)
    result = simulate_mm(make_events(cfg),cfg)
    assert result["metrics"]["fills"] == 0
    assert result["metrics"]["net_pnl"] == 0


def test_mm_cash_ledger_inventory_bounds_and_latency():
    cfg = MMConfig(events=600, queue_ahead=0, max_inventory=10, feed_latency_ms=120, order_latency_ms=250)
    result = simulate_mm(make_events(cfg),cfg)
    assert result["metrics"]["fills"] > 0
    cash = cfg.initial_cash
    quantity = 0
    for fill in result["fills"]:
        sign = 1 if fill["side"] == "BUY" else -1
        quantity += sign*fill["quantity"]
        cash -= sign*fill["quantity"]*fill["price"]+fill["fee"]
    assert quantity == 0
    assert result["metrics"]["peak_abs_inventory"] <= 10
    assert cash-cfg.initial_cash == pytest.approx(result["metrics"]["net_pnl"])
    assert result["effective_feed_ms"] == 200
    assert result["effective_order_ms"] == 300
    assert all(d["observed_time_ms"] <= d["time_ms"]-200 and d["arrival_ms"] >= d["time_ms"]+300 for d in result["decisions"])


def test_mm_future_mutation_is_causal():
    cfg = MMConfig(events=300, queue_ahead=0)
    events = make_events(cfg)
    first = simulate_mm(events,cfg)
    events.loc[200:, ["fast_mid", "slow_mid"]] *= 1.001
    second = simulate_mm(events,cfg)
    assert first["curve"][:200] == second["curve"][:200]


def test_mm_reproducible_export(tmp_path):
    store = Store(tmp_path)
    cfg = MMConfig(events=200)
    assert make_events(cfg).equals(make_events(cfg))
    key = run_mm(store,cfg)
    report = store.get(key,"mm_report")
    path = tmp_path/"mm.zip"
    path.write_bytes(export_bundle(store,report,"mm_dataset"))
    assert replay(path)["verified"]
