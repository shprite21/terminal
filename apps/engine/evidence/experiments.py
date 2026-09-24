from __future__ import annotations

from datetime import date
import csv
import importlib.metadata
import io
import json
from pathlib import Path
import platform
import subprocess
from uuid import uuid4
import zipfile
import pandas as pd

from .data import load_dataset
from .diagnostics import signal_study
from .engine import simulate
from .models import Strategy, Calendar, Hypothesis
from .storage import Store, canonical, digest, now
from .actions import validated_actions, split_factor


def fingerprint():
    root = Path(__file__).resolve().parent.parent
    files = sorted(list((root / "evidence").glob("*.py")) + [root / "flagship_api.py", root / "pyproject.toml", root / "requirements.lock.txt"])
    content = {str(p.relative_to(root)): digest(p.read_bytes()) for p in files if p.exists()}
    try:
        git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=5)
        revision = git.stdout.strip() if git.returncode == 0 else "unversioned repository"
    except (OSError, subprocess.TimeoutExpired):
        revision = "git unavailable"
    return {"revision": revision, "source_sha256": digest(content), "files": content, "python": platform.python_version(),
            "dependencies": {name: importlib.metadata.version(name) for name in ("pandas", "numpy", "pydantic", "smartapi-python")}}


def save_hypothesis(store, hypothesis):
    h = Hypothesis.model_validate(hypothesis)
    for existing in store.list("hypothesis"):
        if existing["family"] == h.family and existing["name"] == h.name and existing["version"] == h.version:
            candidate = h.model_dump(mode="json")
            if store.get(existing["id"]) != candidate:
                raise ValueError("Version already exists; increment the hypothesis version")
    key = store.put("hypothesis", h.model_dump(mode="json"))
    if not store.events(key):
        store.transition(key, "draft", "Initial specification saved")
    return key


def freeze_strategy(store, strategy):
    s = Strategy.model_validate(strategy)
    hypothesis = Hypothesis.model_validate(store.get(s.hypothesis_id, "hypothesis"))
    if hypothesis.missing():
        raise ValueError("Hypothesis incomplete: " + ", ".join(hypothesis.missing()))
    dataset, _ = load_dataset(store, s.dataset_id)
    if not set(s.universe).issubset({i["id"] for i in dataset["instruments"]}):
        raise ValueError("Universe not in dataset")
    if not (dataset["quality"]["requested_start"] <= str(s.train_start) and dataset["quality"]["requested_end"] >= str(s.holdout_end)):
        raise ValueError("Dataset does not cover complete declared partitions")
    if not s.acknowledge_limitations:
        raise ValueError("Acknowledge the dataset limitations")
    for existing in store.list("strategy"):
        if existing["name"] == s.name and existing["version"] == s.version and existing["hypothesis_id"] == s.hypothesis_id and store.get(existing["id"]) != s.model_dump(mode="json"):
            raise ValueError("Strategy version already frozen; increment version")
    key = store.put("strategy", s.model_dump(mode="json"))
    store.event(key, "strategy_frozen", {"code": fingerprint()})
    return key


