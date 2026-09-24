from datetime import date, datetime
import json
from pathlib import Path
import sqlite3
import numpy as np
import pandas as pd
import pytest
from evidence.data import validate_bars, load_dataset, freeze_dataset
from evidence.engine import simulate, features, charges
from evidence.models import Strategy
from evidence.experiments import run_experiment, freeze_strategy, robustness, walk_forward
from evidence.diagnostics import signal_study, purged_training, combine_returns
from evidence.storage import digest


def test_hand_verified_real_prices(real_data, strategy):
    frame, _, _, calendar, _ = real_data
    result = simulate(frame, strategy, calendar, date(2024,1,2),date(2024,1,4))
    # RELIANCE Jan 2 closes 2611.70 > Jan 1 2590.25. Buy Jan 3 open
    # 2610.00: floor(10000/2611.70)=3 shares. Cash 2170.00.
    # Jan 3 close 2583.30 => equity 9919.90. Sell Jan 4 open 2588.00
    # => 2170 + 3*2588 = 9934.00; P&L -66.00; return -0.0066.
    assert [(f["date"],f["side"],f["quantity"],f["price"]) for f in result["fills"]] == [("2024-01-03","BUY",3,2610.0),("2024-01-04","SELL",3,2588.0)]
    assert result["equity"][1]["cash"] == pytest.approx(2170)
    assert result["equity"][1]["equity"] == pytest.approx(9919.9)
    assert result["equity"][-1]["equity"] == pytest.approx(9934)
    assert result["trades"][0]["net_pnl"] == pytest.approx(-66)
    assert result["metrics"]["total_return"] == pytest.approx(-.0066)
    assert result["metrics"]["max_drawdown"] == pytest.approx(-.00801)
    assert result["metrics"]["cagr"] is None
    assert result["metrics"]["sharpe_zero_rf"] is None
    for row in result["equity"]:
        assert row["cash"] + row["market_value"] == pytest.approx(row["equity"])


def test_hand_verified_signal(real_data, strategy):
    frame, _, _, calendar, _ = real_data
    values = features(frame, strategy, calendar)
    score = values.loc[values.date == "2024-01-02", "score"].iloc[0]
    assert score == pytest.approx(21.45 / 2590.25)
    study = signal_study(frame, strategy, calendar, date(2024,1,2),date(2024,1,4), (1,))
    label = next(r for r in study["observations"] if r["date"] == "2024-01-02")
    assert label["forward_return"] == pytest.approx(-28.4 / 2611.7)
    assert all(r["label_end"] <= "2024-01-04" for r in study["observations"])


def test_future_observations_do_not_change_prefix(real_data, strategy):
    frame, _, _, calendar, _ = real_data
    truncated = frame[frame.date <= "2024-01-09"]
    full = simulate(frame, strategy, calendar, date(2024,1,2),date(2024,1,9))
    prefix = simulate(truncated, strategy, calendar, date(2024,1,2),date(2024,1,9))
    assert digest(full) == digest(prefix)
    assert all(f["date"] > o["created_at"][:10] for f in full["fills"] for o in full["orders"] if o["id"] == f["order_id"])


def test_delayed_availability(real_data, strategy):
    frame, _, _, calendar, _ = real_data
    delayed = frame.copy()
    delayed.loc[delayed.date == "2024-01-02", "available_at"] = "2024-01-04T16:00:00+05:30"
    assert "2024-01-02" not in set(features(delayed, strategy, calendar).date)
    result = simulate(delayed, strategy, calendar, date(2024,1,2),date(2024,1,4))
    assert not result["fills"]


def test_missing_session_blocks_not_shortens(real_data, strategy):
    frame, _, instruments, calendar, _ = real_data
    missing = frame[frame.date != "2024-01-03"]
    _, report = validate_bars(missing,instruments,calendar,date(2024,1,1),date(2024,1,12))
    assert report["status"] == "blocked"
    assert all("2024-01-03" in days for days in report["missing_sessions"].values())
    with pytest.raises(ValueError, match="Missing market observations"):
        simulate(missing,strategy,calendar,date(2024,1,2),date(2024,1,4))


def test_duplicate_overlap_from_real_records(real_data):
    frame, _, instruments,calendar,_ = real_data
    overlap = pd.concat([frame,frame.iloc[:4]])
    result, report = validate_bars(overlap,instruments,calendar,date(2024,1,1),date(2024,1,12))
    assert len(result) == 40
    assert report["identical_overlaps_removed"] == 4


def test_incomplete_session_quarantined(real_data):
    frame, _, instruments,calendar,_ = real_data
    with pytest.raises(ValueError, match="Incomplete"):
        validate_bars(frame,instruments,calendar,date(2024,1,1),date(2024,1,12),datetime.fromisoformat("2024-01-12T10:00:00+05:30"))


def test_cash_and_participation(real_data, strategy):
    frame, _, _, calendar, _ = real_data
    config = strategy.model_dump(mode="json")
    config.update(initial_cash=10_000_000, participation=.000001)
    s = Strategy.model_validate(config)
    result = simulate(frame,s,calendar,date(2024,1,2),date(2024,1,9))
    for fill in result["fills"]:
        volume = frame[(frame.instrument==fill["instrument"]) & (frame.date==fill["date"])].volume.iloc[0]
        assert fill["quantity"] <= int(volume*s.participation)
    assert all(r["cash"] >= 0 for r in result["equity"])
    assert any(o["status"] == "partial_remainder_cancelled" for o in result["orders"])


