from datetime import date, datetime, timezone
import io
import json
import os
from pathlib import Path
import pandas as pd
import streamlit as st

from research.storage import Store, digest, canonical
from research.models import Calendar, Hypothesis, Strategy
from research.provider import AngelOneDataProvider, ProviderError, credentials_ready, fetch_master, search_master, download, validate_mappings
from research.data import load_dataset, freeze_dataset, COLUMNS
from research.cli import freeze_download
from research.workbench import TEMPLATES, template, guidance
from research.experiments import save_hypothesis, freeze_strategy, run_experiment, robustness, walk_forward, candidate_review, export_zip
from research.jobs import Jobs
from research.lab_ui import trading_lab, market_making_lab
from research.charts import detail_line, risk_area

st.set_page_config(page_title="Evidence · Strategy research", page_icon="◈", layout="wide")


@st.cache_resource
def resources(root):
    store = Store(root)
    return store, Jobs(store)


store, jobs = resources(os.environ.get("EVIDENCE_DATA_DIR", "data"))


def guarded(function):
    try:
        return function()
    except ProviderError as exc:
        st.error(str(exc))
    except ValueError as exc:
        from pydantic import ValidationError
        if isinstance(exc, ValidationError):
            st.error("Invalid fields: " + "; ".join(".".join(map(str,e["loc"])) + ": " + e["type"] for e in exc.errors()))
        else:
            st.error(str(exc)[:800])
    except Exception:
        st.error("Operation unavailable. Check local setup and required inputs; no result was substituted.")


def json_editor(label, value, key, height=320):
    return st.text_area(label, json.dumps(value, indent=2), height=height, key=key)


def choose(kind, label, key):
    rows = store.list(kind)
    if not rows:
        st.info("No " + kind.replace("_", " ") + " records yet.")
        return None
    lookup = {r["id"]: r for r in rows}
    return st.selectbox(label, list(lookup), format_func=lambda k: lookup[k].get("name", lookup[k].get("label", kind)) + " · " + k[:12], key=key)


with st.sidebar:
    st.markdown("## ◈ Evidence")
    st.caption("SYSTEMATIC STRATEGY RESEARCH")
    environment = st.radio("Environment", ["Trading lab", "Market making", "Advanced daily research"])
    page = environment
    if environment == "Advanced daily research":
        page = st.radio("Workspace", ["Overview", "Data & connection", "Hypotheses", "Strategy", "Research & validation", "Experiments & reports", "Forward review"], label_visibility="collapsed")
    st.divider()
    st.caption("DAY · SWING · MARKET MAKING")
    st.caption("Real and synthetic sources are labeled. All executions are simulated.")

st.title(page)


@st.fragment(run_every="3s")
def job_panel():
    recent = store.list("job")[:3]
    if not recent:
        return
    with st.expander("Jobs", expanded=True):
        for job in recent:
            events = store.events(job["id"])
            latest = events[-1] if events else {"action": "queued", "body": {}}
            st.write(job["label"] + " · " + latest["action"])
            if latest["action"] == "progress":
                st.progress(min(1.0, latest["body"]["done"]/max(1, latest["body"]["total"])))
            if latest["body"].get("reason"):
                st.warning(latest["body"]["reason"])
            if latest["action"] in {"running", "progress"} and st.button("Cancel", key="cancel_" + job["id"]):
                jobs.cancel(job["id"])
            if latest["body"].get("artifact_id"):
                st.caption("Saved artifact: " + str(latest["body"]["artifact_id"]))


job_panel()

if page == "Trading lab":
    trading_lab(store, guarded)

elif page == "Market making":
    market_making_lab(store, guarded)

elif page == "Overview":
    st.markdown("### From a falsifiable idea to an auditable result")
    st.write("Specify the hypothesis before testing. Freeze the data and strategy, inspect the costs and coverage, then evaluate the evidence across chronological periods.")
    datasets, reports = store.list("dataset"), store.list("report")
    cols = st.columns(3)
    cols[0].metric("Frozen datasets", len(datasets))
    cols[1].metric("Specified hypotheses", len(store.list("hypothesis")))
    cols[2].metric("Completed research reports", len(reports))
    if not datasets:
        st.info("No market data loaded. Research charts and performance statistics are unavailable.")
        st.markdown("For Yahoo Finance and synthetic studies, select **Trading lab** in the sidebar. This advanced daily workflow retains its stricter sourced-calendar contract.")
    angel_reports = [r for r in reports if r["dataset_manifest"]["source"]["provider"] == "Angel One SmartAPI"]
    if not angel_reports:
        st.caption("Angel One is optional and deferred. Its authenticated end-to-end workflow remains unverified.")
    st.caption("Published claims, user assumptions, and computed findings have different evidential status. A backtest is never proof of future performance.")