def run_experiment(store, strategy_id, partition="validation", cancelled=lambda: False, progress=lambda a,b: None, planned=True, variant_reason="Predefined baseline", stage=None):
    run_id = store.put("trial", {"nonce": uuid4().hex, "strategy_id": strategy_id, "partition": partition,
                                  "started_at": now(), "planned": planned, "reason": variant_reason, "research_stage": stage or partition})
    store.event(run_id, "running", {})
    try:
        s = Strategy.model_validate(store.get(strategy_id, "strategy"))
        h = Hypothesis.model_validate(store.get(s.hypothesis_id, "hypothesis"))
        store.event(run_id, "family", {"family": h.family})
        if partition not in {"training", "validation", "holdout"}:
            raise ValueError("Unknown research partition")
        if partition == "holdout":
            store.consume_holdout(h.family, strategy_id, run_id)
        dataset, frame = load_dataset(store, s.dataset_id)
        boundaries = {"training": (s.train_start,s.train_end), "validation": (s.validation_start,s.validation_end), "holdout": (s.holdout_start,s.holdout_end)}
        start, end = boundaries[partition]
        calendar = Calendar.model_validate(dataset["calendar"])
        warmup = sorted(d for d in calendar.sessions if d < start)
        if len(warmup) < s.lookback:
            raise ValueError("Insufficient historical warm-up before evaluation; load earlier real data")
        # Physical partition fence: neither simulator nor diagnostics receive future rows.
        frame = frame[frame.date <= str(end)]
        actions = dataset.get("corporate_actions", [])
        result = simulate(frame, s, calendar, start, end, cancelled, progress, actions)
        if cancelled():
            raise InterruptedError("Research cancelled")
        study = signal_study(frame, s, calendar, start, end, actions=actions)
        selected = frame[(frame.date >= str(start)) & (frame.date <= str(end)) & frame.instrument.isin(s.universe)]
        baselines = []
        for instrument, group in selected.groupby("instrument"):
            ordered = group.sort_values("date")
            factor = split_factor(validated_actions(actions, calendar, set(frame.instrument)), instrument, date.fromisoformat(ordered.date.iloc[0]), date.fromisoformat(ordered.date.iloc[-1]))
            baselines.append({"instrument": instrument, "return": float(ordered.close.iloc[-1]*factor/ordered.open.iloc[0]-1)})
        baseline = sum(r["return"] for r in baselines) / len(baselines) if baselines else None
        report = {"trial_id": run_id, "strategy_id": strategy_id, "family": h.family, "partition": partition,
                  "research_stage": stage or partition,
                  "configuration": s.model_dump(mode="json"), "hypothesis": h.model_dump(mode="json"),
                  "dataset_id": s.dataset_id, "dataset_manifest": {k:v for k,v in dataset.items() if k != "rows"},
                  "code": fingerprint(), "boundaries": {"start": str(start), "end": str(end)}, "result": result, "signal_study": study,
                  "benchmark": {"name": "Fixed equal-weight selected-universe buy-and-hold price baseline", "return": baseline,
                                "instruments": baselines, "limitations": "Gross open-to-final-close price baseline; excludes costs and dividends; current-selection bias may apply."},
                  "limitations": dataset["limitations"] + ["Research is evidence conditional on data and assumptions, never proof of profitability.",
                       "Cash account, integer shares, no leverage/shorting; no borrow or live orders. Protective orders activate the session after entry.",
                       "Intrabar stop/target fills occur after opening orders in accounting; ambiguous bars use stop-first. Full-session volume limits assume opening access to that participation; uncertain with daily data.",
                       "Cost rounding is per simulated fill to paise; STT contract-note aggregation and settlement-specific rounding may differ. DP assumed one debit per instrument exit session."]}
        report["limitations"].extend("Cost schedule " + c.name + ": " + ("estimated historical applicability; " if c.estimated_historical else "user-verified applicability; ") + c.applicability_note for c in s.costs)
        report_id = digest({"kind": "report", "body": report})
        export_dir = store.root / "reports" / report_id
        export_dir.mkdir(parents=True, exist_ok=True)
        (export_dir / "report.md").write_text(markdown_report(report), encoding="utf-8")
        (export_dir / "artifacts.zip").write_bytes(export_zip(report))
        store.put("report", report)
        store.event(run_id, "completed", {"report_id": report_id, "result_sha256": digest(result)})
        return report_id
    except InterruptedError:
        store.event(run_id, "cancelled", {"reason": "User cancellation; no completed report"})
        raise
    except ValueError as exc:
        store.event(run_id, "rejected", {"reason": str(exc)[:500]})
        raise
    except Exception:
        store.event(run_id, "failed", {"reason": "Computation failed; inspect local implementation and validation checks"})
        raise ValueError("Computation failed; no completed research result") from None


