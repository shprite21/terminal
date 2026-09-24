from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from portfolio import (
    AllocationConfig,
    ConstrainedOptimizer,
    InverseVolatilityAllocator,
    RegimeConditionedAllocator,
    RollingSharpeAllocator,
)
from regime_detection import MarketBreadthRegimeDetector, RegimeEnsemble, VolatilityRegimeClassifier


def test_regime_detectors_and_ensemble_align(synthetic_prices):
    returns = synthetic_prices.pct_change().fillna(0.0)
    volatility = VolatilityRegimeClassifier(lookback=10).fit_predict(returns.mean(axis=1).to_frame("returns"))
    breadth = MarketBreadthRegimeDetector(moving_average_window=30).fit_predict(synthetic_prices)
    combined = RegimeEnsemble().combine({"volatility": volatility, "breadth": breadth})

    assert combined.labels.index.equals(synthetic_prices.index)
    assert set(combined.labels.dropna().unique()).issubset({0, 1, 2})
    assert combined.probabilities is not None


def test_allocators_return_sane_weights(synthetic_prices):
    returns = synthetic_prices.pct_change().fillna(0.0)
    inverse_vol = InverseVolatilityAllocator(
        AllocationConfig(lookback=20, long_only=True, min_weight=0.0, max_weight=0.5)
    ).allocate(returns)
    rolling_sharpe = RollingSharpeAllocator(
        AllocationConfig(lookback=20, long_only=True, min_weight=0.0, max_weight=0.7)
    ).allocate(returns)
    regimes = pd.Series(1, index=synthetic_prices.index)
    regime_weights = RegimeConditionedAllocator(
        AllocationConfig(gross_leverage=1.0, min_weight=0.0, max_weight=0.5)
    ).allocate(inverse_vol.weights, regimes)

    for result in [inverse_vol, rolling_sharpe, regime_weights]:
        assert result.weights.index.equals(synthetic_prices.index)
        assert np.isfinite(result.weights.to_numpy()).all()
        assert (result.weights.abs().sum(axis=1) <= 1.0 + 1e-8).all()


def test_constrained_optimizer_respects_long_only_budget(synthetic_prices):
    returns = synthetic_prices.pct_change().dropna()
    optimizer = ConstrainedOptimizer(
        AllocationConfig(long_only=True, min_weight=0.0, max_weight=0.5, gross_leverage=1.0)
    )
    weights = optimizer.allocate(returns.mean(), returns.cov())

    assert np.isfinite(weights.to_numpy()).all()
    assert abs(weights.sum() - 1.0) < 1e-4
    assert (weights >= -1e-8).all()
    assert (weights <= 0.5 + 1e-8).all()


def test_constrained_optimizer_can_enforce_sector_neutrality():
    assets = ["BANK_A", "BANK_B", "TECH_A", "TECH_B"]
    expected_returns = pd.Series([0.12, 0.03, 0.10, 0.02], index=assets)
    covariance = pd.DataFrame(np.eye(4) * 0.04, index=assets, columns=assets)
    sectors = {
        "BANK_A": "financials",
        "BANK_B": "financials",
        "TECH_A": "technology",
        "TECH_B": "technology",
    }
    optimizer = ConstrainedOptimizer(
        AllocationConfig(
            gross_leverage=1.0,
            long_only=False,
            min_weight=-0.5,
            max_weight=0.5,
            risk_aversion=0.5,
            sector_neutral=True,
            sector_neutral_tolerance=1e-6,
        )
    )

    weights = optimizer.allocate(expected_returns, covariance, sectors)

    assert np.isfinite(weights.to_numpy()).all()
    assert weights.abs().sum() <= 1.0 + 1e-6
    for sector in set(sectors.values()):
        members = [asset for asset, label in sectors.items() if label == sector]
        assert abs(weights.loc[members].sum()) <= 2e-6


def test_sector_neutral_optimizer_requires_complete_sector_labels():
    expected_returns = pd.Series({"A": 0.1, "B": 0.05})
    covariance = pd.DataFrame(
        np.eye(2), index=expected_returns.index, columns=expected_returns.index
    )
    optimizer = ConstrainedOptimizer(
        AllocationConfig(sector_neutral=True, long_only=False)
    )

    with pytest.raises(ValueError, match="missing sector labels for assets: B"):
        optimizer.allocate(expected_returns, covariance, {"A": "technology"})


def test_sector_neutrality_rejects_long_only_configuration():
    with pytest.raises(ValueError, match="require long_only=False"):
        AllocationConfig(sector_neutral=True, long_only=True)