elif page == "Data & connection":
    tabs = st.tabs(["Connect & download", "Freeze downloaded history", "Supplemental CSV", "Inventory & quality"])
    with tabs[0]:
        st.subheader("Secure local connection")
        st.code(".venv\\Scripts\\python.exe -m research.cli credentials", language="powershell")
        st.caption("Use the hidden terminal prompts to save secrets in the OS credential store. Never paste credentials into a hypothesis, report, or chat.")
        st.caption("Add --show-input to the command to see and verify each value as you type in your local terminal.")
        ready = credentials_ready()
        st.write("Credentials configured" if ready else "Unavailable: configure credentials locally")
        with st.form("connection", clear_on_submit=True):
            totp = st.text_input("Current six-digit TOTP (blank uses explicitly stored seed)", type="password")
            connect = st.form_submit_button("Connect to Angel One", disabled=not ready)
        if connect:
            def connection():
                provider = AngelOneDataProvider(store)
                provider.connect(totp or None)
                st.session_state.provider = provider
                st.success("Authenticated session connected")
            guarded(connection)
        if st.button("Fetch official instrument master"):
            guarded(lambda: st.success("Saved mapping version " + fetch_master(store)))
        masters = store.list("instrument_master")
        if masters:
            version = st.selectbox("Instrument mapping", [m["id"] for m in masters], format_func=lambda x: x[:16])
            query = st.text_input("Search NSE cash equities", placeholder="Trading symbol")
            matches = guarded(lambda: search_master(store, version, query)) if query else []
            selected = st.multiselect("Instruments", matches or [], format_func=lambda i: i.symbol + " · token " + i.token)
            st.caption("This current master does not establish historical universe membership.")
            first, last = st.columns(2)
            start = first.date_input("Requested start", value=date.today())
            end = last.date_input("Requested end", value=date.today())
            st.caption("ONE_DAY · Completed chunks are retained for resume. Repeating an identical request resumes it; extending the range creates a new immutable dataset when frozen.")
            refresh = st.checkbox("Re-fetch history, including empty or incomplete chunks; preserve frozen datasets")
            if st.button("Download / resume selected history", disabled=not selected or "provider" not in st.session_state):
                def start_download():
                    if start > end:
                        raise ValueError("Start must precede end")
                    provider = st.session_state.provider
                    validate_mappings(store, selected)
                    return jobs.submit("Angel One history download", lambda c,p: store.put("download", download(provider, store, selected, start, end, c,p,refresh)))
                guarded(start_download)
    with tabs[1]:
        key = choose("download", "Downloaded history", "freeze_download_select")
        if key:
            record = store.get(key, "download")
            st.json(record["request"])
            st.write("Returned rows:", sum(len(c["rows"]) for c in record["chunks"].values()))
            calendar_upload = st.file_uploader("Verified exchange session calendar JSON", type="json", key="angel_calendar")
            st.caption("Include coverage bounds and exact session open/close timestamps, holidays, and special sessions. See README for the calendar contract.")
            price_note = st.text_area("Evidence that these are raw prices; known adjustment/corporate-action limitations", key="angel_price")
            action_upload = st.file_uploader("Optional sourced split / cash-dividend records (JSON list)", type="json", key="angel_actions")
            if st.button("Validate full coverage & freeze dataset", disabled=not calendar_upload):
                guarded(lambda: st.success("Frozen dataset " + freeze_download(store, key, json.loads(calendar_upload.getvalue()), price_note, json.loads(action_upload.getvalue()) if action_upload else [])))
    with tabs[2]:
        st.write("Import attributable real historical observations. Both the original CSV and its source manifest are retained.")
        st.code(",".join(COLUMNS))
        csv_upload = st.file_uploader("Real historical CSV", type="csv")
        metadata_upload = st.file_uploader("Source, instruments, calendar, bounds and price-note JSON", type="json", key="csv_metadata")
        if csv_upload:
            st.caption("Original CSV SHA-256: " + digest(csv_upload.getvalue()))
        if st.button("Validate and import real data", disabled=not(csv_upload and metadata_upload)):
            def import_csv():
                metadata = json.loads(metadata_upload.getvalue())
                raw = csv_upload.getvalue()
                key = freeze_dataset(store, pd.read_csv(io.BytesIO(raw)), metadata["source"], metadata["instruments"], metadata["calendar"],
                                      date.fromisoformat(metadata["start"]), date.fromisoformat(metadata["end"]), metadata["price_note"], raw, metadata.get("corporate_actions", []))
                st.success("Frozen dataset " + key)
            guarded(import_csv)
    with tabs[3]:
        key = choose("dataset", "Dataset", "inventory_dataset")
        if key:
            def inventory():
                manifest, bars = load_dataset(store, key)
                for limitation in manifest["limitations"]:
                    st.warning(limitation)
                st.json({k:v for k,v in manifest.items() if k != "rows"})
                st.dataframe(bars, width="stretch")
            guarded(inventory)
        for review in store.list("quality_review")[:10]:
            st.error("Dataset freezing blocked · " + review["id"][:12])
            st.json(review["quality"])