def markdown_report(report):
    lines = ["# " + report["configuration"]["name"], "", "**Simulated executions using real market observations.**", "",
             "Research stage: " + report.get("research_stage", report["partition"]), "Partition: " + report["partition"], "Dataset: " + report["dataset_id"], "", "## Limitations", ""]
    lines.extend("- " + v for v in report["limitations"])
    lines += ["", "## Provenance and coverage", "", "```json", json.dumps(report["dataset_manifest"], indent=2), "```",
              "", "## Computed performance", "", "```json", json.dumps(report["result"]["metrics"], indent=2), "```",
              "", "## Configuration", "", "```json", json.dumps(report["configuration"], indent=2), "```",
              "", "## Reproducibility", "", "```json", json.dumps(report["code"], indent=2), "```"]
    return "\n".join(lines)


def export_zip(report):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("report.md", markdown_report(report))
        archive.writestr("report.json", canonical(report))
        archive.writestr("strategy.json", canonical(report["configuration"]))
        archive.writestr("hypothesis.json", canonical(report["hypothesis"]))
        for name in ("orders", "fills", "trades", "equity", "holdings", "signals", "cash_movements"):
            archive.writestr(name + ".csv", pd.DataFrame(report["result"][name]).to_csv(index=False))
    return output.getvalue()


def robustness(store, strategy_id, variants, cancelled=lambda: False, progress=lambda a,b: None, planned=True):
    if not 1 <= len(variants) <= 25:
        raise ValueError("Robustness batch must contain 1–25 explicit variants")
    allowed = {"lookback", "threshold", "holding_sessions", "slippage_bps", "spread_bps", "participation", "execution_delay", "position_fraction", "initial_cash", "max_positions", "min_daily_turnover"}
    base = store.get(strategy_id, "strategy")
    outputs = []
    batch = store.put("robustness_batch", {"nonce": uuid4().hex, "strategy_id": strategy_id, "variants": variants, "planned": planned})
    for index, variant in enumerate(variants):
        if cancelled():
            store.event(batch, "cancelled", {"completed": len(outputs)})
            raise InterruptedError("Robustness cancelled")
        if not set(variant).issubset(allowed):
            store.event(batch, "variant_rejected", {"variant_index": index, "reason": "Unsupported field"})
            outputs.append({"variant": variant, "status": "rejected"})
            continue
        config = {**base, **variant, "name": base["name"] + " robustness " + batch[:8] + " " + str(index), "version": 1}
        try:
            key = freeze_strategy(store, config)
            report = run_experiment(store, key, "validation", cancelled, planned=planned, variant_reason="Robustness batch " + batch)
            outputs.append({"variant": variant, "status": "completed", "report_id": report})
        except ValueError as exc:
            store.event(batch, "variant_rejected", {"variant_index": index, "reason": str(exc)[:500]})
            outputs.append({"variant": variant, "status": "rejected"})
        progress(index + 1, len(variants))
    key = store.put("robustness_result", {"batch_id": batch, "strategy_id": strategy_id, "outputs": outputs})
    store.event(batch, "completed", {"result_id": key})
    return key


