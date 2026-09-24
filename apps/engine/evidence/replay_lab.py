"""Replay an exported lab ZIP locally without network calls."""
import argparse
from datetime import date
import json
from pathlib import Path
import zipfile
import pandas as pd
from .bar_lab import bar_study
from .market_making import simulate_mm
from .storage import canonical, digest
from .lab_provenance import lab_fingerprint


def replay(path):
    with zipfile.ZipFile(path) as archive:
        report = json.loads(archive.read("report.json"))
        dataset = json.loads(archive.read("dataset.json"))
    if digest(dataset["rows"]) != dataset["rows_sha256"]:
        raise ValueError("Export dataset hash mismatch.")
    if report.get("code") != lab_fingerprint():
        raise ValueError("Code or dependency fingerprint differs from this report. Use the original code and environment to replay.")
    frame = pd.DataFrame(dataset["rows"])
    if report["engine_version"] == "mm-v1":
        result = simulate_mm(frame, report["result"]["configuration"])
        expected, actual = report["result"]["metrics"], result["metrics"]
    elif report["engine_version"] == "bar-lab-v1":
        expected, actual = {}, {}
        for label, result in report["results"].items():
            bounds = result["requested_period"]
            rerun = bar_study(frame, result["configuration"], date.fromisoformat(bounds["start"]),
                              date.fromisoformat(bounds["end"]), dataset["request"]["interval"], dataset["timezone"])
            expected[label], actual[label] = result["metrics"], rerun["metrics"]
    else:
        raise ValueError("Unsupported engine version.")
    if canonical(expected) != canonical(actual):
        raise ValueError("Replay metrics differ; verify the code/dependency versions.")
    return {"verified": True, "engine": report["engine_version"], "source": dataset.get("source", {}).get("kind", "SYNTHETIC")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    print(json.dumps(replay(parser.parse_args().archive), indent=2))
