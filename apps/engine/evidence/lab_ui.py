"""Streamlit views for bar studies and the separate synthetic MM environment."""
from datetime import date, timedelta
import io
import json
import zipfile
from pathlib import Path
import pandas as pd
import streamlit as st
from .charts import candles, detail_line, risk_area, latency_bars
from .lab_data import yahoo_history, synthetic_history, load_bars
from .bar_lab import BarConfig, compare_periods
from .market_making import MMConfig, run_mm, MM_LIMITATIONS
from .storage import canonical


def export_bundle(store, report, dataset_kind):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("report.json", canonical(report))
        dataset = store.get(report["dataset_id"], dataset_kind)
        archive.writestr("dataset.json", canonical(dataset))
        archive.writestr("observations.csv", pd.DataFrame(dataset["rows"]).to_csv(index=False))
        # Include the matching local source only; never label changed code as the run's code.
        for name, expected in report.get("code", {}).get("source_hashes", {}).items():
            from .storage import digest
            path = Path(__file__).parent/name
            if path.exists() and digest(path.read_bytes()) == expected:
                archive.writestr("research/"+name, path.read_bytes())
        archive.writestr("environment.json", canonical(report.get("code", {})))
        archive.writestr("README.txt", "Source labels and assumptions in report.json and dataset.json apply to every exported result.\n"
                          "Use python -m research.replay_lab PATH_TO_ZIP to verify replay metrics with the matching engine version.\n")
    return buffer.getvalue()


def select_saved(store, kind, label, key):
    records = store.list(kind)
    if not records:
        return None
    lookup = {r["id"]: r for r in records}
    return st.selectbox(label, list(lookup), format_func=lambda k: lookup[k]["name"]+" · "+k[:8], key=key)


