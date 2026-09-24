"""PnL, risk analytics, and visualization utilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, Mapping

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def compute_drawdown(equity_curve: pd.Series) -> pd.Series:
    """Return drawdown from the running maximum of an equity curve."""

    running_max = equity_curve.cummax()
    return equity_curve - running_max


def sharpe_ratio(returns: pd.Series, periods_per_year: float) -> float:
    """Annualized Sharpe ratio for a return series."""

    clean_returns = returns.replace([np.inf, -np.inf], np.nan).dropna()
    if clean_returns.empty or clean_returns.std(ddof=1) == 0.0:
        return 0.0
    return float(np.sqrt(periods_per_year) * clean_returns.mean() / clean_returns.std(ddof=1))


def compute_performance_metrics(state: pd.DataFrame, dt: float) -> Dict[str, float]:
    """Compute headline risk and performance statistics."""

    if state.empty:
        raise ValueError("state DataFrame cannot be empty")

    pnl = state["portfolio_value"] - state["portfolio_value"].iloc[0]
    gross_exposure = state["gross_exposure"].shift(1).clip(lower=1.0)
    portfolio_returns = state["portfolio_value"].diff().fillna(0.0) / gross_exposure
    drawdown = compute_drawdown(state["portfolio_value"])
    periods_per_year = 1.0 / dt

    metrics = {
        "total_pnl": float(pnl.iloc[-1]),
        "average_step_pnl": float(state["portfolio_value"].diff().fillna(0.0).mean()),
        "pnl_volatility": float(state["portfolio_value"].diff().fillna(0.0).std(ddof=1)),
        "sharpe_ratio": sharpe_ratio(portfolio_returns, periods_per_year),
        "max_drawdown": float(drawdown.min()),
        "max_abs_inventory": float(state["option_inventory"].abs().max()),
        "max_abs_net_delta": float(state["net_delta"].abs().max()),
        "mean_abs_hedge_error": float(state["hedge_error"].abs().mean()),
        "final_option_inventory": float(state["option_inventory"].iloc[-1]),
        "final_stock_position": float(state["stock_position"].iloc[-1]),
        "realized_volatility_last": float(state["realized_volatility"].iloc[-1]),
        "realized_volatility_mean": float(state["realized_volatility"].mean()),
    }
    return metrics


def save_results(
    state: pd.DataFrame,
    trades: pd.DataFrame,
    hedges: pd.DataFrame,
    metrics: Mapping[str, float],
    results_dir: Path,
) -> None:
    """Write simulation state, trade logs, hedge logs, and metrics to disk."""

    results_dir.mkdir(parents=True, exist_ok=True)
    state.to_csv(results_dir / "simulation_state.csv", index=False)
    trades.to_csv(results_dir / "option_trades.csv", index=False)
    hedges.to_csv(results_dir / "hedge_trades.csv", index=False)
    with (results_dir / "risk_metrics.json").open("w", encoding="utf-8") as handle:
        json.dump(dict(metrics), handle, indent=2, sort_keys=True)


def plot_market_making_dashboard(
    state: pd.DataFrame,
    trades: pd.DataFrame,
    plots_dir: Path,
) -> Iterable[Path]:
    """Create a professional dashboard and focused analytics plots."""

    plots_dir.mkdir(parents=True, exist_ok=True)
    plt.style.use("seaborn-v0_8-whitegrid")
    created: list[Path] = []

    equity = state["portfolio_value"]
    cumulative_pnl = equity - equity.iloc[0]
    drawdown = compute_drawdown(equity)

    fig, axes = plt.subplots(3, 2, figsize=(16, 13), constrained_layout=True)
    fig.suptitle("Derivatives Pricing + Market Making System", fontsize=18, fontweight="bold")

    axes[0, 0].plot(state["step"], state["spot"], color="#1f77b4", linewidth=1.8)
    axes[0, 0].set_title("GBM Underlying Price")
    axes[0, 0].set_xlabel("Simulation Step")
    axes[0, 0].set_ylabel("Spot")

    axes[0, 1].plot(state["step"], cumulative_pnl, color="#2ca02c", linewidth=1.8)
    axes[0, 1].axhline(0.0, color="#444444", linewidth=0.8)
    axes[0, 1].set_title("Cumulative PnL")
    axes[0, 1].set_xlabel("Simulation Step")
    axes[0, 1].set_ylabel("PnL")

    axes[1, 0].plot(state["step"], state["option_inventory"], label="Option Contracts", color="#9467bd")
    axes[1, 0].plot(state["step"], state["stock_position"], label="Stock Shares", color="#ff7f0e")
    axes[1, 0].set_title("Inventory and Hedge Position")
    axes[1, 0].set_xlabel("Simulation Step")
    axes[1, 0].legend()

    axes[1, 1].plot(state["step"], state["net_delta"], label="Net Delta", color="#d62728")
    axes[1, 1].plot(state["step"], state["hedge_error"], label="Hedge Error", color="#17becf", alpha=0.8)
    axes[1, 1].axhline(0.0, color="#444444", linewidth=0.8)
    axes[1, 1].set_title("Delta Exposure")
    axes[1, 1].set_xlabel("Simulation Step")
    axes[1, 1].legend()

    axes[2, 0].plot(state["step"], state["realized_volatility"], color="#8c564b", linewidth=1.6)
    axes[2, 0].set_title("Rolling Realized Volatility")
    axes[2, 0].set_xlabel("Simulation Step")
    axes[2, 0].set_ylabel("Annualized Vol")

    axes[2, 1].fill_between(state["step"], drawdown, 0.0, color="#e377c2", alpha=0.45)
    axes[2, 1].set_title("Drawdown")
    axes[2, 1].set_xlabel("Simulation Step")
    axes[2, 1].set_ylabel("Drawdown")

    dashboard_path = plots_dir / "market_making_dashboard.png"
    fig.savefig(dashboard_path, dpi=160)
    plt.close(fig)
    created.append(dashboard_path)

    created.extend(
        [
            _line_plot(
                state["step"],
                cumulative_pnl,
                "Cumulative PnL",
                "Simulation Step",
                "PnL",
                plots_dir / "cumulative_pnl.png",
                "#2ca02c",
            ),
            _line_plot(
                state["step"],
                state["option_inventory"],
                "Option Inventory Exposure",
                "Simulation Step",
                "Contracts",
                plots_dir / "inventory_exposure.png",
                "#9467bd",
            ),
            _line_plot(
                state["step"],
                state["hedge_error"],
                "Hedge Error",
                "Simulation Step",
                "Share-Equivalent Delta",
                plots_dir / "hedge_error.png",
                "#d62728",
            ),
            _line_plot(
                state["step"],
                state["realized_volatility"],
                "Rolling Realized Volatility",
                "Simulation Step",
                "Annualized Volatility",
                plots_dir / "realized_volatility.png",
                "#8c564b",
            ),
        ]
    )

    if not trades.empty:
        created.append(_trade_plot(state, trades, plots_dir / "option_trade_prices.png"))

    return created


def _line_plot(
    x: pd.Series,
    y: pd.Series,
    title: str,
    xlabel: str,
    ylabel: str,
    output_path: Path,
    color: str,
) -> Path:
    fig, ax = plt.subplots(figsize=(11, 5.5), constrained_layout=True)
    ax.plot(x, y, color=color, linewidth=1.8)
    ax.axhline(0.0, color="#444444", linewidth=0.8)
    ax.set_title(title, fontweight="bold")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    fig.savefig(output_path, dpi=160)
    plt.close(fig)
    return output_path


def _trade_plot(state: pd.DataFrame, trades: pd.DataFrame, output_path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(11, 5.5), constrained_layout=True)
    ax.plot(state["step"], state["option_mid"], color="#1f77b4", linewidth=1.6, label="Option Mid")

    buy_trades = trades[trades["customer_side"] == "buy"]
    sell_trades = trades[trades["customer_side"] == "sell"]
    if not buy_trades.empty:
        ax.scatter(
            buy_trades["step"],
            buy_trades["price"],
            color="#2ca02c",
            s=20,
            label="Customer Buy",
            alpha=0.75,
        )
    if not sell_trades.empty:
        ax.scatter(
            sell_trades["step"],
            sell_trades["price"],
            color="#d62728",
            s=20,
            label="Customer Sell",
            alpha=0.75,
        )
    ax.set_title("Executed Option Trade Prices", fontweight="bold")
    ax.set_xlabel("Simulation Step")
    ax.set_ylabel("Option Price")
    ax.legend()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)
    return output_path