def walk_forward(store, strategy_id, lookbacks, train_sessions, validation_sessions, test_sessions, cancelled=lambda: False, progress=lambda a,b: None):
    """Expanding folds, select on inner validation, evaluate next interval, exclude final holdout."""
    if not lookbacks or len(lookbacks) > 10 or min(train_sessions, validation_sessions, test_sessions) < 2:
        raise ValueError("Bounded lookbacks and at least two sessions per fold segment required")
    base = Strategy.model_validate(store.get(strategy_id, "strategy"))
    dataset, frame = load_dataset(store, base.dataset_id)
    cal = Calendar.model_validate(dataset["calendar"])
    dates = sorted(d for d in cal.sessions if base.train_start <= d < base.holdout_start)
    batch = store.put("walk_forward", {"nonce": uuid4().hex, "strategy_id": strategy_id, "lookbacks": lookbacks,
                                       "train_sessions": train_sessions, "validation_sessions": validation_sessions, "test_sessions": test_sessions})
    folds = []
    # No fitted transforms: deterministic trailing features. Only bounded lookback selection.
    for split in range(train_sessions, len(dates) - validation_sessions - test_sessions + 1, test_sessions):
        if cancelled():
            raise InterruptedError("Walk-forward cancelled")
        valid_start, valid_end = dates[split], dates[split+validation_sessions-1]
        test_start, test_end = dates[split+validation_sessions], dates[split+validation_sessions+test_sessions-1]
        candidates = []
        for lookback in sorted(set(lookbacks)):
            config = base.model_dump(mode="json")
            config.update(name=base.name + f" wf {batch[:8]} {split} {lookback}", version=1, lookback=lookback,
                          train_start=str(dates[0]), train_end=str(dates[split-1]), validation_start=str(valid_start), validation_end=str(valid_end),
                          holdout_start=str(base.holdout_start), holdout_end=str(base.holdout_end))
            key = freeze_strategy(store, config)
            report_id = run_experiment(store, key, "validation", cancelled, variant_reason="Walk-forward selection " + batch, stage="walk_forward_selection")
            score = store.get(report_id, "report")["result"]["metrics"]["total_return"]
            candidates.append((score, -lookback, key, report_id))
        _, _, selected, selection_report = max(candidates)
        config = store.get(selected, "strategy")
        config.update(name=config["name"] + " frozen evaluation", version=1, train_end=str(valid_end), validation_start=str(test_start), validation_end=str(test_end))
        frozen = freeze_strategy(store, config)
        evaluation = run_experiment(store, frozen, "validation", cancelled, variant_reason="Walk-forward subsequent evaluation " + batch, stage="walk_forward_evaluation")
        store.event(evaluation, "walk_forward_evaluation", {"batch": batch})
        folds.append({"train": [str(dates[0]),str(dates[split-1])], "selection": [str(valid_start),str(valid_end)],
                      "evaluation": [str(test_start),str(test_end)], "selection_report": selection_report, "evaluation_report": evaluation, "frozen_strategy": frozen})
        progress(len(folds), max(1, (len(dates)-train_sessions-validation_sessions)//test_sessions))
    if not folds:
        raise ValueError("Insufficient real coverage for requested walk-forward folds")
    result = store.put("walk_forward_result", {"batch_id": batch, "folds": folds, "limitations": "Each fold starts with fresh cash. No aggregate CAGR across reset portfolios. Selection uses inner validation total return; no learned transformations. Final holdout is never accessed."})
    store.event(batch, "completed", {"result_id": result})
    return result


def candidate_review(store, report_id, notes):
    report = store.get(report_id, "report")
    checks = ["hypothesis_completeness", "data_adequacy", "chronological_correctness", "out_of_sample_evidence", "cost_parameter_sensitivity", "concentration_capacity", "portfolio_fit", "reproducibility"]
    if set(notes) != set(checks) or any(v.get("outcome") not in {"pass", "fail", "unavailable"} or len(v.get("evidence", "")) < 10 for v in notes.values()):
        raise ValueError("Each review criterion needs pass/fail/unavailable and substantive evidence")
    outcome = "rejected" if any(v["outcome"] == "fail" for v in notes.values()) else "inconclusive"
    if all(v["outcome"] == "pass" for v in notes.values()) and report["partition"] == "holdout":
        outcome = "eligible for forward testing"
    review = {"report_id": report_id, "outcome": outcome, "checks": notes, "reviewed_at": now(),
              "frozen_specification": report["configuration"], "monitoring_plan": {"review_schedule": "Weekly operational review; monthly research review",
              "track": ["signal frequency", "turnover", "exposures", "realized versus assumed costs", "missing data", "reconciliation"],
              "pause_conditions": ["Missing or stale required data", "Corporate action without validated accounting", "Constraint or reconciliation failure", "Costs exceed reviewed assumptions"],
              "expected_values": "Specify numeric ranges from the reviewed report before forward testing"}, "limitation": "Researcher attestations; review eligibility is not proof of an edge."}
    return store.put("candidate_review", review)