def trading_lab(store, guarded):
    st.caption("YAHOO FINANCE / SYNTHETIC SCENARIOS · DAY & SWING · TWO-PERIOD COMPARISON")
    st.write("Load a market, choose a trading horizon, then compare the same strategy across two independent periods.")
    data_tab, strategy_tab, reports_tab = st.tabs(["1 · Market data", "2 · Strategy & periods", "3 · Visual results"])
    with data_tab:
        source = st.radio("Data source", ["Yahoo Finance (real)", "Synthetic scenario"], horizontal=True)
        horizon = st.radio("Data frequency", ["Swing / daily", "Day / intraday"], horizontal=True)
        interval = "1d" if horizon == "Swing / daily" else st.selectbox("Bar interval", ["5m", "15m", "1m"])
        end_default = date.today()-timedelta(days=1)
        days_default = 180 if interval == "1d" else (5 if interval == "1m" else 28)
        with st.form("lab_load"):
            left, right = st.columns(2)
            start = left.date_input("Download / scenario start", end_default-timedelta(days=days_default), key="load_start_"+interval)
            end = right.date_input("Download / scenario end (inclusive)", end_default, key="load_end_"+interval)
            if source == "Yahoo Finance (real)":
                symbol = st.text_input("Yahoo ticker", "RELIANCE.NS", help="One instrument per study; .NS denotes NSE on Yahoo.")
                st.caption("No Angel credentials needed. Adjusted OHLC, personal research. 1m requests limited to 7 recent days; other intraday intervals to 60. Errors never trigger synthetic fallback.")
            else:
                seed = st.number_input("Random seed", 0, 2**32-1, 42)
                vol = st.slider("Assumed daily volatility (%)", 0.0, 10.0, 2.0, .1)/100
                drift = st.slider("Assumed daily drift (%)", -1.0, 1.0, .02, .01)/100
                st.warning("SYNTHETIC: artificial market history. Results test mechanics and assumptions, not a real trading edge.")
            submit = st.form_submit_button("Download Yahoo history" if source == "Yahoo Finance (real)" else "Generate synthetic history", type="primary")
        if submit:
            def load():
                with st.spinner("Preparing and validating data…"):
                    key = yahoo_history(store, symbol, start, end, interval) if source == "Yahoo Finance (real)" else synthetic_history(store, start, end, interval, seed, vol, drift)
                st.session_state["lab_data_select"] = key
                st.success("Dataset saved. Choose Strategy & periods to run a study.")
            guarded(load)
        dataset_id = select_saved(store, "lab_dataset", "Loaded dataset", "lab_data_select")
        if not dataset_id:
            st.info("No lab data loaded. Generate a scenario or download Yahoo history to begin.")
        else:
            dataset, bars = load_bars(store, dataset_id)
            st.warning(dataset["source"]["kind"]) if dataset["source"]["synthetic"] else st.success(dataset["source"]["kind"])
            a, b, c = st.columns(3)
            a.metric("Observations", dataset["actual"]["bars"])
            b.metric("Observed sessions", dataset["actual"]["sessions"])
            c.metric("Quote currency / units", dataset["currency"])
            st.caption(f"Actual coverage: {dataset['actual']['first']} → {dataset['actual']['last']}")
            candles(bars, dataset["currency"])
            st.info("Data is saved. Continue to **2 · Strategy & periods** to run a comparison. Export is optional.")
            with st.expander("Source, coverage & limitations", expanded=False):
                for note in dataset["limitations"]:
                    st.write("• " + note)
            with st.expander("Technical metadata", expanded=False):
                st.json({k:v for k,v in dataset.items() if k not in {"rows", "source"}})
                st.json({k:v for k,v in dataset["source"].items() if k != "returned_payload_csv"})
            st.download_button("Export labeled dataset JSON", canonical(dataset), "dataset-"+dataset_id[:8]+".json", "application/json")
    with strategy_tab:
        if not dataset_id:
            st.info("Load a dataset in Market data first.")
        else:
            st.write("Selected market: **" + dataset["name"] + "**")
            modes = ["Swing trade"] if dataset["request"]["interval"] == "1d" else ["Day trade", "Swing trade"]
            mode = st.radio("Trading horizon", modes, horizontal=True)
            if len(modes) == 1:
                st.caption("Load intraday bars to enable Day trade. Swing positions can span sessions; day positions close each session.")
            with st.form("bar_config_"+dataset_id+mode):
                a, b, c = st.columns(3)
                strategy = a.selectbox("Strategy", ["Momentum", "Moving average", "Mean reversion"])
                lookback = b.number_input("Lookback (bars)", 2, 200, 10)
                holding = c.number_input("Maximum holding (bars)", 1, 500, 5)
                threshold = a.number_input("Signal threshold (%)", 0.0, 50.0, 0.0, .1)/100
                initial = b.number_input("Starting capital (quote units)", 100.0, 1e9, 100000.0)
                allocation = c.slider("Allocation (%)", 1, 100, 50)/100
                fee = a.number_input("Fee per side (bps)", 0.0, 100.0, 5.0)
                slip = b.number_input("Slippage per side (bps)", 0.0, 100.0, 3.0)
                participation = c.number_input("Prior-bar volume participation (%)", .01, 25.0, 1.0)/100
                dates = sorted(set(pd.to_datetime(bars.timestamp, utc=True).dt.tz_convert(dataset["timezone"]).dt.date))
                split = max(1, len(dates)//2)
                left, right = st.columns(2)
                left.markdown("**Period A**")
                a_start = left.date_input("A start", dates[0])
                a_end = left.date_input("A end", dates[split-1])
                right.markdown("**Period B**")
                b_start = right.date_input("B start", dates[min(split, len(dates)-1)])
                b_end = right.date_input("B end", dates[-1])
                st.caption("A must end before B starts. Both periods reset cash and warm-up. Day features also reset each session. These are exploratory comparisons, not an untouched holdout.")
                acknowledged = st.checkbox("I reviewed the source, actual coverage, adjusted-price / synthetic limitations and assumed costs.")
                run = st.form_submit_button("Compare both periods", type="primary")
            if run:
                def compute():
                    config = BarConfig(mode=mode, strategy=strategy, lookback=lookback, holding_bars=holding, threshold=threshold,
                                       initial_cash=initial, allocation=allocation, fee_bps=fee, slippage_bps=slip, participation=participation)
                    key = compare_periods(store, dataset_id, config.model_dump(), a_start, a_end, b_start, b_end, acknowledged)
                    st.session_state["lab_report_select"] = key
                    st.success("Comparison saved. Open Visual results.")
                guarded(compute)
    with reports_tab:
        key = select_saved(store, "lab_report", "Saved comparison (frozen settings)", "lab_report_select")
        if not key:
            st.info("No computed comparisons yet.")
        else:
            report = store.get(key, "lab_report")
            st.warning(report["source"]["kind"]) if report["source"]["synthetic"] else st.success(report["source"]["kind"])
            st.caption("Saved report dataset: " + report["dataset_id"][:12] + ". Changing controls does not change this report; run a new comparison.")
            table = pd.DataFrame({k:v["metrics"] for k,v in report["results"].items()}).T
            table = table[["net_return", "max_drawdown", "net_pnl", "fees", "fills", "sessions"]].rename(columns={
                "net_return":"Net return", "max_drawdown":"Max drawdown", "net_pnl":"Net P&L", "fees":"Fees", "fills":"Fills", "sessions":"Sessions"})
            st.dataframe(table.style.format({"Net return":"{:.2%}", "Max drawdown":"{:.2%}", "Net P&L":"{:,.2f}",
                                            "Fees":"{:,.2f}", "Fills":"{:.0f}", "Sessions":"{:.0f}"}), width="stretch")
            normalized = pd.DataFrame({k:pd.Series([r["equity"]/v["configuration"]["initial_cash"]*100 for r in v["equity"]]) for k,v in report["results"].items()})
            normalized.index.name = "Elapsed bar"
            detail_line(normalized, list(normalized.columns), "Elapsed bar", y_title="Equity · rebased to 100")
            st.caption("Equity rebased to 100, aligned by elapsed bar; calendar durations may differ. No annualized Sharpe inferred from short samples.")
            for label, result in report["results"].items():
                with st.expander(label + " · actual dates, equity, drawdown & trades", expanded=True):
                    period = result["actual_period"]
                    st.caption(f"Actual coverage: {period['first']} → {period['last']}")
                    eq = pd.DataFrame(result["equity"]).set_index("timestamp")
                    detail_line(eq, ["equity", "gross_same_positions", "buy_hold_gross"], "Time (UTC)", 240, temporal=True, y_title="Portfolio value · quote units")
                    peaks = eq.equity.cummax().clip(lower=result["configuration"]["initial_cash"])
                    risk_area(eq.equity/peaks-1)
                    st.dataframe(result["trades"], width="stretch")
                    st.dataframe(result["fills"], width="stretch")
                    with st.expander(label + " · settings & execution assumptions", expanded=False):
                        st.json({"configuration": result["configuration"], "assumptions": result["assumptions"]})
            st.download_button("Export comparison + source data", export_bundle(store, report, "lab_dataset"), "comparison-"+key[:8]+".zip", "application/zip")


def market_making_lab(store, guarded):
    st.caption("SYNTHETIC TWO-VENUE MARKET · EVENT REPLAY · LATENCY SENSITIVITY")
    st.warning("Synthetic environment only. Yahoo OHLCV does not contain the order-book and timestamp data needed to validate real latency arbitrage.")
    with st.expander("Market and execution assumptions", expanded=False):
        for note in MM_LIMITATIONS:
            st.write("• "+note)
    with st.form("mm_config"):
        strategy = st.selectbox("Market-making environment strategy", ["Market making + latency arbitrage", "Market making", "Latency arbitrage"])
        a,b,c = st.columns(3)
        seed = a.number_input("Scenario seed", 0, 2**32-1, 42)
        events = b.number_input("Events", 100, 20000, 3000, 100)
        step = c.number_input("Event step (ms)", 10, 1000, 100, 10)
        vol = a.number_input("Mid volatility (bps / √second)", 0.0, 100.0, 8.0)
        venue = b.number_input("Slow venue lag (ms)", 0, 5000, 300, 10)
        spread = c.number_input("Venue spread (bps)", .1, 100.0, 4.0)
        feed = a.number_input("Our feed latency (ms)", 0, 5000, 100, 10)
        outbound = b.number_input("Our outbound latency (ms)", 0, 5000, 100, 10)
        refresh = c.number_input("Quote / decision refresh (ms)", 10, 10000, 500, 10)
        quote = a.number_input("Quote half spread (bps)", .1, 100.0, 4.0)
        skew = b.number_input("Inventory skew at limit (bps)", 0.0, 100.0, 5.0)
        edge = c.number_input("Minimum arb edge after fees (bps)", 0.0, 100.0, 1.0)
        size = a.number_input("Order size (units)", 1, 100, 5)
        limit = b.number_input("Inventory limit (units)", 1, 1000, 50)
        queue = c.number_input("Assumed queue ahead (units)", 0, 10000, 10)
        maker_fee = a.number_input("Maker fee (bps / side)", 0.0, 100.0, .5)
        taker_fee = b.number_input("Taker fee (bps / side)", 0.0, 100.0, 1.0)
        capital = c.number_input("Scenario capital", 1000.0, 1e9, 100000.0)
        acknowledged = st.checkbox("I understand these are synthetic scenario results and the paired arbitrage fills assume atomic hedging.")
        run = st.form_submit_button("Run market-making scenario", type="primary")
    if run:
        def compute():
            if not acknowledged:
                raise ValueError("Acknowledge the synthetic market and fill assumptions first.")
            config = MMConfig(strategy=strategy, seed=seed, events=events, step_ms=step, volatility_bps=vol,
                              venue_lag_ms=venue, market_spread_bps=spread, feed_latency_ms=feed,
                              order_latency_ms=outbound, refresh_ms=refresh, quote_half_spread_bps=quote,
                              skew_bps=skew, min_edge_bps=edge, order_size=size, max_inventory=limit,
                              queue_ahead=queue, maker_fee_bps=maker_fee, taker_fee_bps=taker_fee, initial_cash=capital)
            with st.spinner("Replaying scenario and latency variants…"):
                st.session_state["mm_report_select"] = run_mm(store, config)
            st.success("Synthetic scenario and sensitivity runs saved.")
        guarded(compute)
    key = select_saved(store, "mm_report", "Saved synthetic run (frozen settings)", "mm_report_select")
    if not key:
        st.info("No scenario has run yet. Results appear only after an actual computation.")
        return
    report = store.get(key, "mm_report")
    result = report["result"]
    st.subheader(report["name"])
    st.caption("Saved settings apply below; changing the form requires a new run. P&L is in scenario units.")
    m = result["metrics"]
    a,b,c,d = st.columns(4)
    a.metric("Synthetic net P&L", f"{m['net_pnl']:.2f}")
    b.metric("Fees", f"{m['fees']:.2f}")
    c.metric("Maximum drawdown", f"{m['max_drawdown']:.3%}")
    d.metric("Simulated fills", m["fills"])
    curve = pd.DataFrame(result["curve"]).set_index("time_ms")
    detail_line(curve, ["pnl", "arb_pnl", "fees"], "Elapsed ms", y_title="P&L / fees · scenario units")
    detail_line(curve, ["fast_mid", "slow_mid", "bid_quote", "ask_quote"], "Elapsed ms", y_title="Price · scenario units")
    risk_area(curve.inventory, "Elapsed ms", temporal=False, percent=False, height=160)
    st.subheader("Outbound latency sensitivity · same synthetic events")
    sensitivity = pd.DataFrame(report["latency_sensitivity"])
    latency_bars(sensitivity)
    st.dataframe(sensitivity, width="stretch")
    with st.expander("Simulated executions, observed decisions & reproducibility"):
        st.json({"configuration": result["configuration"], "metrics": m,
                 "effective_feed_ms": result["effective_feed_ms"], "effective_order_ms": result["effective_order_ms"]})
        st.dataframe(result["fills"], width="stretch")
        st.dataframe(result["decisions"], width="stretch")
    st.download_button("Export synthetic scenario + results", export_bundle(store, report, "mm_dataset"), "SYNTHETIC-mm-"+key[:8]+".zip", "application/zip")
