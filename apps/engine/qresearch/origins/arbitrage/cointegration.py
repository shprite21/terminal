"""Cointegration tests for pair and basket discovery."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tsa.stattools import adfuller, coint
from statsmodels.tsa.vector_ar.vecm import coint_johansen


@dataclass(frozen=True)
class EngleGrangerResult:
    """Result from an Engle-Granger cointegration test."""

    assets: tuple[str, ...]
    target: str
    statistic: float
    p_value: float
    critical_values: dict[str, float]
    hedge_ratios: dict[str, float]
    is_cointegrated: bool
    residual_adf_statistic: float | None = None
    residual_adf_p_value: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the result to a dictionary."""

        return asdict(self)


@dataclass(frozen=True)
class JohansenResult:
    """Summary of a Johansen cointegration test."""

    assets: tuple[str, ...]
    trace_statistics: dict[str, float]
    trace_critical_values_95: dict[str, float]
    max_eigen_statistics: dict[str, float]
    max_eigen_critical_values_95: dict[str, float]
    inferred_rank_95: int
    eigenvectors: dict[str, dict[str, float]]

    def to_dict(self) -> dict[str, Any]:
        """Serialize the result to a dictionary."""

        return asdict(self)


class CointegrationTester:
    """Run Engle-Granger and Johansen cointegration diagnostics."""

    def __init__(
        self,
        significance_level: float = 0.05,
        use_log_prices: bool = True,
        min_obs: int = 252,
    ) -> None:
        self.significance_level = significance_level
        self.use_log_prices = use_log_prices
        self.min_obs = min_obs

    def _prepare(self, prices: pd.DataFrame) -> pd.DataFrame:
        """Validate and transform price data before statistical tests."""

        data = prices.copy().dropna(how="any")
        if len(data) < self.min_obs:
            raise ValueError(f"Cointegration tests require at least {self.min_obs} observations.")
        if self.use_log_prices:
            if (data <= 0).any().any():
                raise ValueError("Log-price cointegration requires strictly positive prices.")
            data = np.log(data)
        return data

    def test_pair(self, prices: pd.DataFrame, asset_a: str, asset_b: str) -> EngleGrangerResult:
        """Run the Engle-Granger test for a pair of assets."""

        data = self._prepare(prices[[asset_a, asset_b]])
        statistic, p_value, critical_values = coint(data[asset_a], data[asset_b])
        regression = sm.OLS(data[asset_a], sm.add_constant(data[asset_b])).fit()
        beta = float(regression.params[asset_b])
        hedge_ratios = {asset_a: 1.0, asset_b: -beta}
        critical_map = {"1%": float(critical_values[0]), "5%": float(critical_values[1]), "10%": float(critical_values[2])}

        return EngleGrangerResult(
            assets=(asset_a, asset_b),
            target=asset_a,
            statistic=float(statistic),
            p_value=float(p_value),
            critical_values=critical_map,
            hedge_ratios=hedge_ratios,
            is_cointegrated=bool(p_value < self.significance_level),
        )

    def scan_pairs(self, prices: pd.DataFrame) -> pd.DataFrame:
        """Run Engle-Granger tests for all unique pairs in the price matrix."""

        records: list[dict[str, Any]] = []
        for asset_a, asset_b in combinations(prices.columns, 2):
            result = self.test_pair(prices, asset_a, asset_b)
            record = result.to_dict()
            record["asset_a"] = asset_a
            record["asset_b"] = asset_b
            records.append(record)
        output = pd.DataFrame(records)
        if not output.empty:
            output = output.sort_values(["p_value", "statistic"], ascending=[True, True])
        return output

    def test_basket(self, prices: pd.DataFrame, target: str | None = None) -> EngleGrangerResult:
        """Run a multivariate Engle-Granger residual stationarity test for a basket."""

        data = self._prepare(prices)
        target_asset = target or str(data.columns[0])
        explanatory_assets = [column for column in data.columns if column != target_asset]
        if not explanatory_assets:
            raise ValueError("At least one explanatory asset is required for basket testing.")

        y = data[target_asset]
        x = sm.add_constant(data[explanatory_assets])
        regression = sm.OLS(y, x).fit()
        residuals = regression.resid.dropna()
        adf_statistic, adf_p_value, _, _, critical_values, _ = adfuller(residuals, autolag="AIC")
        hedge_ratios = {target_asset: 1.0}
        hedge_ratios.update(
            {asset: -float(regression.params[asset]) for asset in explanatory_assets}
        )

        return EngleGrangerResult(
            assets=tuple(data.columns),
            target=target_asset,
            statistic=float(adf_statistic),
            p_value=float(adf_p_value),
            critical_values={key: float(value) for key, value in critical_values.items()},
            hedge_ratios=hedge_ratios,
            is_cointegrated=bool(adf_p_value < self.significance_level),
            residual_adf_statistic=float(adf_statistic),
            residual_adf_p_value=float(adf_p_value),
        )

    def johansen_test(
        self,
        prices: pd.DataFrame,
        det_order: int = 0,
        k_ar_diff: int = 1,
    ) -> JohansenResult:
        """Run the Johansen trace and max-eigenvalue cointegration tests."""

        data = self._prepare(prices)
        result = coint_johansen(data, det_order=det_order, k_ar_diff=k_ar_diff)
        assets = tuple(data.columns)

        trace_statistics = {f"rank <= {idx}": float(value) for idx, value in enumerate(result.lr1)}
        max_eigen_statistics = {f"rank <= {idx}": float(value) for idx, value in enumerate(result.lr2)}
        trace_critical_values_95 = {
            f"rank <= {idx}": float(value)
            for idx, value in enumerate(result.cvt[:, 1])
        }
        max_eigen_critical_values_95 = {
            f"rank <= {idx}": float(value)
            for idx, value in enumerate(result.cvm[:, 1])
        }
        inferred_rank_95 = int(np.sum(result.lr1 > result.cvt[:, 1]))
        eigenvectors_frame = pd.DataFrame(result.evec, index=assets)

        return JohansenResult(
            assets=assets,
            trace_statistics=trace_statistics,
            trace_critical_values_95=trace_critical_values_95,
            max_eigen_statistics=max_eigen_statistics,
            max_eigen_critical_values_95=max_eigen_critical_values_95,
            inferred_rank_95=inferred_rank_95,
            eigenvectors=eigenvectors_frame.to_dict(),
        )

