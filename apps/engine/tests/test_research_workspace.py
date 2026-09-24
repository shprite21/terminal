from __future__ import annotations

import json
import threading

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from apps import research_api
from apps.portfolio_api import app
from apps.research_api import ResearchWorkspace
from backtesting import (
    BacktestConfig,
    VectorizedBacktester,
    WalkForwardConfig,
    WalkForwardValidator,
)
from data.research_source import OHLCVHistory, load_research_bundle
from portfolio.custom import MarketDataError
from regime_detection.base import RegimeResult
from research.workspace import (
    CATALOG,
    ResearchRequest,
    pipeline_for,
    research_metrics,
    run_research,
    subset_bundle,
)
from risk import ExposureConstraint, RiskConfig
from strategies.base import StrategySignal


def request(**changes):
    return ResearchRequest(
        **{
            "name": "PM integration test",
            "hypothesis": "Diversify momentum with reversal under hard risk limits.",
            "data_mode": "demo",
            "symbols": ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"],
            "sleeves": [
                {"strategy": "time_series_momentum", "budget": 60, "lookback": 30},
                {"strategy": "mean_reversion", "budget": 40, "lookback": 10},
            ],
            "train_window": 126,
            "test_window": 63,
            **changes,
        }
    )


@pytest.fixture()
def research_bundle(synthetic_bundle):
    synthetic_bundle.benchmark = synthetic_bundle.close().mean(axis=1).to_frame("Close")
    synthetic_bundle.metadata = {
        "source": "Test synthetic observations",
        "data_mode": "demo",
        "currency": "USD",
        "benchmark": "Synthetic benchmark",
        "retrieved_at": "2026-09-05T00:00:00Z",
    }
    return synthetic_bundle


@pytest.mark.parametrize(
    "changes",
    [
        {"symbols": ["AAA", "aaa"]},
        {"symbols": "AAA,BBB"},
        {"commission_bps": float("nan")},
        {"max_gross_exposure": 0.5, "max_net_exposure": 1},
        {"max_net_exposure": 0},
        {"sleeves": [{"strategy": "pead", "budget": 100, "lookback": 20}]},
        {"sleeves": [{"strategy": "mean_reversion", "budget": 90, "lookback": 20}]},
        {"sleeves": [{"strategy": "mean_reversion", "budget": 100, "lookback": 200}]},
        {"snapshot_run_id": "../private"},
        {"hypothesis": "          "},
    ],
)
def test_mandate_rejects_invalid_requests(changes):
    with pytest.raises(ValidationError):
        request(**changes)


def test_constraints_do_not_create_shorts_or_break_gross():
    rng = np.random.default_rng(17)
    weights = pd.DataFrame(rng.normal(0, 2, (200, 12)))
    config = RiskConfig(max_asset_weight=0.10, max_gross_exposure=0.4, max_net_exposure=0.05)
    result = ExposureConstraint(config).apply(weights)
    assert result.abs().sum(axis=1).max() <= 0.4 + 1e-10
    assert result.sum(axis=1).abs().max() <= 0.05 + 1e-10
    assert result.abs().max().max() <= 0.10 + 1e-10
    long_only = ExposureConstraint(config).apply(weights.abs())
    assert long_only.min().min() >= 0


@pytest.mark.parametrize("strategy", list(CATALOG))
def test_exposed_strategies_are_causal_and_constrained(research_bundle, strategy):
    req = request(
        sleeves=[{"strategy": strategy, "lookback": 20, "budget": 100}],
        volatility_target=0.60,
        max_gross_exposure=0.5,
        max_net_exposure=0.3,
        max_asset_weight=0.08,
    )
    pipeline = pipeline_for(req)
    full = pipeline.run(research_bundle)
    prefix = pipeline.run(subset_bundle(research_bundle, research_bundle.close().index[:240]))
    pd.testing.assert_frame_equal(full.weights.iloc[:240], prefix.weights)
    assert np.isfinite(full.weights.to_numpy()).all()
    assert full.weights.min().min() >= 0
    assert full.weights.max().max() <= 0.08 + 1e-10
    assert full.weights.sum(axis=1).max() <= 0.3 + 1e-10


def test_high_volatility_maps_to_defensive(monkeypatch, synthetic_prices):
    from research import pipeline

    monkeypatch.setattr(
        pipeline.VolatilityRegimeClassifier,
        "fit_predict",
        lambda self, values: RegimeResult(pd.Series(2, index=values.index)),
    )
    monkeypatch.setattr(
        pipeline.MarketBreadthRegimeDetector,
        "fit_predict",
        lambda self, values: RegimeResult(pd.Series(1, index=values.index)),
    )
    result = pipeline.ResearchPipeline._detect_regimes(
        synthetic_prices, synthetic_prices.pct_change()
    )
    assert (result == 0).all()


