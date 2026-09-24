"""Offline contracts for the custom-portfolio workflow (never depend on Yahoo)."""

import json
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from apps import portfolio_api
from portfolio.custom import (
    MarketDataError,
    PortfolioRequest,
    PriceHistory,
    analyze_portfolio,
    load_yahoo_history,
)


@pytest.fixture
def payload():
    return {
        "holdings": [{"ticker": "AAA", "weight": 50}, {"ticker": "BBB", "weight": 50}],
        "benchmark": "SPY",
        "initial_capital": 1000,
    }


@pytest.fixture
def histories():
    dates = pd.bdate_range("2024-01-02", periods=30)
    return {
        symbol: PriceHistory(pd.Series(np.linspace(100, end, 30), index=dates), "USD")
        for symbol, end in [("AAA", 200), ("BBB", 50), ("SPY", 110)]
    }


def test_buy_hold_drift_and_attribution(payload, histories):
    result = analyze_portfolio(PortfolioRequest(**payload), lambda s, p: histories[s])
    assert result["metrics"]["ending_value"] == pytest.approx(1250)
    assert result["metrics"]["total_return"] == pytest.approx(0.25)
    assert result["metrics"]["benchmark_return"] == pytest.approx(0.1)
    assert result["holdings"][0]["ending_weight"] == pytest.approx(80)
    assert sum(h["return_contribution"] for h in result["holdings"]) == pytest.approx(0.25)
    assert result["equity_curve"][0]["portfolio"] == pytest.approx(1000)
    assert result["equity_curve"][0]["drawdown"] == 0
    assert result["metrics"]["effective_holdings"] == 2
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize(
    "change",
    [
        {"holdings": []},
        {"holdings": [{"ticker": "AAA", "weight": 99}]},
        {"holdings": [{"ticker": "AAA", "weight": 101}, {"ticker": "BBB", "weight": -1}]},
        {"holdings": [{"ticker": "AAA", "weight": 50}, {"ticker": "aaa", "weight": 50}]},
        {"holdings": [{"ticker": "AAA", "weight": float("nan")}]},
        {"holdings": [{"ticker": "=cmd", "weight": 100}]},
        {"holdings": [{"ticker": "AAA", "weight": 0}]},
        {"benchmark": "not a ticker"},
        {"benchmark": None},
        {"period": "max"},
        {"initial_capital": float("inf")},
        {"risk_free_rate": -1},
        {"unexpected": True},
        {"holdings": [{"ticker": f"S{i}", "weight": 100 / 31} for i in range(31)]},
    ],
)
def test_invalid_requests(payload, change):
    with pytest.raises(ValidationError):
        PortfolioRequest(**(payload | change))


def test_normalize_tickers(payload):
    request = PortfolioRequest(
        **(
            payload
            | {"benchmark": " ^nsei ", "holdings": [{"ticker": " reliance.ns ", "weight": 100}]}
        )
    )
    assert request.benchmark == "^NSEI"
    assert request.holdings[0].ticker == "RELIANCE.NS"


def test_same_benchmark_is_loaded_once(payload, histories):
    calls = []

    def loader(symbol, period):
        calls.append(symbol)
        return histories[symbol]

    analyze_portfolio(PortfolioRequest(**(payload | {"benchmark": "AAA"})), loader)
    assert sorted(calls) == ["AAA", "BBB"]


def test_mixed_currencies_rejected(payload, histories):
    histories["BBB"] = PriceHistory(histories["BBB"].close, "INR")
    with pytest.raises(MarketDataError, match="same quote currency"):
        analyze_portfolio(PortfolioRequest(**payload), lambda s, p: histories[s])


@pytest.mark.parametrize("invalid", [0, -1, np.inf])
def test_bad_prices_rejected(payload, histories, invalid):
    histories["AAA"].close.iloc[5] = invalid
    with pytest.raises(MarketDataError, match="Invalid or missing"):
        analyze_portfolio(PortfolioRequest(**payload), lambda s, p: histories[s])


def test_internal_gaps_are_not_silently_filled(payload, histories):
    histories["AAA"].close.iloc[8] = np.nan
    with pytest.raises(MarketDataError, match="Missing daily prices"):
        analyze_portfolio(PortfolioRequest(**payload), lambda s, p: histories[s])