elif page == "Hypotheses":
    st.caption("All template ideas are user assumptions, not findings. The guided workbench runs without an LLM.")
    name = st.selectbox("Formulation template", list(TEMPLATES))
    existing = choose("hypothesis", "Review existing version (optional)", "hypothesis_existing")
    editing = st.checkbox("Edit selected hypothesis as a new version", disabled=not existing)
    initial = store.get(existing, "hypothesis") if editing else template(name)
    if editing:
        initial = {**initial, "version": initial["version"] + 1, "created_at": datetime.now(timezone.utc).isoformat()}
    text = json_editor("Hypothesis specification", initial, "hypothesis_" + (existing if editing else name), 500)
    if st.button("Check formulation"):
        guarded(lambda: st.json(guidance(json.loads(text))))
    if st.button("Save hypothesis version"):
        guarded(lambda: st.success("Saved " + save_hypothesis(store, json.loads(text))))
    if existing:
        state = st.selectbox("Research state", ["draft", "specified", "testing", "rejected", "inconclusive", "candidate for forward testing"])
        reason = st.text_input("Reason for transition")
        if st.button("Record state transition"):
            guarded(lambda: store.transition(existing, state, reason))
        st.dataframe(store.events(existing), width="stretch")
    st.info("Event-reaction templates are unavailable until a timestamped-event data adapter is implemented.")

elif page == "Strategy":
    dataset_id = choose("dataset", "Frozen real dataset", "strategy_dataset")
    hypothesis_id = choose("hypothesis", "Hypothesis version", "strategy_hypothesis")
    st.caption("Only deterministic, trailing features are supported. No model fitting, shorting, leverage, or live order placement.")
    if dataset_id and hypothesis_id:
        manifest = store.get(dataset_id, "dataset")
        for limitation in manifest["limitations"]:
            st.warning(limitation)
        initial = {"name": "Daily research specification", "version": 1, "hypothesis_id": hypothesis_id, "dataset_id": dataset_id,
                   "universe": [i["id"] for i in manifest["instruments"]], "feature": "momentum", "lookback": 20,
                   "train_start": "", "train_end": "", "validation_start": "", "validation_end": "", "holdout_start": "", "holdout_end": "",
                   "costs": [], "acknowledge_limitations": False}
        st.info("Set all six chronological boundaries, supply effective-dated cost schedules, and acknowledge limitations. Blank requirements block research.")
        with st.expander("Current published cost reference; historical applicability unverified"):
            st.json(json.loads(Path("examples/costs-current-reference.json").read_text()))
        with st.expander("Full strategy schema and execution controls"):
            st.json(Strategy.model_json_schema())
        config = json_editor("Strategy JSON", initial, "strategy_" + dataset_id + hypothesis_id, 500)
        if st.button("Validate & freeze strategy"):
            guarded(lambda: st.success("Frozen strategy " + freeze_strategy(store, json.loads(config))))

elif page == "Research & validation":
    strategy_id = choose("strategy", "Frozen strategy", "research_strategy")
    if strategy_id:
        tabs = st.tabs(["Signal & portfolio study", "Bounded robustness", "Walk-forward"])
        with tabs[0]:
            partition = st.selectbox("Chronological partition", ["training", "validation", "holdout"])
            acknowledged = True
            if partition == "holdout":
                st.warning("Access consumes the final holdout for this research family, even if evaluation subsequently fails. Local controls cannot establish whether data was viewed elsewhere.")
                acknowledged = st.checkbox("I have frozen the final specification and accept consuming the holdout")
            if st.button("Run registered research", disabled=not acknowledged):
                guarded(lambda: jobs.submit("Research · " + partition, lambda c,p: run_experiment(store, strategy_id, partition, c,p)))
        with tabs[1]:
            st.caption("Every variant is registered. Runs use validation data only. Maximum 25 explicit variants.")
            variants = json_editor("Parameter / execution variants", [], "robustness_variants", 180)
            planned = st.checkbox("These checks were predefined before viewing results", value=False)
            if st.button("Run bounded robustness"):
                guarded(lambda: jobs.submit("Robustness", lambda c,p: robustness(store, strategy_id, json.loads(variants), c,p,planned)))
        with tabs[2]:
            lookbacks = st.text_input("Explicit candidate lookbacks as a JSON list", "[]")
            train = st.number_input("Initial training sessions", min_value=2, value=252)
            valid = st.number_input("Inner validation sessions", min_value=2, value=63)
            test = st.number_input("Subsequent evaluation sessions", min_value=2, value=63)
            st.caption("Expanding training; bounded selection by inner-validation net return. Features are deterministic and unfitted. Each fold resets cash. Final holdout is excluded.")
            if st.button("Run walk-forward evaluation"):
                guarded(lambda: jobs.submit("Walk-forward", lambda c,p: walk_forward(store, strategy_id, json.loads(lookbacks), train,valid,test,c,p)))