def test_drifting_holdings_charge_rebalance_turnover():
    dates = pd.to_datetime(["2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09", "2024-01-10"])
    prices = pd.DataFrame({"A": [100, 100, 110, 121, 121], "B": [100] * 5}, index=dates)
    targets = pd.DataFrame(0.5, index=dates, columns=prices.columns)
    config = BacktestConfig(
        rebalance_frequency="W-FRI",
        transaction_cost_bps=0,
        slippage_bps=0,
        drift_between_rebalances=True,
    )
    result = VectorizedBacktester(config).run(prices, targets)
    assert result.turnover.tolist() == [0, 0, 1, 0, 0]
    assert result.equity_curve.iloc[-1] / config.initial_capital == pytest.approx(1.105)
    assert result.weights.iloc[3]["A"] == pytest.approx(0.55 / 1.05)
    assert result.weights.iloc[3]["B"] == pytest.approx(0.5 / 1.05)


def test_holiday_and_monthly_rebalance():
    dates = pd.to_datetime(["2024-03-27", "2024-03-28", "2024-04-01", "2024-04-02"])
    prices = pd.DataFrame({"A": [100, 100, 101, 102]}, index=dates)
    targets = prices * 0 + 1
    for frequency in ("W-FRI", "ME"):
        result = VectorizedBacktester(
            BacktestConfig(rebalance_frequency=frequency, drift_between_rebalances=True)
        ).run(prices, targets)
        assert result.turnover.iloc[2] == 1
        assert result.turnover.iloc[:2].sum() == 0


def test_validation_keeps_first_test_return_and_execution_assumptions(synthetic_prices):
    config = BacktestConfig(
        initial_capital=500_000,
        rebalance_frequency=None,
        transaction_cost_bps=17,
        slippage_bps=9,
        annual_borrow_bps=200,
        drift_between_rebalances=True,
    )

    def factory(frame, parameters=None):
        weights = frame * 0 + 0.1
        weights.iloc[:, 0] = -0.1
        return StrategySignal("fixed", weights)

    full = VectorizedBacktester(config).run(synthetic_prices, factory(synthetic_prices).weights)
    validation = WalkForwardValidator(
        WalkForwardConfig(train_window=126, min_train_window=126, test_window=42), config
    ).evaluate(synthetic_prices, factory)
    pd.testing.assert_series_equal(validation.oos_returns, full.returns.iloc[126:])
    assert validation.oos_returns.iloc[0] != 0
    assert validation.windows[0].test_result.costs.iloc[0] > 0
    assert validation.oos_equity_curve.iloc[-1] == pytest.approx(
        config.initial_capital * (1 + full.returns.iloc[126:]).prod()
    )


def test_first_loss_counts_in_drawdown():
    assert research_metrics(pd.Series([-0.1, 0.01]))["max_drawdown"] == pytest.approx(-0.1)


def test_refitting_preserves_previous_model_holdings_and_transition_cost(synthetic_prices):
    config = BacktestConfig(rebalance_frequency=None, transaction_cost_bps=20,
                            slippage_bps=10, drift_between_rebalances=True)

    def factory(frame, parameters=None):
        return StrategySignal("refit", frame * 0 + 0.1 * parameters["direction"])

    validation = WalkForwardValidator(
        WalkForwardConfig(train_window=126, min_train_window=126, test_window=63, mode="expanding"),
        config,
    ).evaluate(synthetic_prices, factory,
               parameter_refitter=lambda frame: {"direction": 1 if len(frame) < 189 else -1})
    targets = synthetic_prices * 0 + 0.1
    targets.iloc[188:] = -0.1
    expected = VectorizedBacktester(config).run(synthetic_prices, targets)
    pd.testing.assert_series_equal(validation.oos_returns, expected.returns.iloc[126:])
    assert validation.windows[1].test_result.turnover.iloc[0] > 1.0


@pytest.mark.parametrize("failure", ["currency", "gap", "invalid", "instrument", "duplicate"])
def test_data_source_rejects_unusable_observations(synthetic_bundle, failure):
    def loader(symbol, period):
        frame = synthetic_bundle.ohlcv[symbol].copy()
        # Make OHLC bars internally valid for this ingestion fixture.
        frame["High"] = frame[["Open", "High", "Close"]].max(axis=1)
        frame["Low"] = frame[["Open", "Low", "Close"]].min(axis=1)
        currency, instrument = "USD", "EQUITY"
        if symbol == "BBB":
            if failure == "currency":
                currency = "INR"
            elif failure == "gap":
                frame = frame.drop(frame.index[150])
            elif failure == "invalid":
                frame.iloc[150, frame.columns.get_loc("Close")] = np.nan
            elif failure == "instrument":
                instrument = "CRYPTOCURRENCY"
            else:
                frame = pd.concat([frame, frame.iloc[[-1]]])
        return OHLCVHistory(frame, currency, instrument)

    with pytest.raises(MarketDataError):
        load_research_bundle(["AAA", "BBB"], "CCC", "2y", loader)