def test_common_window_and_insufficient_history(payload, histories):
    histories["AAA"] = PriceHistory(histories["AAA"].close.iloc[5:], "USD")
    result = analyze_portfolio(PortfolioRequest(**payload), lambda s, p: histories[s])
    assert result["observations"] == 25
    assert "shortened" in result["warnings"][0]
    assert result["equity_curve"][0]["portfolio"] == 1000
    histories["AAA"] = PriceHistory(histories["AAA"].close.iloc[-5:], "USD")
    with pytest.raises(MarketDataError, match="22 common"):
        analyze_portfolio(PortfolioRequest(**payload), lambda s, p: histories[s])


def test_only_equities_and_etfs(payload, histories):
    histories["AAA"] = PriceHistory(histories["AAA"].close, "USD", "CRYPTOCURRENCY")
    with pytest.raises(MarketDataError, match="supported equity"):
        analyze_portfolio(PortfolioRequest(**payload), lambda s, p: histories[s])


def test_constant_prices_are_json_safe(payload, histories):
    for history in histories.values():
        history.close[:] = 100
    result = analyze_portfolio(PortfolioRequest(**payload), lambda s, p: histories[s])
    assert result["metrics"]["total_return"] == 0
    assert result["metrics"]["beta"] is None
    json.dumps(result, allow_nan=False)


def test_higher_risk_free_rate_reduces_sharpe(payload, histories):
    low = analyze_portfolio(PortfolioRequest(**payload), lambda s, p: histories[s])
    high = analyze_portfolio(
        PortfolioRequest(**(payload | {"risk_free_rate": 5})), lambda s, p: histories[s]
    )
    assert high["metrics"]["sharpe"] < low["metrics"]["sharpe"]


def test_yahoo_contract_and_current_day_exclusion(monkeypatch):
    today = pd.Timestamp.now(tz="America/New_York").normalize()
    dates = pd.date_range(end=today, periods=3)
    ticker = Mock()
    ticker.history.return_value = pd.DataFrame({"Close": [100, 101, 102]}, index=dates)
    ticker.get_history_metadata.return_value = {"currency": "USD", "instrumentType": "EQUITY"}
    monkeypatch.setattr("portfolio.custom.yf.Ticker", lambda symbol: ticker)
    result = load_yahoo_history("AAA", "1y")
    assert len(result.close) == 2
    assert result.close.index.tz is None
    assert result.currency == "USD"
    assert ticker.history.call_args.kwargs["auto_adjust"] is True
    assert ticker.history.call_args.kwargs["timeout"] == 15


def test_yahoo_error_is_actionable(monkeypatch):
    ticker = Mock()
    ticker.history.side_effect = RuntimeError("private provider implementation detail")
    monkeypatch.setattr("portfolio.custom.yf.Ticker", lambda symbol: ticker)
    with pytest.raises(MarketDataError, match="could not load AAA") as error:
        load_yahoo_history("AAA", "1y")
    assert "private" not in str(error.value)


def test_api_success_validation_failure_and_cors(monkeypatch, payload, histories):
    monkeypatch.setattr(
        portfolio_api,
        "analyze_portfolio",
        lambda request: analyze_portfolio(request, lambda s, p: histories[s]),
    )
    client = TestClient(portfolio_api.app)
    assert client.get("/openapi.json").json()["info"]["title"] == "Shprite Equity Lab"
    assert client.get("/api/health").json()["mode"] == "research_only"
    response = client.post(
        "/api/portfolio/analyze", json=payload, headers={"Origin": "http://localhost:3000"}
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.json()["metrics"]["ending_value"] == 1250
    assert client.post("/api/portfolio/analyze", json={"holdings": []}).status_code == 422
    assert (
        "access-control-allow-origin"
        not in client.get("/api/health", headers={"Origin": "https://untrusted.example"}).headers
    )

    def fail(request):
        raise MarketDataError("Yahoo unavailable; try later.")

    monkeypatch.setattr(portfolio_api, "analyze_portfolio", fail)
    response = client.post("/api/portfolio/analyze", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"] == "Yahoo unavailable; try later."
