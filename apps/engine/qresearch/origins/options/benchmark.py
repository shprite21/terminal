"""Python vs C++ Black-Scholes pricing benchmark."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Tuple

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

try:
    from .black_scholes import black_scholes_price
except ImportError:  # pragma: no cover - supports direct script execution.
    from black_scholes import black_scholes_price


def generate_option_inputs(n_options: int, seed: int = 123) -> Tuple[np.ndarray, ...]:
    """Create deterministic randomized option inputs for benchmark runs."""

    rng = np.random.default_rng(seed)
    spots = rng.lognormal(mean=np.log(100.0), sigma=0.15, size=n_options)
    strikes = rng.uniform(75.0, 125.0, size=n_options)
    maturities = rng.uniform(1.0 / 252.0, 1.0, size=n_options)
    rates = rng.uniform(0.0, 0.05, size=n_options)
    vols = rng.uniform(0.10, 0.55, size=n_options)
    option_types = rng.choice(np.array([1, -1], dtype=np.int8), size=n_options)
    return spots, strikes, maturities, rates, vols, option_types


def benchmark_python(n_options: int, seed: int = 123) -> Dict[str, float]:
    """Benchmark pure Python scalar Black-Scholes pricing."""

    spots, strikes, maturities, rates, vols, option_types = generate_option_inputs(n_options, seed)
    checksum = 0.0
    start = time.perf_counter()
    for spot, strike, maturity, rate, vol, option_type in zip(
        spots, strikes, maturities, rates, vols, option_types
    ):
        checksum += black_scholes_price(
            spot=float(spot),
            strike=float(strike),
            time_to_maturity=float(maturity),
            risk_free_rate=float(rate),
            volatility=float(vol),
            option_type="call" if int(option_type) == 1 else "put",
        )
    elapsed = time.perf_counter() - start
    return {
        "engine": "python",
        "options": float(n_options),
        "elapsed_seconds": elapsed,
        "options_per_second": n_options / elapsed if elapsed > 0.0 else 0.0,
        "checksum": checksum,
    }


def compile_cpp(repo_root: Path, output_dir: Path) -> Tuple[bool, Path, str]:
    """Compile the C++ benchmark executable when a compatible compiler is available."""

    compiler = next((candidate for candidate in ("g++", "clang++", "c++") if shutil.which(candidate)), None)
    executable = output_dir / ("cpp_benchmark.exe" if os.name == "nt" else "cpp_benchmark")
    if compiler is None:
        return False, executable, "No compatible C++ compiler found on PATH"

    cpp_dir = repo_root / "cpp"
    command = [
        str(shutil.which(compiler)),
        "-O3",
        "-std=c++17",
        str(cpp_dir / "benchmark.cpp"),
        str(cpp_dir / "black_scholes.cpp"),
        str(cpp_dir / "greeks.cpp"),
        "-o",
        str(executable),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        return False, executable, completed.stderr.strip() or completed.stdout.strip()
    return True, executable, "compiled"


def benchmark_cpp(repo_root: Path, output_dir: Path, n_options: int, seed: int = 123) -> Dict[str, float]:
    """Compile and run the C++ benchmark, returning a JSON-compatible result."""

    output_dir.mkdir(parents=True, exist_ok=True)
    compiled, executable, message = compile_cpp(repo_root, output_dir)
    if not compiled:
        return {
            "engine": "cpp",
            "available": False,
            "error": message,
            "options": float(n_options),
            "elapsed_seconds": 0.0,
            "options_per_second": 0.0,
            "checksum": 0.0,
        }

    completed = subprocess.run(
        [str(executable), str(n_options), str(seed)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return {
            "engine": "cpp",
            "available": False,
            "error": completed.stderr.strip() or completed.stdout.strip(),
            "options": float(n_options),
            "elapsed_seconds": 0.0,
            "options_per_second": 0.0,
            "checksum": 0.0,
        }

    result = json.loads(completed.stdout)
    result["available"] = True
    return result


def save_benchmark_results(results: Dict[str, Dict[str, float]], output_dir: Path, plots_dir: Path) -> None:
    """Write benchmark JSON and a speed comparison plot."""

    output_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "benchmark_results.json").open("w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2, sort_keys=True)

    engines = list(results.keys())
    speeds = [results[engine].get("options_per_second", 0.0) for engine in engines]
    fig, ax = plt.subplots(figsize=(8, 5), constrained_layout=True)
    bars = ax.bar(engines, speeds, color=["#1f77b4", "#ff7f0e"])
    ax.set_title("Black-Scholes Pricing Throughput", fontweight="bold")
    ax.set_ylabel("Options / Second")
    ax.bar_label(bars, labels=[f"{speed:,.0f}" for speed in speeds], padding=4)
    fig.savefig(plots_dir / "pricing_benchmark.png", dpi=160)
    plt.close(fig)


def run_benchmarks(n_options: int = 200_000, seed: int = 123) -> Dict[str, Dict[str, float]]:
    """Run Python and C++ pricing benchmarks and persist artifacts."""

    repo_root = Path(__file__).resolve().parents[1]
    results_dir = repo_root / "results"
    plots_dir = repo_root / "plots"
    python_result = benchmark_python(n_options=n_options, seed=seed)
    cpp_result = benchmark_cpp(
        repo_root=repo_root,
        output_dir=results_dir,
        n_options=n_options,
        seed=seed,
    )
    results = {"python": python_result, "cpp": cpp_result}
    if cpp_result.get("available") and python_result["elapsed_seconds"] > 0.0:
        results["speedup"] = {
            "cpp_vs_python": cpp_result["options_per_second"] / python_result["options_per_second"]
        }
    save_benchmark_results(results, results_dir, plots_dir)
    return results


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=200_000, help="Number of options to price")
    parser.add_argument("--seed", type=int, default=123, help="Random seed")
    args = parser.parse_args(argv)

    results = run_benchmarks(n_options=args.n, seed=args.seed)
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1:])
