"""Optuna-based Bayesian optimization for basket trading parameters."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import optuna
import pandas as pd

from qresearch.origins.arbitrage.backtester import BacktestResult, BasketBacktester
from qresearch.origins.arbitrage.metrics import PerformanceAnalyzer
from qresearch.origins.arbitrage.signals import SignalEngine
from qresearch.origins.arbitrage.spread_builder import WeightedSpreadBuilder


LOGGER = logging.getLogger(__name__)


@dataclass
class OptimizerConfig:
    """Search-space and validation configuration for Optuna."""

    n_trials: int = 100
    random_seed: int = 42
    validation_fraction: float = 0.35
    weight_low: float = -2.0
    weight_high: float = 2.0
    entry_low: float = 1.0
    entry_high: float = 3.0
    exit_low: float = 0.05
    exit_high: float = 1.0
    rolling_window_low: int = 20
    rolling_window_high: int = 120
    position_size_low: float = 0.25
    position_size_high: float = 1.50
    min_validation_trades: int = 2


@dataclass(frozen=True)
class StrategyParameters:
    """Optimizable basket strategy parameters."""

    weights: dict[str, float]
    entry_threshold: float
    exit_threshold: float
    rolling_window: int
    position_size: float

    def to_dict(self) -> dict[str, Any]:
        """Serialize strategy parameters."""

        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StrategyParameters":
        """Deserialize strategy parameters."""

        return cls(
            weights={str(key): float(value) for key, value in data["weights"].items()},
            entry_threshold=float(data["entry_threshold"]),
            exit_threshold=float(data["exit_threshold"]),
            rolling_window=int(data["rolling_window"]),
            position_size=float(data["position_size"]),
        )


@dataclass
class OptimizationResult:
    """Result returned after Optuna optimization."""

    study: optuna.Study
    best_params: StrategyParameters
    best_value: float
    stability: pd.DataFrame


class BayesianStrategyOptimizer:
    """Optimize spread weights and signal parameters for out-of-sample Sharpe."""

    def __init__(
        self,
        config: OptimizerConfig,
        spread_builder: WeightedSpreadBuilder,
        signal_engine: SignalEngine,
        backtester: BasketBacktester,
        metrics: PerformanceAnalyzer,
    ) -> None:
        self.config = config
        self.spread_builder = spread_builder
        self.signal_engine = signal_engine
        self.backtester = backtester
        self.metrics = metrics

    def optimize(self, prices: pd.DataFrame) -> OptimizationResult:
        """Run Optuna optimization on a training window with a validation holdout."""

        sampler = optuna.samplers.TPESampler(seed=self.config.random_seed)
        study = optuna.create_study(direction="maximize", sampler=sampler)
        study.optimize(lambda trial: self._objective(trial, prices), n_trials=self.config.n_trials)

        best_params = StrategyParameters.from_dict(study.best_trial.user_attrs["strategy_params"])
        stability = self.parameter_stability(study)
        return OptimizationResult(
            study=study,
            best_params=best_params,
            best_value=float(study.best_value),
            stability=stability,
        )

    def _objective(self, trial: optuna.Trial, prices: pd.DataFrame) -> float:
        """Optuna objective: maximize validation Sharpe Ratio."""

        params = self._suggest_parameters(trial, prices.columns)
        trial.set_user_attr("strategy_params", params.to_dict())

        validation_start_idx = int(len(prices) * (1.0 - self.config.validation_fraction))
        validation_start_idx = max(validation_start_idx, params.rolling_window + 5)
        validation_start_date = prices.index[validation_start_idx]

        result = self.run_strategy(prices, params)
        validation_returns = result.returns.loc[validation_start_date:].dropna()
        if validation_returns.empty:
            raise optuna.TrialPruned("No validation returns were available.")

        validation_equity = (
            self.backtester.config.initial_capital * (1.0 + validation_returns).cumprod()
        ).rename("equity")
        validation_trades = self._filter_trades(result.trade_log, validation_returns.index[0], validation_returns.index[-1])
        report = self.metrics.calculate(validation_returns, validation_equity, validation_trades)

        trial.set_user_attr("validation_report", report)
        sharpe = report["sharpe_ratio"]
        if not np.isfinite(sharpe):
            return -1_000.0
        if report["trade_count"] < self.config.min_validation_trades:
            sharpe -= 0.25 * (self.config.min_validation_trades - report["trade_count"])
        return float(sharpe)

    def _suggest_parameters(self, trial: optuna.Trial, columns: pd.Index) -> StrategyParameters:
        """Sample a candidate strategy parameter set."""

        raw_weights = np.array(
            [
                trial.suggest_float(f"weight_{asset}", self.config.weight_low, self.config.weight_high)
                for asset in columns
            ],
            dtype=float,
        )
        if np.abs(raw_weights).sum() <= 1e-8:
            raise optuna.TrialPruned("Sampled weights have zero gross exposure.")

        # Remove sign symmetry so Optuna does not waste trials on equivalent inverted baskets.
        if raw_weights[0] < 0:
            raw_weights = -raw_weights
        normalized = raw_weights / np.abs(raw_weights).sum()
        weights = {str(asset): float(weight) for asset, weight in zip(columns, normalized)}

        entry_threshold = trial.suggest_float(
            "entry_threshold",
            self.config.entry_low,
            self.config.entry_high,
        )
        exit_upper = min(self.config.exit_high, entry_threshold - 0.05)
        if exit_upper <= self.config.exit_low:
            raise optuna.TrialPruned("Exit threshold upper bound collapsed.")
        exit_threshold = trial.suggest_float("exit_threshold", self.config.exit_low, exit_upper)
        rolling_window = trial.suggest_int(
            "rolling_window",
            self.config.rolling_window_low,
            self.config.rolling_window_high,
        )
        position_size = trial.suggest_float(
            "position_size",
            self.config.position_size_low,
            self.config.position_size_high,
        )

        return StrategyParameters(
            weights=weights,
            entry_threshold=entry_threshold,
            exit_threshold=exit_threshold,
            rolling_window=rolling_window,
            position_size=position_size,
        )

    def run_strategy(self, prices: pd.DataFrame, params: StrategyParameters) -> BacktestResult:
        """Run spread construction, signal generation, and backtesting for a parameter set."""

        stats = self.spread_builder.compute_statistics(
            prices=prices,
            weights=params.weights,
            rolling_window=params.rolling_window,
        )
        signal_frame = self.signal_engine.generate(
            z_score=stats.z_score,
            entry_threshold=params.entry_threshold,
            exit_threshold=params.exit_threshold,
        )
        return self.backtester.run(
            prices=prices,
            weights=stats.weights,
            signal_frame=signal_frame,
            spread=stats.spread,
            z_score=stats.z_score,
            position_size=params.position_size,
        )

    def evaluate(
        self,
        prices: pd.DataFrame,
        params: StrategyParameters,
    ) -> tuple[BacktestResult, dict[str, Any]]:
        """Evaluate a fixed parameter set and return the backtest plus metrics."""

        result = self.run_strategy(prices, params)
        report = self.metrics.calculate(result.returns, result.equity_curve, result.trade_log)
        return result, report

    def walk_forward_validation(
        self,
        prices: pd.DataFrame,
        train_size: int,
        test_size: int,
        step_size: int | None = None,
        n_trials: int | None = None,
    ) -> pd.DataFrame:
        """Run rolling train/test walk-forward validation."""

        records: list[dict[str, Any]] = []
        step = step_size or test_size
        original_trials = self.config.n_trials
        if n_trials is not None:
            self.config.n_trials = n_trials

        try:
            start = 0
            window_number = 0
            while start + train_size + test_size <= len(prices):
                window_number += 1
                train = prices.iloc[start : start + train_size]
                test = prices.iloc[start + train_size : start + train_size + test_size]
                LOGGER.info("Walk-forward window %s: optimizing %s to %s", window_number, train.index[0], train.index[-1])
                optimization = self.optimize(train)

                warmup = train.tail(max(optimization.best_params.rolling_window * 2, 30))
                combined = pd.concat([warmup, test])
                result = self.run_strategy(combined, optimization.best_params)
                test_returns = result.returns.reindex(test.index).dropna()
                if test_returns.empty:
                    start += step
                    continue
                test_equity = (
                    self.backtester.config.initial_capital * (1.0 + test_returns).cumprod()
                ).rename("equity")
                test_trades = self._filter_trades(result.trade_log, test.index[0], test.index[-1])
                test_report = self.metrics.calculate(test_returns, test_equity, test_trades)
                records.append(
                    {
                        "window": window_number,
                        "train_start": train.index[0],
                        "train_end": train.index[-1],
                        "test_start": test.index[0],
                        "test_end": test.index[-1],
                        "optimization_sharpe": optimization.best_value,
                        "test_sharpe": test_report["sharpe_ratio"],
                        "test_cagr": test_report["cagr"],
                        "test_max_drawdown": test_report["max_drawdown"],
                        "test_trade_count": test_report["trade_count"],
                        "best_params": optimization.best_params.to_dict(),
                    }
                )
                start += step
        finally:
            if n_trials is not None:
                self.config.n_trials = original_trials

        return pd.DataFrame(records)

    @staticmethod
    def parameter_stability(study: optuna.Study, top_fraction: float = 0.20) -> pd.DataFrame:
        """Summarize dispersion of top-trial parameters as an overfitting diagnostic."""

        trials = study.trials_dataframe(attrs=("number", "value", "params", "state"))
        if trials.empty:
            return pd.DataFrame()
        complete = trials[trials["state"] == "COMPLETE"].copy()
        if complete.empty:
            return pd.DataFrame()
        top_n = max(1, int(np.ceil(len(complete) * top_fraction)))
        top = complete.sort_values("value", ascending=False).head(top_n)
        param_columns = [column for column in top.columns if column.startswith("params_")]
        if not param_columns:
            return pd.DataFrame()
        stability = top[param_columns].agg(["mean", "std", "min", "max"]).T
        stability.index = stability.index.str.replace("params_", "", regex=False)
        stability["coefficient_of_variation"] = stability["std"] / stability["mean"].abs().replace(0.0, np.nan)
        return stability

    @staticmethod
    def save_optimization_artifacts(study: optuna.Study, output_dir: Path, figure_dir: Path) -> None:
        """Persist Optuna trials and diagnostic figures."""

        output_dir.mkdir(parents=True, exist_ok=True)
        figure_dir.mkdir(parents=True, exist_ok=True)
        trials = study.trials_dataframe()
        trials.to_csv(output_dir / "optuna_trials.csv", index=False)

        try:
            import matplotlib.pyplot as plt
            from optuna.visualization.matplotlib import plot_optimization_history, plot_param_importances

            ax = plot_optimization_history(study)
            ax.figure.tight_layout()
            ax.figure.savefig(figure_dir / "optimization_history.png", dpi=160)
            plt.close(ax.figure)

            ax = plot_param_importances(study)
            ax.figure.tight_layout()
            ax.figure.savefig(figure_dir / "parameter_importance.png", dpi=160)
            plt.close(ax.figure)
        except Exception as exc:  # pragma: no cover - plotting is environment-dependent.
            LOGGER.warning("Could not save Optuna visualization figures: %s", exc)

    @staticmethod
    def _filter_trades(trade_log: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        """Return trades that overlap a given date interval."""

        if trade_log.empty:
            return trade_log
        trade_log = trade_log.copy()
        trade_log["entry_date"] = pd.to_datetime(trade_log["entry_date"])
        trade_log["exit_date"] = pd.to_datetime(trade_log["exit_date"])
        return trade_log[(trade_log["exit_date"] >= start) & (trade_log["entry_date"] <= end)]