elif page == "Experiments & reports":
    trials = store.list("trial")
    if trials:
        records = []
        for trial in trials:
            events = store.events(trial["id"])
            records.append({"trial": trial["id"], "partition": trial["partition"], "strategy": trial["strategy_id"],
                            "status": events[-1]["action"] if events else "unavailable", "planned": trial["planned"], "reason": trial["reason"]})
        st.dataframe(records, width="stretch")
        st.caption("Trial count includes failed/rejected runs. Also inspect robustness batches for variants rejected before execution.")
    else:
        st.info("No experiments. Performance charts remain empty until a real-data computation completes.")
    report_id = choose("report", "Computed report", "report_selected")
    if report_id:
        report = store.get(report_id, "report")
        st.subheader(report["configuration"]["name"] + " · " + report.get("research_stage", report["partition"]))
        st.caption(report["result"]["execution_label"])
        for limitation in report["limitations"]:
            st.warning(limitation)
        st.caption("Dataset " + report["dataset_id"] + " · " + report["boundaries"]["start"] + " through " + report["boundaries"]["end"])
        metrics = report["result"]["metrics"]
        a,b,c,d = st.columns(4)
        a.metric("Net return", f"{metrics['total_return']:.2%}")
        b.metric("Maximum drawdown", f"{metrics['max_drawdown']:.2%}")
        c.metric("Explicit costs · INR", f"{metrics['costs']:,.2f}")
        d.metric("Simulated exit lots", metrics["trade_count"])
        eq = pd.DataFrame(report["result"]["equity"]).set_index("date")
        detail_line(eq, ["equity", "gross_same_positions"], "Date (UTC)", temporal=True, y_title="Portfolio value · INR")
        peaks = eq.equity.cummax().clip(lower=report["configuration"]["initial_cash"])
        risk_area(eq.equity/peaks-1)
        tabs = st.tabs(["Metrics & benchmark", "Signal research", "Orders → fills → holdings", "Provenance & export"])
        with tabs[0]:
            st.json(metrics)
            st.json(report["benchmark"])
        with tabs[1]:
            st.json({k:v for k,v in report["signal_study"].items() if k != "observations"})
            st.dataframe(report["signal_study"]["observations"], width="stretch")
        with tabs[2]:
            for kind in ("signals", "orders", "fills", "trades", "holdings", "cash_movements", "dividend_receivables", "open_positions"):
                st.write(kind.replace("_", " ").title())
                st.dataframe(report["result"][kind], width="stretch")
        with tabs[3]:
            st.json(report["dataset_manifest"])
            st.json(report["code"])
            st.download_button("Download reproducible research artifacts", export_zip(report), "research-" + report_id[:12] + ".zip", "application/zip")
    for kind in ("robustness_result", "walk_forward_result", "robustness_batch"):
        with st.expander(kind.replace("_", " ").title()):
            st.json(store.list(kind))

elif page == "Forward review":
    report_id = choose("report", "Report to review", "forward_report")
    st.caption("Review evidence for every criterion. This does not place orders or prove that an edge exists.")
    if report_id:
        fields = ["hypothesis_completeness", "data_adequacy", "chronological_correctness", "out_of_sample_evidence", "cost_parameter_sensitivity", "concentration_capacity", "portfolio_fit", "reproducibility"]
        review = json_editor("Review criteria and supporting evidence", {f: {"outcome": "unavailable", "evidence": ""} for f in fields}, "review_notes", 450)
        if st.button("Save candidate review"):
            guarded(lambda: st.success("Saved review " + candidate_review(store, report_id, json.loads(review))))
    for review in store.list("candidate_review"):
        st.write(review["outcome"])
        st.download_button("Export frozen specification & monitoring plan", canonical(review), "forward-review.json", key="review_export_" + review["id"])