def test_ambiguous_real_bar_uses_stop_first(real_data, strategy):
    frame, _, _, calendar, _ = real_data
    s = Strategy.model_validate({**strategy.model_dump(mode="json"), "holding_sessions": 20, "stop_fraction": .02, "target_fraction": .002})
    result = simulate(frame,s,calendar,date(2024,1,2),date(2024,1,9))
    # Position entered Jan 3 @2610. Jan 5 high 2619.85 penetrates target
    # 2615.22; Jan 4 high2609.85 does not. No synthetic bars constructed.
    exit_fill = next(f for f in result["fills"] if f["side"]=="SELL")
    assert exit_fill["date"] == "2024-01-05"
    assert exit_fill["price"] == pytest.approx(2615.22)
    # Jan 4 actual open2588 is through a 0.5% stop at2596.95.
    gap = Strategy.model_validate({**s.model_dump(mode="json"), "stop_fraction":.005, "target_fraction":None})
    result = simulate(frame,gap,calendar,date(2024,1,2),date(2024,1,5))
    assert result["fills"][1]["price"] == 2588
    assert any(o["reason"]=="stop_gap" for o in result["orders"])
    both=Strategy.model_validate({**strategy.model_dump(mode="json"),"holding_sessions":20,"stop_fraction":.005,"target_fraction":.005})
    result=simulate(frame,both,calendar,date(2024,1,4),date(2024,1,9))
    # Jan5 entry2602.9; Jan8 actual OHLC touches both barriers; opening2610
    # lies inside. Conservative stop=2602.9*.995=2589.885 takes precedence.
    assert result["fills"][1]["price"]==pytest.approx(2589.885)
    assert any(o["reason"]=="stop_first_if_ambiguous" for o in result["orders"])


def test_cost_arithmetic_uses_real_turnover(real_data, strategy):
    config = strategy.model_dump(mode="json")
    schedule = config["costs"][0]
    schedule.update(brokerage_rate=.001, brokerage_min=5, brokerage_cap=20, stt_buy=.001, exchange_rate=.000030699,
                    sebi_rate=.000001, ipft_rate=.000000001, gst_rate=.18, stamp_buy=.00015, dp_per_debit=20)
    s = Strategy.model_validate(config)
    # 3 actual observed RELIANCE Jan3 opening shares * 2610 = 7830.
    fees = charges(s,date(2024,1,3),"BUY",7830)
    assert fees == {"brokerage":7.83,"stt":7.83,"exchange":.24,"sebi":.01,"ipft":0,"stamp":1.17,"dp":0,"gst":1.45}


def test_immutable_source_and_registry(registered):
    store, _, dataset = registered
    manifest, _ = load_dataset(store,dataset)
    with store.db() as con, pytest.raises(sqlite3.IntegrityError):
        con.execute("UPDATE artifacts SET body='{}' WHERE id=?",(dataset,))
    source = store.root / "raw" / (manifest["source"]["raw_sha256"] + ".bin")
    source.write_bytes(b"")  # Corrupt transport artifact, never fabricate observations.
    with pytest.raises(ValueError,match="Source payload"):
        load_dataset(store,dataset)


def test_reproducibility_failed_trials_and_holdout(registered):
    store,strategy_id,_ = registered
    first = store.get(run_experiment(store,strategy_id),"report")
    second = store.get(run_experiment(store,strategy_id),"report")
    assert digest(first["result"]) == digest(second["result"])
    holdout = run_experiment(store,strategy_id,"holdout")
    with pytest.raises(ValueError,match="consumed"):
        run_experiment(store,strategy_id,"holdout")
    assert len(store.list("trial")) == 4
    assert any(e["action"]=="holdout_access" for e in store.events(strategy_id))
    assert store.events(store.list("trial")[0]["id"])[-1]["action"] == "rejected"
    assert store.get(holdout)["partition"] == "holdout"


def test_cancellation_has_no_report(registered):
    store,key,_ = registered
    with pytest.raises(InterruptedError):
        run_experiment(store,key,cancelled=lambda:True)
    assert not store.list("report")
    assert store.events(store.list("trial")[0]["id"])[-1]["action"]=="cancelled"


def test_purge_real_labels(real_data,strategy):
    frame, _, _, calendar,_ = real_data
    study = signal_study(frame,strategy,calendar,date(2024,1,2),date(2024,1,12),(2,))
    retained = purged_training(study["observations"],date(2024,1,8),date(2024,1,12),1,calendar)
    assert all(r["label_end"] < "2024-01-05" for r in retained)


def test_robustness_is_bounded_and_recorded(registered):
    store,key,_ = registered
    with pytest.raises(ValueError):
        robustness(store,key,[{}]*26)
    result = store.get(robustness(store,key,[{"slippage_bps":10},{"forbidden":1}]))
    assert [o["status"] for o in result["outputs"]] == ["completed","rejected"]


def test_walk_forward_never_reads_final_holdout(registered):
    store,key,_=registered
    result=store.get(walk_forward(store,key,[1],2,2,2))
    assert result["folds"]
    assert all(f["evaluation"][1] < "2024-01-10" for f in result["folds"])
    with store.db() as con:
        assert con.execute("SELECT count(*) FROM holdouts").fetchone()[0]==0


def test_parameter_validation(strategy):
    with pytest.raises(ValueError):
        Strategy.model_validate({**strategy.model_dump(mode="json"),"lookback":0})
    with pytest.raises(ValueError):
        Strategy.model_validate({**strategy.model_dump(mode="json"),"validation_start":"2024-01-02"})