def test_full_research_evidence_reconciles_and_archives(research_bundle, tmp_path):
    req = request()
    result = run_research(req, tmp_path, bundle=research_bundle)
    assert len(result["sleeves"]) == 2
    assert result["validation"]["complete_windows"] == 3
    assert result["paper_candidate_eligible"] is False
    assert result["attribution"]["asset_contribution"] + result["attribution"][
        "cost_contribution"
    ] == pytest.approx(result["metrics"]["total_return"])
    assert result["cost_stress"][2]["total_return"] < result["cost_stress"][0]["total_return"]
    assert result["data"]["data_mode"] == "demo"
    assert result["equity_curve"][0]["portfolio"] == req.initial_capital
    assert result["equity_curve"][-1]["portfolio"] / req.initial_capital - 1 == pytest.approx(
        result["metrics"]["total_return"]
    )
    assert (tmp_path / "source.zip").is_file()
    for name in (
        "prices.csv",
        "benchmark.csv",
        "targets.csv",
        "executed_weights.csv",
        "returns.csv",
        "result.json",
    ):
        assert (tmp_path / name).is_file()
    json.dumps(result, allow_nan=False)


def test_job_api_persistence_decisions_and_errors(tmp_path, monkeypatch, research_bundle):
    # Calculate one real evidence pack, then reuse it to isolate persistence/API tests.
    result = run_research(request(), tmp_path / "fixture", bundle=research_bundle)

    def runner(req, directory, progress, **kwargs):
        progress("Integration stage")
        (directory / "result.json").write_text(json.dumps(result), encoding="utf-8")
        return result

    service = ResearchWorkspace(tmp_path / "experiments", runner=runner)
    monkeypatch.setattr(research_api, "_workspace", service)
    client = TestClient(app)
    try:
        assert len(client.get("/api/research/catalog").json()["strategies"]) == 8
        response = client.post("/api/research/runs", json=request().model_dump())
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        service.executor.shutdown(wait=True)
        evidence = client.get(f"/api/research/runs/{run_id}").json()
        assert evidence["status"] == "completed"
        assert (
            client.post(
                f"/api/research/runs/{run_id}/decision",
                json={"status": "paper_candidate", "rationale": "Synthetic run must stay blocked."},
            ).status_code
            == 409
        )
        assert (
            client.post(
                f"/api/research/runs/{run_id}/decision",
                json={"status": "watchlist", "rationale": "Keep for methodological review."},
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/research/runs/{run_id}/decision",
                json={
                    "status": "rejected",
                    "rationale": "No evidence from real market observations.",
                },
            ).status_code
            == 200
        )
        assert len(client.get(f"/api/research/runs/{run_id}").json()["decisions"]) == 2
        memo = client.get(f"/api/research/runs/{run_id}/artifacts/memo")
        assert memo.status_code == 200 and "Keep for methodological review" in memo.text
        assert client.get(f"/api/research/runs/{run_id}/artifacts/secret").status_code == 404
        assert client.get("/api/research/runs/not-a-run").status_code == 404
        assert client.post("/api/research/runs", json={}).status_code == 422
        restarted = ResearchWorkspace(service.root, runner=runner)
        assert restarted.get(run_id)["decision"]["status"] == "rejected"
        assert restarted.tracker.load(run_id).metrics["sharpe"] == result["metrics"]["sharpe"]
        restarted.executor.shutdown(wait=True)
    finally:
        service.executor.shutdown(wait=True)


def test_queue_limit_and_failure_are_visible(tmp_path):
    release = threading.Event()

    def runner(req, directory, progress):
        release.wait(timeout=5)
        raise MarketDataError("Provider unavailable; no synthetic fallback.")

    service = ResearchWorkspace(tmp_path, runner=runner)
    try:
        jobs = [service.submit(request()) for _ in range(3)]
        with pytest.raises(Exception, match="Three runs"):
            service.submit(request())
        release.set()
        service.executor.shutdown(wait=True)
        for job in jobs:
            failed = service.get(job["run_id"])
            assert failed["status"] == "failed"
            assert "no synthetic fallback" in failed["error"]
    finally:
        release.set()
        service.executor.shutdown(wait=True)
