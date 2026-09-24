from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from plotly.subplots import make_subplots
from scipy import stats
from statsmodels.graphics.gofplots import qqplot
from statsmodels.graphics.tsaplots import plot_acf
from statsmodels.tsa.stattools import coint

from qresearch.origins.regime.analytics.metrics import (
    active_return_series,
    annual_return_series,
    annualized_return,
    annualized_volatility,
    calculate_capture_ratios,
    calculate_performance_metrics,
    conditional_value_at_risk,
    drawdown_duration_series,
    drawdown_periods,
    half_life_of_mean_reversion,
    information_ratio,
    monthly_return_table,
    monthly_win_rate,
    profit_factor_by_year,
    regime_duration_table,
    regime_statistics,
    rolling_alpha,
    rolling_beta,
    rolling_information_ratio,
    rolling_sharpe,
    rolling_sortino,
    rolling_tracking_error,
    rolling_value_at_risk,
    rolling_volatility,
    sharpe_ratio,
    strategy_statistics_by_regime,
    tracking_error,
    value_at_risk,
    volatility_contribution,
)
from qresearch.origins.regime.backtester.engine import BacktestResult
from qresearch.origins.regime.strategies.base import StrategyOutput
from qresearch.origins.regime.utils.helpers import ensure_directory, save_dataframe


plt.style.use("seaborn-v0_8-whitegrid")
plt.rcParams.update(
    {
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.edgecolor": "#334155",
        "axes.labelcolor": "#0f172a",
        "axes.titleweight": "bold",
        "axes.titlesize": 14,
        "axes.labelsize": 11,
        "grid.color": "#cbd5e1",
        "grid.alpha": 0.35,
        "legend.frameon": True,
        "legend.facecolor": "white",
        "legend.edgecolor": "#cbd5e1",
        "font.size": 10,
    }
)


COLORS = {
    "equity": "#1f77b4",
    "benchmark": "#475569",
    "drawdown": "#d62728",
    "bull": "#2ca02c",
    "bear": "#d62728",
    "high_volatility": "#ff7f0e",
    "positive": "#2ca02c",
    "negative": "#d62728",
    "accent": "#0ea5e9",
    "neutral": "#64748b",
}

REGIME_COLORS = {
    "Bull": COLORS["bull"],
    "Bear": COLORS["bear"],
    "High Volatility": COLORS["high_volatility"],
}


@dataclass(slots=True)
class FullReportArtifacts:
    """Container returned by the full analytics report generator."""

    figures: dict[str, Path]
    reports: dict[str, Path]


def _finalize_figure(fig: plt.Figure, output_path: str | Path, dpi: int = 300) -> Path:
    """Save a matplotlib figure with consistent formatting."""
    path = Path(output_path)
    ensure_directory(path.parent)
    fig.tight_layout()
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return path


def _save_message_figure(title: str, output_path: str | Path, message: str = "No data available.") -> Path:
    """Persist a placeholder figure when a plot cannot be constructed."""
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.axis("off")
    ax.text(0.5, 0.55, title, ha="center", va="center", fontsize=15, weight="bold")
    ax.text(0.5, 0.40, message, ha="center", va="center", fontsize=11, color=COLORS["neutral"])
    return _finalize_figure(fig, output_path)


def _format_time_axis(ax: plt.Axes) -> None:
    """Apply a yearly formatter to a datetime x-axis."""
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))


def _format_percent_axis(ax: plt.Axes) -> None:
    """Display a decimal-valued axis as percentages."""
    ax.yaxis.set_major_formatter(mtick.PercentFormatter(xmax=1.0))


def _format_percent_x_axis(ax: plt.Axes) -> None:
    """Display a decimal-valued x-axis as percentages."""
    ax.xaxis.set_major_formatter(mtick.PercentFormatter(xmax=1.0))


def _cumulative_returns(returns: pd.Series) -> pd.Series:
    """Convert daily returns to a cumulative return index."""
    clean = pd.to_numeric(returns, errors="coerce").fillna(0.0)
    return (1.0 + clean).cumprod() - 1.0


def _aligned_regimes(regimes: pd.Series, index: pd.Index) -> pd.Series:
    """Align regime labels to a target index."""
    if regimes.empty:
        return pd.Series(index=index, dtype=object, name="regime")
    return regimes.reindex(index).ffill().bfill().rename("regime")


def _add_regime_background(ax: plt.Axes, index: pd.Index, regimes: pd.Series, alpha: float = 0.10) -> None:
    """Shade plot background by detected regime."""
    aligned_regimes = _aligned_regimes(regimes, index)
    if aligned_regimes.empty:
        return

    regime_groups = (aligned_regimes != aligned_regimes.shift()).cumsum()
    for _, run in aligned_regimes.groupby(regime_groups):
        color = REGIME_COLORS.get(str(run.iloc[0]), "#94a3b8")
        ax.axvspan(run.index[0], run.index[-1], color=color, alpha=alpha)


def _save_table_figure(
    table: pd.DataFrame,
    output_path: str | Path,
    title: str,
    percent_columns: list[str] | None = None,
) -> Path:
    """Render a DataFrame as a static figure."""
    if table.empty:
        return _save_message_figure(title=title, output_path=output_path)

    display_table = table.copy()
    percent_columns = percent_columns or []
    for column in percent_columns:
        if column in display_table.columns:
            display_table[column] = display_table[column].map(
                lambda value: f"{value:.2%}" if pd.notna(value) else ""
            )

    for column in display_table.columns:
        if pd.api.types.is_numeric_dtype(display_table[column]) and column not in percent_columns:
            display_table[column] = display_table[column].map(lambda value: f"{value:.2f}" if pd.notna(value) else "")
        elif pd.api.types.is_datetime64_any_dtype(display_table[column]):
            display_table[column] = display_table[column].dt.strftime("%Y-%m-%d").fillna("Open")

    fig_height = max(3.5, 0.5 + 0.45 * (len(display_table) + 1))
    fig, ax = plt.subplots(figsize=(12, fig_height))
    ax.axis("off")
    ax.set_title(title, loc="left", pad=16)
    table_artist = ax.table(
        cellText=display_table.values,
        colLabels=list(display_table.columns),
        cellLoc="center",
        loc="center",
    )
    table_artist.auto_set_font_size(False)
    table_artist.set_fontsize(9)
    table_artist.scale(1.0, 1.4)
    return _finalize_figure(fig, output_path)


def _extract_trade_table(
    strategy_returns: pd.DataFrame,
    strategy_outputs: Mapping[str, StrategyOutput],
) -> pd.DataFrame:
    """Aggregate trade-level return and duration statistics from strategy activity."""
    rows: list[dict[str, Any]] = []
    for strategy_name, strategy_output in strategy_outputs.items():
        if strategy_name not in strategy_returns.columns:
            continue

        gross_exposure = strategy_output.positions.abs().sum(axis=1)
        active = gross_exposure > 0.0
        if not active.any():
            continue

        trade_starts = active & ~active.shift(fill_value=False)
        trade_ids = trade_starts.cumsum().where(active)
        valid_trade_ids = pd.Series(trade_ids.dropna().unique()).astype(int).tolist()

        for trade_id in valid_trade_ids:
            trade_index = trade_ids[trade_ids == trade_id].index
            if len(trade_index) == 0:
                continue

            trade_returns = strategy_returns.loc[trade_index, strategy_name].fillna(0.0)
            rows.append(
                {
                    "Strategy": strategy_name,
                    "Start Date": trade_index[0],
                    "End Date": trade_index[-1],
                    "Duration": int(len(trade_index)),
                    "Trade Return": float((1.0 + trade_returns).prod() - 1.0),
                }
            )

    return pd.DataFrame(rows)


def _representative_signal_series(
    strategy_name: str,
    strategy_output: StrategyOutput,
    prices: pd.DataFrame,
) -> tuple[pd.Series, pd.Series, str] | None:
    """Choose a representative asset price and signal series for visualization."""
    metadata = strategy_output.metadata or {}
    if strategy_name == "pairs_trading" and strategy_output.diagnostics is not None:
        asset_y = str(metadata.get("asset_y", ""))
        if asset_y and asset_y in prices.columns and "pair_position" in strategy_output.diagnostics.columns:
            return prices[asset_y], strategy_output.diagnostics["pair_position"].fillna(0.0), asset_y

    candidate_assets = metadata.get("assets")
    if isinstance(candidate_assets, list) and candidate_assets:
        for asset in candidate_assets:
            if asset in prices.columns and asset in strategy_output.positions.columns:
                return prices[asset], strategy_output.positions[asset].fillna(0.0), str(asset)

    active_columns = strategy_output.positions.abs().sum(axis=0).sort_values(ascending=False).index.tolist()
    for asset in active_columns:
        if asset in prices.columns:
            return prices[asset], strategy_output.positions[asset].fillna(0.0), str(asset)

    return None


def _simulate_monte_carlo_paths(
    returns: pd.Series,
    n_simulations: int = 500,
    random_seed: int = 42,
) -> pd.DataFrame:
    """Bootstrap historical returns into Monte Carlo equity paths."""
    clean_returns = pd.to_numeric(returns, errors="coerce").dropna()
    if clean_returns.empty:
        return pd.DataFrame()

    rng = np.random.default_rng(random_seed)
    sampled_returns = rng.choice(clean_returns.to_numpy(dtype=float), size=(len(clean_returns), n_simulations), replace=True)
    equity_paths = np.vstack([np.ones(n_simulations), np.cumprod(1.0 + sampled_returns, axis=0)])
    columns = [f"simulation_{simulation}" for simulation in range(n_simulations)]
    return pd.DataFrame(equity_paths, index=range(equity_paths.shape[0]), columns=columns)


def plot_equity_curve(equity_curve: pd.Series, output_path: str | Path) -> Path:
    """Save a portfolio equity curve chart."""
    if equity_curve.dropna().empty:
        return _save_message_figure("Portfolio Equity Curve", output_path)
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(equity_curve.index, equity_curve.values, color=COLORS["equity"], linewidth=2.1)
    ax.set_title("Portfolio Equity Curve")
    ax.set_ylabel("Portfolio Value")
    ax.grid(alpha=0.3)
    _format_time_axis(ax)
    return _finalize_figure(fig, output_path)


def plot_drawdown(drawdown: pd.Series, output_path: str | Path) -> Path:
    """Save a drawdown chart."""
    return plot_underwater(drawdown=drawdown, output_path=output_path)


def plot_underwater(drawdown: pd.Series, output_path: str | Path) -> Path:
    """Save an underwater drawdown plot."""
    if drawdown.dropna().empty:
        return _save_message_figure("Underwater Plot", output_path)
    fig, ax = plt.subplots(figsize=(12, 4.5))
    ax.fill_between(drawdown.index, drawdown.values, 0.0, color=COLORS["drawdown"], alpha=0.32)
    ax.plot(drawdown.index, drawdown.values, color=COLORS["drawdown"], linewidth=1.4)
    ax.axhline(0.0, color="#0f172a", linewidth=0.9)
    ax.set_title("Underwater Plot")
    ax.set_ylabel("Drawdown")
    _format_percent_axis(ax)
    _format_time_axis(ax)
    return _finalize_figure(fig, output_path)


def plot_monthly_returns_heatmap(returns: pd.Series, output_path: str | Path) -> Path:
    """Save a year-by-month return heatmap with annual totals."""
    heatmap = monthly_return_table(returns)
    if heatmap.empty:
        return _save_message_figure("Monthly Returns Heatmap", output_path)

    fig, ax = plt.subplots(figsize=(14, max(4.5, 0.5 * len(heatmap) + 2.5)))
    image = ax.imshow(heatmap.fillna(0.0).values, cmap="RdYlGn", aspect="auto", vmin=-0.25, vmax=0.25)
    ax.set_title("Monthly Returns Heatmap")
    ax.set_xticks(range(len(heatmap.columns)))
    ax.set_xticklabels(heatmap.columns)
    ax.set_yticks(range(len(heatmap.index)))
    ax.set_yticklabels(heatmap.index)

    for row in range(heatmap.shape[0]):
        for col in range(heatmap.shape[1]):
            value = heatmap.iloc[row, col]
            label = "" if pd.isna(value) else f"{value:.1%}"
            ax.text(col, row, label, ha="center", va="center", fontsize=9, color="#0f172a")

    fig.colorbar(image, ax=ax, fraction=0.03, pad=0.02)
    return _finalize_figure(fig, output_path)


def plot_annual_returns_bar(returns: pd.Series, output_path: str | Path) -> Path:
    """Save a yearly returns bar chart."""
    annual_returns = annual_return_series(returns)
    if annual_returns.empty:
        return _save_message_figure("Annual Returns", output_path)

    colors = [COLORS["positive"] if value >= 0.0 else COLORS["negative"] for value in annual_returns.values]
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.bar(annual_returns.index.astype(str), annual_returns.values, color=colors, alpha=0.85)
    ax.axhline(0.0, color="#0f172a", linewidth=0.9)
    ax.set_title("Annual Returns")
    ax.set_ylabel("Return")
    _format_percent_axis(ax)
    return _finalize_figure(fig, output_path)


def plot_rolling_volatility(
    returns: pd.Series,
    output_path: str | Path,
    windows: tuple[int, int] = (21, 63),
    periods_per_year: int = 252,
) -> Path:
    """Save rolling annualized volatility series."""
    clean_returns = pd.to_numeric(returns, errors="coerce").dropna()
    if clean_returns.empty:
        return _save_message_figure("Rolling Volatility", output_path)

    fig, ax = plt.subplots(figsize=(12, 4.5))
    palette = [COLORS["accent"], COLORS["benchmark"]]
    for color, window in zip(palette, windows):
        rolling_metric = rolling_volatility(clean_returns, window=window, periods_per_year=periods_per_year)
        ax.plot(rolling_metric.index, rolling_metric.values, label=f"{window}-Day", linewidth=1.7, color=color)
    ax.set_title("Rolling Annualized Volatility")
    ax.set_ylabel("Volatility")
    _format_percent_axis(ax)
    _format_time_axis(ax)
    ax.legend(loc="best")
    return _finalize_figure(fig, output_path)


def plot_rolling_sharpe(
    returns: pd.Series,
    output_path: str | Path,
    window: int = 63,
    periods_per_year: int = 252,
) -> Path:
    """Save a rolling Sharpe ratio chart."""
    rolling_metric = rolling_sharpe(returns=returns, window=window, periods_per_year=periods_per_year)
    if rolling_metric.dropna().empty:
        return _save_message_figure(f"Rolling {window}-Day Sharpe Ratio", output_path)
    fig, ax = plt.subplots(figsize=(12, 4.5))
    ax.plot(rolling_metric.index, rolling_metric.values, color=COLORS["positive"], linewidth=1.75)
    ax.axhline(0.0, color="#0f172a", linewidth=0.9, linestyle="--")
    ax.set_title(f"Rolling {window}-Day Sharpe Ratio")
    ax.set_ylabel("Sharpe")
    _format_time_axis(ax)
    return _finalize_figure(fig, output_path)


def plot_rolling_sortino(
    returns: pd.Series,
    output_path: str | Path,
    window: int = 63,
    periods_per_year: int = 252,
) -> Path:
    """Save a rolling Sortino ratio chart."""
    rolling_metric = rolling_sortino(returns=returns, window=window, periods_per_year=periods_per_year)
    if rolling_metric.dropna().empty:
        return _save_message_figure(f"Rolling {window}-Day Sortino Ratio", output_path)
    fig, ax = plt.subplots(figsize=(12, 4.5))
    ax.plot(rolling_metric.index, rolling_metric.values, color=COLORS["accent"], linewidth=1.75)
    ax.axhline(0.0, color="#0f172a", linewidth=0.9, linestyle="--")
    ax.set_title(f"Rolling {window}-Day Sortino Ratio")
    ax.set_ylabel("Sortino")
    _format_time_axis(ax)
    return _finalize_figure(fig, output_path)


def plot_rolling_beta(
    returns: pd.Series,
    benchmark_returns: pd.Series,
    output_path: str | Path,
    window: int = 63,
) -> Path:
    """Save a rolling beta chart relative to the benchmark."""
    beta_series = rolling_beta(returns=returns, benchmark_returns=benchmark_returns, window=window)
    if beta_series.dropna().empty:
        return _save_message_figure("Rolling Beta vs Benchmark", output_path)
    fig, ax = plt.subplots(figsize=(12, 4.5))
    ax.plot(beta_series.index, beta_series.values, color=COLORS["benchmark"], linewidth=1.75)
    ax.axhline(1.0, color=COLORS["neutral"], linestyle="--", linewidth=1.0)
    ax.set_title(f"Rolling {window}-Day Beta vs Benchmark")
    ax.set_ylabel("Beta")
    _format_time_axis(ax)
    return _finalize_figure(fig, output_path)


def plot_rolling_alpha(
    returns: pd.Series,
    benchmark_returns: pd.Series,
    output_path: str | Path,
    window: int = 63,
    periods_per_year: int = 252,
) -> Path:
    """Save a rolling annualized CAPM alpha chart."""
    alpha_series = rolling_alpha(
        returns=returns,
        benchmark_returns=benchmark_returns,
        window=window,
        periods_per_year=periods_per_year,
    )
    if alpha_series.dropna().empty:
        return _save_message_figure("Rolling Alpha", output_path)
    fig, ax = plt.subplots(figsize=(12, 4.5))
    ax.plot(alpha_series.index, alpha_series.values, color=COLORS["equity"], linewidth=1.75)
    ax.axhline(0.0, color="#0f172a", linewidth=0.9, linestyle="--")
    ax.set_title(f"Rolling {window}-Day Annualized Alpha")
    ax.set_ylabel("Alpha")
    _format_percent_axis(ax)
    _format_time_axis(ax)
    return _finalize_figure(fig, output_path)


def plot_return_distribution_histogram(returns: pd.Series, output_path: str | Path) -> Path:
    """Save a return distribution histogram with mean and median markers."""
    clean_returns = pd.to_numeric(returns, errors="coerce").dropna()
    if clean_returns.empty:
        return _save_message_figure("Return Distribution", output_path)
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.hist(clean_returns.values, bins=40, color=COLORS["equity"], alpha=0.70, edgecolor="white")
    ax.axvline(clean_returns.mean(), color=COLORS["positive"], linewidth=2.0, linestyle="--", label="Mean")
    ax.axvline(clean_returns.median(), color=COLORS["negative"], linewidth=2.0, linestyle=":", label="Median")
    ax.set_title("Return Distribution")
    ax.set_xlabel("Daily Return")
    ax.set_ylabel("Frequency")
    _format_percent_x_axis(ax)
    ax.legend(loc="best")
    return _finalize_figure(fig, output_path)


def plot_var_cvar_distribution(returns: pd.Series, output_path: str | Path) -> Path:
    """Save a return distribution with VaR and CVaR thresholds."""
    clean_returns = pd.to_numeric(returns, errors="coerce").dropna()
    if clean_returns.empty:
        return _save_message_figure("VaR and CVaR Distribution", output_path)

    var_95 = value_at_risk(clean_returns, confidence_level=0.95)
    cvar_95 = conditional_value_at_risk(clean_returns, confidence_level=0.95)
    var_99 = value_at_risk(clean_returns, confidence_level=0.99)
    cvar_99 = conditional_value_at_risk(clean_returns, confidence_level=0.99)

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.hist(clean_returns.values, bins=40, color=COLORS["benchmark"], alpha=0.7, edgecolor="white")
    ax.axvline(var_95, color=COLORS["drawdown"], linestyle="--", linewidth=1.8, label="VaR 95")
    ax.axvline(cvar_95, color=COLORS["drawdown"], linestyle="-", linewidth=1.8, label="CVaR 95")
    ax.axvline(var_99, color=COLORS["high_volatility"], linestyle="--", linewidth=1.8, label="VaR 99")
    ax.axvline(cvar_99, color=COLORS["high_volatility"], linestyle="-", linewidth=1.8, label="CVaR 99")
    ax.set_title("Historical VaR and Conditional VaR")
    ax.set_xlabel("Daily Return")
    ax.set_ylabel("Frequency")
    _format_percent_x_axis(ax)
    ax.legend(loc="best")
    return _finalize_figure(fig, output_path)


def plot_qq_returns(returns: pd.Series, output_path: str | Path) -> Path:
    """Save a QQ plot comparing returns against a normal distribution."""
    clean_returns = pd.to_numeric(returns, errors="coerce").dropna()
    if clean_returns.empty:
        return _save_message_figure("QQ Plot", output_path)
    fig = plt.figure(figsize=(6, 6))
    qqplot(clean_returns, line="45", ax=fig.add_subplot(111))
    fig.axes[0].set_title("QQ Plot of Returns vs Normal Distribution")
    return _finalize_figure(fig, output_path)


def plot_autocorrelation(returns: pd.Series, output_path: str | Path, lags: int = 21) -> Path:
    """Save an autocorrelation chart."""
    clean_returns = pd.to_numeric(returns, errors="coerce").dropna()
    if clean_returns.empty:
        return _save_message_figure("Autocorrelation of Returns", output_path)
    fig, ax = plt.subplots(figsize=(10, 4.5))
    plot_acf(clean_returns, lags=lags, zero=False, ax=ax)
    ax.set_title("Autocorrelation of Returns")
    return _finalize_figure(fig, output_path)


def plot_cumulative_returns_comparison(
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series,
    strategy_returns: pd.DataFrame,
    output_path: str | Path,
    benchmark_name: str = "Benchmark",
) -> Path:
    """Save cumulative return curves for the portfolio, benchmark, and components."""
    if pd.to_numeric(portfolio_returns, errors="coerce").dropna().empty:
        return _save_message_figure("Cumulative Returns Comparison", output_path)

    fig, ax = plt.subplots(figsize=(12, 6))
    portfolio_curve = _cumulative_returns(portfolio_returns)
    benchmark_curve = _cumulative_returns(benchmark_returns)
    ax.plot(portfolio_curve.index, portfolio_curve.values, color=COLORS["equity"], linewidth=2.2, label="Portfolio")
    ax.plot(benchmark_curve.index, benchmark_curve.values, color=COLORS["benchmark"], linewidth=1.8, label=benchmark_name)

    for strategy in strategy_returns.columns:
        strategy_curve = _cumulative_returns(strategy_returns[strategy])
        ax.plot(strategy_curve.index, strategy_curve.values, linewidth=1.3, alpha=0.9, label=strategy.replace("_", " ").title())

    ax.set_title("Cumulative Returns Comparison")
    ax.set_ylabel("Cumulative Return")
    _format_percent_axis(ax)
    _format_time_axis(ax)
    ax.legend(loc="best", ncol=2)
    return _finalize_figure(fig, output_path)


def plot_strategy_cumulative_returns(strategy_returns: pd.DataFrame, output_path: str | Path) -> Path:
    """Save cumulative return comparison for component strategies only."""
    if strategy_returns.dropna(how="all").empty:
        return _save_message_figure("Strategy Cumulative Returns", output_path)

    fig, ax = plt.subplots(figsize=(12, 6))
    for column in strategy_returns.columns:
        cumulative = _cumulative_returns(strategy_returns[column])
        ax.plot(cumulative.index, cumulative.values, linewidth=1.6, label=column.replace("_", " ").title())
    ax.set_title("Strategy Cumulative Returns")
    ax.set_ylabel("Cumulative Return")
    _format_percent_axis(ax)
    _format_time_axis(ax)
    ax.legend(loc="best")
    return _finalize_figure(fig, output_path)


def plot_rolling_var(
    returns: pd.Series,
    output_path: str | Path,
    window: int = 63,
    confidence_level: float = 0.95,
) -> Path:
    """Save rolling historical VaR."""
    rolling_var = rolling_value_at_risk(returns=returns, window=window, confidence_level=confidence_level)
    if rolling_var.dropna().empty:
        return _save_message_figure("Rolling VaR", output_path)
    fig, ax = plt.subplots(figsize=(12, 4.5))
    ax.plot(rolling_var.index, rolling_var.values, color=COLORS["drawdown"], linewidth=1.8)
    ax.set_title(f"Rolling {window}-Day Historical VaR ({int(confidence_level * 100)}%)")
    ax.set_ylabel("VaR")
    _format_percent_axis(ax)
    _format_time_axis(ax)
    return _finalize_figure(fig, output_path)


def plot_drawdown_duration(drawdown: pd.Series, output_path: str | Path) -> Path:
    """Save drawdown duration over time."""
    duration_series = drawdown_duration_series(drawdown)
    if duration_series.dropna().empty:
        return _save_message_figure("Drawdown Duration", output_path)
    fig, ax = plt.subplots(figsize=(12, 4.5))
    ax.fill_between(duration_series.index, duration_series.values, 0, color=COLORS["drawdown"], alpha=0.25)
    ax.plot(duration_series.index, duration_series.values, color=COLORS["drawdown"], linewidth=1.6)
    ax.set_title("Drawdown Duration")
    ax.set_ylabel("Trading Days")
    _format_time_axis(ax)
    return _finalize_figure(fig, output_path)


def plot_worst_drawdown_table(returns: pd.Series, output_path: str | Path, top_n: int = 10) -> Path:
    """Save the worst drawdowns as a table figure."""
    table = drawdown_periods(returns, top_n=top_n)
    return _save_table_figure(
        table=table,
        output_path=output_path,
        title=f"Top {top_n} Drawdowns",
        percent_columns=["Depth"],
    )


def plot_signal_plot(
    price: pd.Series,
    signal: pd.Series,
    output_path: str | Path,
    title: str,
    asset_label: str,
) -> Path:
    """Save a price chart with long and short entry markers."""
    clean_price = pd.to_numeric(price, errors="coerce").dropna()
    clean_signal = pd.to_numeric(signal, errors="coerce").reindex(clean_price.index).fillna(0.0)
    if clean_price.empty:
        return _save_message_figure(title, output_path)

    previous_signal = clean_signal.shift(fill_value=0.0)
    long_entries = clean_signal[(clean_signal > 0.0) & (previous_signal <= 0.0)].index
    short_entries = clean_signal[(clean_signal < 0.0) & (previous_signal >= 0.0)].index
    exits = clean_signal[(clean_signal == 0.0) & (previous_signal != 0.0)].index

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(clean_price.index, clean_price.values, color=COLORS["equity"], linewidth=1.7, label=asset_label)
    ax.scatter(long_entries, clean_price.reindex(long_entries), marker="^", s=70, color=COLORS["positive"], label="Long Entry")
    ax.scatter(short_entries, clean_price.reindex(short_entries), marker="v", s=70, color=COLORS["negative"], label="Short Entry")
    ax.scatter(exits, clean_price.reindex(exits), marker="o", s=45, color=COLORS["neutral"], label="Exit")
    ax.set_title(title)
    ax.set_ylabel("Price")
    _format_time_axis(ax)
    ax.legend(loc="best")
    return _finalize_figure(fig, output_path)


def plot_position_exposure(positions: pd.DataFrame, output_path: str | Path) -> Path:
    """Save long, short, net, and gross exposure over time."""
    if positions.dropna(how="all").empty:
        return _save_message_figure("Position Exposure", output_path)

    long_exposure = positions.clip(lower=0.0).sum(axis=1)
    short_exposure = positions.clip(upper=0.0).sum(axis=1)
    gross_exposure = positions.abs().sum(axis=1)
    net_exposure = positions.sum(axis=1)

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(long_exposure.index, long_exposure.values, label="Long Exposure", color=COLORS["positive"], linewidth=1.5)
    ax.plot(short_exposure.index, short_exposure.values, label="Short Exposure", color=COLORS["negative"], linewidth=1.5)
    ax.plot(net_exposure.index, net_exposure.values, label="Net Exposure", color=COLORS["equity"], linewidth=1.6)
    ax.plot(gross_exposure.index, gross_exposure.values, label="Gross Exposure", color=COLORS["benchmark"], linewidth=1.4, linestyle="--")
    ax.set_title("Position Exposure")
    ax.set_ylabel("Exposure")
    _format_time_axis(ax)
    ax.legend(loc="best")
    return _finalize_figure(fig, output_path)


def plot_turnover(turnover: pd.Series, output_path: str | Path, rolling_window: int = 21) -> Path:
    """Save daily turnover and its rolling average."""
    clean_turnover = pd.to_numeric(turnover, errors="coerce").dropna()
    if clean_turnover.empty:
        return _save_message_figure("Turnover", output_path)
    rolling_avg = clean_turnover.rolling(rolling_window).mean()
    fig, ax = plt.subplots(figsize=(12, 4.5))
    ax.bar(clean_turnover.index, clean_turnover.values, color=COLORS["benchmark"], alpha=0.35, label="Daily Turnover")
    ax.plot(rolling_avg.index, rolling_avg.values, color=COLORS["equity"], linewidth=1.8, label=f"{rolling_window}-Day Average")
    ax.set_title("Turnover")
    ax.set_ylabel("Turnover")
    _format_percent_axis(ax)
    _format_time_axis(ax)
    ax.legend(loc="best")
    return _finalize_figure(fig, output_path)


def plot_trade_return_distribution(trade_table: pd.DataFrame, output_path: str | Path) -> Path:
    """Save a histogram of realized trade returns."""
    if trade_table.empty or "Trade Return" not in trade_table.columns:
        return _save_message_figure("Trade Return Distribution", output_path)
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.hist(trade_table["Trade Return"], bins=25, color=COLORS["equity"], alpha=0.72, edgecolor="white")
    ax.axvline(trade_table["Trade Return"].mean(), color=COLORS["positive"], linewidth=1.8, linestyle="--", label="Mean")
    ax.set_title("Trade Return Distribution")
    ax.set_xlabel("Trade Return")
    ax.set_ylabel("Frequency")
    _format_percent_x_axis(ax)
    ax.legend(loc="best")
    return _finalize_figure(fig, output_path)


def plot_trade_duration_distribution(trade_table: pd.DataFrame, output_path: str | Path) -> Path:
    """Save a histogram of trade holding periods."""
    if trade_table.empty or "Duration" not in trade_table.columns:
        return _save_message_figure("Trade Duration Distribution", output_path)
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.hist(trade_table["Duration"], bins=min(25, max(5, len(trade_table))), color=COLORS["accent"], alpha=0.72, edgecolor="white")
    ax.set_title("Trade Duration Distribution")
    ax.set_xlabel("Holding Period (Trading Days)")
    ax.set_ylabel("Frequency")
    return _finalize_figure(fig, output_path)


def plot_hit_rate_by_month(returns: pd.Series, output_path: str | Path) -> Path:
    """Save the average monthly hit rate by calendar month."""
    monthly_hit_rate = monthly_win_rate(returns)
    if monthly_hit_rate.empty:
        return _save_message_figure("Hit Rate by Month", output_path)
    grouped = monthly_hit_rate.groupby(monthly_hit_rate.index.month).mean()
    month_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    grouped = grouped.reindex(range(1, 13))
    fig, ax = plt.subplots(figsize=(11, 4.8))
    ax.bar(month_labels, grouped.values, color=COLORS["positive"], alpha=0.8)
    ax.set_title("Hit Rate by Month")
    ax.set_ylabel("Win Rate")
    ax.set_ylim(0.0, 1.0)
    ax.yaxis.set_major_formatter(mtick.PercentFormatter(xmax=1.0))
    return _finalize_figure(fig, output_path)


def plot_profit_factor_by_year(returns: pd.Series, output_path: str | Path) -> Path:
    """Save yearly profit factor bars."""
    yearly_profit_factor = profit_factor_by_year(returns)
    if yearly_profit_factor.empty:
        return _save_message_figure("Profit Factor by Year", output_path)
    fig, ax = plt.subplots(figsize=(11, 4.8))
    ax.bar(yearly_profit_factor.index.astype(str), yearly_profit_factor.values, color=COLORS["accent"], alpha=0.85)
    ax.axhline(1.0, color=COLORS["neutral"], linewidth=1.0, linestyle="--")
    ax.set_title("Profit Factor by Year")
    ax.set_ylabel("Profit Factor")
    return _finalize_figure(fig, output_path)


def plot_regime_overlay_on_price(
    benchmark_prices: pd.Series,
    regimes: pd.Series,
    output_path: str | Path,
    title: str = "Regime Overlay on Price",
) -> Path:
    """Save a benchmark price series with regime background shading."""
    clean_prices = pd.to_numeric(benchmark_prices, errors="coerce").dropna()
    if clean_prices.empty:
        return _save_message_figure(title, output_path)
    fig, ax = plt.subplots(figsize=(12, 6))
    _add_regime_background(ax=ax, index=clean_prices.index, regimes=regimes, alpha=0.12)
    ax.plot(clean_prices.index, clean_prices.values, color=COLORS["equity"], linewidth=1.9)
    ax.set_title(title)
    ax.set_ylabel("Price")
    _format_time_axis(ax)
    legend_handles = [
        Patch(facecolor=color, alpha=0.18, edgecolor="none", label=label)
        for label, color in REGIME_COLORS.items()
    ]
    ax.legend(handles=legend_handles, loc="best")
    return _finalize_figure(fig, output_path)


def plot_regime_classification(
    benchmark_prices: pd.Series,
    regimes: pd.Series,
    output_path: str | Path,
) -> Path:
    """Backward-compatible wrapper for regime overlay on price."""
    return plot_regime_overlay_on_price(
        benchmark_prices=benchmark_prices,
        regimes=regimes,
        output_path=output_path,
        title="Benchmark Price with HMM Regime Classification",
    )


def plot_regime_frequency(regimes: pd.Series, output_path: str | Path) -> Path:
    """Save regime frequency as a percentage of sample time."""
    clean_regimes = regimes.dropna().astype(str)
    if clean_regimes.empty:
        return _save_message_figure("Regime Frequency", output_path)
    frequencies = clean_regimes.value_counts(normalize=True).sort_index()
    colors = [REGIME_COLORS.get(regime, COLORS["neutral"]) for regime in frequencies.index]
    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.bar(frequencies.index, frequencies.values, color=colors, alpha=0.85)
    ax.set_title("Regime Frequency")
    ax.set_ylabel("Share of Time")
    ax.set_ylim(0.0, 1.0)
    ax.yaxis.set_major_formatter(mtick.PercentFormatter(xmax=1.0))
    return _finalize_figure(fig, output_path)


def plot_transition_matrix(transition_matrix: pd.DataFrame, output_path: str | Path) -> Path:
    """Save an HMM transition-matrix heatmap."""
    if transition_matrix.empty:
        return _save_message_figure("Regime Transition Matrix", output_path)
    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    image = ax.imshow(transition_matrix.values, cmap="Blues", vmin=0.0, vmax=1.0)
    ax.set_title("Regime Transition Matrix")
    ax.set_xticks(range(len(transition_matrix.columns)))
    ax.set_xticklabels(transition_matrix.columns, rotation=45, ha="right")
    ax.set_yticks(range(len(transition_matrix.index)))
    ax.set_yticklabels(transition_matrix.index)

    for row in range(transition_matrix.shape[0]):
        for col in range(transition_matrix.shape[1]):
            ax.text(col, row, f"{transition_matrix.iloc[row, col]:.2f}", ha="center", va="center")

    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    return _finalize_figure(fig, output_path)


def plot_regime_duration_distribution(regimes: pd.Series, output_path: str | Path) -> Path:
    """Save the distribution of consecutive regime lengths."""
    durations = regime_duration_table(regimes)
    if durations.empty:
        return _save_message_figure("Regime Duration Distribution", output_path)
    fig, ax = plt.subplots(figsize=(10, 5))
    for regime, sample in durations.groupby("Regime"):
        ax.hist(
            sample["Duration"],
            bins=min(20, max(5, len(sample))),
            alpha=0.55,
            label=str(regime),
            color=REGIME_COLORS.get(str(regime), COLORS["neutral"]),
        )
    ax.set_title("Regime Duration Distribution")
    ax.set_xlabel("Consecutive Trading Days")
    ax.set_ylabel("Frequency")
    ax.legend(loc="best")
    return _finalize_figure(fig, output_path)


def plot_regime_specific_return_boxplots(
    returns: pd.Series,
    regimes: pd.Series,
    output_path: str | Path,
) -> Path:
    """Save return boxplots grouped by regime."""
    aligned = pd.concat([returns.rename("return"), regimes.rename("regime")], axis=1).dropna(how="any")
    if aligned.empty:
        return _save_message_figure("Regime-Specific Return Boxplots", output_path)

    grouped = [sample["return"].values for _, sample in aligned.groupby("regime")]
    labels = [str(label) for label, _ in aligned.groupby("regime")]
    fig, ax = plt.subplots(figsize=(10, 5))
    box = ax.boxplot(grouped, labels=labels, patch_artist=True)
    for patch, label in zip(box["boxes"], labels):
        patch.set_facecolor(REGIME_COLORS.get(label, COLORS["neutral"]))
        patch.set_alpha(0.55)
    ax.set_title("Regime-Specific Return Boxplots")
    ax.set_ylabel("Daily Return")
    _format_percent_axis(ax)
    return _finalize_figure(fig, output_path)


def plot_regime_specific_sharpe_ratios(
    returns: pd.Series,
    regimes: pd.Series,
    output_path: str | Path,
    periods_per_year: int = 252,
) -> Path:
    """Save Sharpe ratios computed within each regime."""
    stats_frame = regime_statistics(returns=returns, regimes=regimes, periods_per_year=periods_per_year)
    if stats_frame.empty:
        return _save_message_figure("Regime-Specific Sharpe Ratios", output_path)
    fig, ax = plt.subplots(figsize=(9, 4.8))
    colors = [REGIME_COLORS.get(regime, COLORS["neutral"]) for regime in stats_frame.index]
    ax.bar(stats_frame.index.astype(str), stats_frame["Sharpe Ratio"], color=colors, alpha=0.85)
    ax.axhline(0.0, color="#0f172a", linewidth=0.9)
    ax.set_title("Regime-Specific Sharpe Ratios")
    ax.set_ylabel("Sharpe")
    return _finalize_figure(fig, output_path)


def plot_strategy_performance_by_regime(
    strategy_returns: pd.DataFrame,
    regimes: pd.Series,
    output_path: str | Path,
    periods_per_year: int = 252,
) -> Path:
    """Save grouped strategy performance metrics by regime."""
    statistics_frame = strategy_statistics_by_regime(
        strategy_returns=strategy_returns,
        regimes=regimes,
        periods_per_year=periods_per_year,
    )
    if statistics_frame.empty:
        return _save_message_figure("Strategy Performance by Regime", output_path)

    statistics_frame = statistics_frame.reset_index()
    statistics_frame = statistics_frame[statistics_frame["Regime"] != "All"]
    if statistics_frame.empty:
        return _save_message_figure("Strategy Performance by Regime", output_path)

    metrics = ["Mean Return", "Sharpe Ratio", "Annualized Volatility"]
    fig, axes = plt.subplots(nrows=3, ncols=1, figsize=(12, 11), sharex=True)
    regimes_sorted = sorted(statistics_frame["Regime"].unique())
    strategies_sorted = list(strategy_returns.columns)
    x_positions = np.arange(len(regimes_sorted))
    width = 0.75 / max(1, len(strategies_sorted))

    for ax, metric in zip(axes, metrics):
        pivot = statistics_frame.pivot(index="Regime", columns="Strategy", values=metric).reindex(
            index=regimes_sorted,
            columns=strategies_sorted,
        )
        for index, strategy in enumerate(pivot.columns):
            offset = (index - (len(pivot.columns) - 1) / 2.0) * width
            ax.bar(x_positions + offset, pivot[strategy].values, width=width, label=strategy if metric == metrics[0] else None)
        ax.set_title(metric)
        if metric != "Sharpe Ratio":
            _format_percent_axis(ax)
        ax.axhline(0.0, color="#0f172a", linewidth=0.8)

    axes[-1].set_xticks(x_positions)
    axes[-1].set_xticklabels(regimes_sorted)
    axes[0].legend(loc="best", ncol=min(3, len(strategies_sorted)))
    fig.suptitle("Strategy Performance by Regime", y=1.02, fontsize=15, fontweight="bold")
    return _finalize_figure(fig, output_path)


def plot_dynamic_strategy_weights(strategy_weights: pd.DataFrame, output_path: str | Path) -> Path:
    """Save a stacked area chart of dynamic strategy allocations."""
    clean_weights = strategy_weights.dropna(how="all")
    if clean_weights.empty:
        return _save_message_figure("Dynamic Strategy Weights", output_path)
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.stackplot(clean_weights.index, clean_weights.T.values, labels=list(clean_weights.columns), alpha=0.85)
    ax.set_title("Dynamic Strategy Weight Allocation")
    ax.set_ylabel("Weight")
    ax.set_ylim(0.0, 1.0)
    ax.yaxis.set_major_formatter(mtick.PercentFormatter(xmax=1.0))
    _format_time_axis(ax)
    ax.legend(loc="upper left", ncol=min(3, len(clean_weights.columns)))
    return _finalize_figure(fig, output_path)


def plot_contribution_to_return(
    strategy_returns: pd.DataFrame,
    strategy_weights: pd.DataFrame,
    output_path: str | Path,
) -> Path:
    """Save cumulative contribution to return for each strategy."""
    if strategy_returns.dropna(how="all").empty or strategy_weights.dropna(how="all").empty:
        return _save_message_figure("Contribution to Return", output_path)

    contributions = strategy_returns.reindex_like(strategy_weights).fillna(0.0) * strategy_weights.fillna(0.0)
    cumulative_contributions = contributions.cumsum()
    fig, ax = plt.subplots(figsize=(12, 5))
    for strategy in cumulative_contributions.columns:
        ax.plot(
            cumulative_contributions.index,
            cumulative_contributions[strategy],
            linewidth=1.6,
            label=strategy.replace("_", " ").title(),
        )
    ax.set_title("Cumulative Contribution to Return")
    ax.set_ylabel("Cumulative Contribution")
    _format_percent_axis(ax)
    _format_time_axis(ax)
    ax.legend(loc="best")
    return _finalize_figure(fig, output_path)


def plot_risk_contribution(
    strategy_returns: pd.DataFrame,
    strategy_weights: pd.DataFrame,
    output_path: str | Path,
    periods_per_year: int = 252,
) -> Path:
    """Save volatility contribution by strategy."""
    contributions = volatility_contribution(
        strategy_returns=strategy_returns,
        strategy_weights=strategy_weights,
        periods_per_year=periods_per_year,
    )
    if contributions.empty:
        return _save_message_figure("Risk Contribution", output_path)
    percentage_contributions = contributions.div(contributions.sum()).replace([np.inf, -np.inf], np.nan)
    fig, ax = plt.subplots(figsize=(10, 4.8))
    ax.bar(
        percentage_contributions.index.astype(str),
        percentage_contributions.values,
        color=COLORS["accent"],
        alpha=0.85,
    )
    ax.set_title("Volatility Contribution by Strategy")
    ax.set_ylabel("Share of Portfolio Volatility")
    ax.yaxis.set_major_formatter(mtick.PercentFormatter(xmax=1.0))
    return _finalize_figure(fig, output_path)


def plot_correlation_heatmap(strategy_returns: pd.DataFrame, output_path: str | Path) -> Path:
    """Save a strategy correlation heatmap."""
    clean_returns = strategy_returns.dropna(how="all")
    if clean_returns.empty:
        return _save_message_figure("Strategy Correlation Heatmap", output_path)
    correlation = clean_returns.corr()
    fig, ax = plt.subplots(figsize=(7, 6))
    image = ax.imshow(correlation.values, cmap="coolwarm", vmin=-1.0, vmax=1.0)
    ax.set_title("Strategy Correlation Heatmap")
    ax.set_xticks(range(len(correlation.columns)))
    ax.set_xticklabels(correlation.columns, rotation=45, ha="right")
    ax.set_yticks(range(len(correlation.index)))
    ax.set_yticklabels(correlation.index)
    for row in range(correlation.shape[0]):
        for col in range(correlation.shape[1]):
            ax.text(col, row, f"{correlation.iloc[row, col]:.2f}", ha="center", va="center")
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    return _finalize_figure(fig, output_path)


def plot_rolling_correlation_matrix(
    strategy_returns: pd.DataFrame,
    output_path: str | Path,
    window: int = 63,
) -> Path:
    """Save rolling pairwise correlations between strategies."""
    clean_returns = strategy_returns.dropna(how="all")
    pairs = list(combinations(clean_returns.columns, 2))
    if clean_returns.empty or not pairs:
        return _save_message_figure("Rolling Correlation Matrix", output_path)

    fig, axes = plt.subplots(nrows=len(pairs), ncols=1, figsize=(12, max(4.5, 3.2 * len(pairs))), sharex=True)
    if len(pairs) == 1:
        axes = [axes]

    for ax, (left, right) in zip(axes, pairs):
        rolling_corr = clean_returns[left].rolling(window).corr(clean_returns[right])
        ax.plot(rolling_corr.index, rolling_corr.values, color=COLORS["benchmark"], linewidth=1.6)
        ax.axhline(0.0, color="#0f172a", linewidth=0.8, linestyle="--")
        ax.set_title(f"{left} vs {right}")
        ax.set_ylim(-1.0, 1.0)
        _format_time_axis(ax)

    fig.suptitle(f"Rolling {window}-Day Strategy Correlations", y=1.02, fontsize=15, fontweight="bold")
    return _finalize_figure(fig, output_path)


def plot_spread_time_series(spread: pd.Series, output_path: str | Path) -> Path:
    """Save the pairs-trading spread time series."""
    clean_spread = pd.to_numeric(spread, errors="coerce").dropna()
    if clean_spread.empty:
        return _save_message_figure("Spread Time Series", output_path)
    fig, ax = plt.subplots(figsize=(12, 4.8))
    ax.plot(clean_spread.index, clean_spread.values, color=COLORS["equity"], linewidth=1.6)
    ax.axhline(clean_spread.mean(), color=COLORS["neutral"], linestyle="--", linewidth=1.0, label="Mean")
    ax.set_title("Spread Time Series")
    ax.set_ylabel("Spread")
    _format_time_axis(ax)
    ax.legend(loc="best")
    return _finalize_figure(fig, output_path)


def plot_spread_zscore(
    spread_zscore: pd.Series,
    output_path: str | Path,
    entry_threshold: float = 2.0,
    exit_threshold: float = 0.5,
) -> Path:
    """Save spread z-score with entry and exit thresholds."""
    clean_zscore = pd.to_numeric(spread_zscore, errors="coerce").dropna()
    if clean_zscore.empty:
        return _save_message_figure("Spread Z-Score", output_path)
    fig, ax = plt.subplots(figsize=(12, 4.8))
    ax.plot(clean_zscore.index, clean_zscore.values, color=COLORS["benchmark"], linewidth=1.6)
    ax.axhline(entry_threshold, color=COLORS["negative"], linestyle="--", linewidth=1.0, label="Entry Threshold")
    ax.axhline(-entry_threshold, color=COLORS["positive"], linestyle="--", linewidth=1.0)
    ax.axhline(exit_threshold, color=COLORS["neutral"], linestyle=":", linewidth=1.0, label="Exit Threshold")
    ax.axhline(-exit_threshold, color=COLORS["neutral"], linestyle=":", linewidth=1.0)
    ax.axhline(0.0, color="#0f172a", linewidth=0.8)
    ax.set_title("Spread Z-Score with Entry and Exit Thresholds")
    ax.set_ylabel("Z-Score")
    _format_time_axis(ax)
    ax.legend(loc="best")
    return _finalize_figure(fig, output_path)


def plot_hedge_ratio(hedge_ratio: pd.Series, output_path: str | Path) -> Path:
    """Save the rolling hedge ratio through time."""
    clean_hedge_ratio = pd.to_numeric(hedge_ratio, errors="coerce").dropna()
    if clean_hedge_ratio.empty:
        return _save_message_figure("Hedge Ratio Through Time", output_path)
    fig, ax = plt.subplots(figsize=(12, 4.8))
    ax.plot(clean_hedge_ratio.index, clean_hedge_ratio.values, color=COLORS["accent"], linewidth=1.6)
    ax.set_title("Hedge Ratio Through Time")
    ax.set_ylabel("Hedge Ratio")
    _format_time_axis(ax)
    return _finalize_figure(fig, output_path)


def plot_cointegration_test_summary(
    asset_x_prices: pd.Series,
    asset_y_prices: pd.Series,
    output_path: str | Path,
    asset_x_label: str,
    asset_y_label: str,
) -> Path:
    """Save a cointegration summary figure for the trading pair."""
    aligned = pd.concat([asset_x_prices.rename("x"), asset_y_prices.rename("y")], axis=1).dropna(how="any")
    if aligned.empty:
        return _save_message_figure("Cointegration Test Summary", output_path)

    test_statistic, p_value, critical_values = coint(aligned["y"], aligned["x"])
    normalized = aligned / aligned.iloc[0]

    fig, axes = plt.subplots(nrows=2, ncols=1, figsize=(12, 7), gridspec_kw={"height_ratios": [2.0, 1.2]})
    axes[0].plot(normalized.index, normalized["x"], label=asset_x_label, color=COLORS["benchmark"], linewidth=1.6)
    axes[0].plot(normalized.index, normalized["y"], label=asset_y_label, color=COLORS["equity"], linewidth=1.6)
    axes[0].set_title("Cointegration Test Summary")
    axes[0].set_ylabel("Normalized Price")
    axes[0].legend(loc="best")
    _format_time_axis(axes[0])

    axes[1].axis("off")
    summary_lines = [
        f"Engle-Granger Test Statistic: {test_statistic:.4f}",
        f"P-Value: {p_value:.4f}",
        f"Critical Values (1%, 5%, 10%): {critical_values[0]:.4f}, {critical_values[1]:.4f}, {critical_values[2]:.4f}",
        "Interpretation: lower p-values indicate stronger evidence of cointegration.",
    ]
    axes[1].text(0.02, 0.85, "\n".join(summary_lines), fontsize=11, va="top")
    return _finalize_figure(fig, output_path)


def plot_half_life_visualization(spread: pd.Series, output_path: str | Path) -> Path:
    """Save a half-life of mean reversion diagnostic visualization."""
    clean_spread = pd.to_numeric(spread, errors="coerce").dropna()
    if len(clean_spread) < 3:
        return _save_message_figure("Mean Reversion Half-Life", output_path)

    lagged = clean_spread.shift(1).dropna()
    delta = clean_spread.diff().dropna()
    aligned = pd.concat([lagged.rename("lagged"), delta.rename("delta")], axis=1).dropna(how="any")
    if aligned.empty:
        return _save_message_figure("Mean Reversion Half-Life", output_path)

    slope, intercept = np.polyfit(aligned["lagged"], aligned["delta"], deg=1)
    half_life = half_life_of_mean_reversion(clean_spread)
    persistence = 1.0 + slope

    fig, axes = plt.subplots(nrows=1, ncols=2, figsize=(13, 5))
    axes[0].scatter(aligned["lagged"], aligned["delta"], alpha=0.55, color=COLORS["equity"])
    regression_x = np.linspace(aligned["lagged"].min(), aligned["lagged"].max(), 100)
    regression_y = slope * regression_x + intercept
    axes[0].plot(regression_x, regression_y, color=COLORS["drawdown"], linewidth=1.8)
    axes[0].set_title("Delta Spread vs Lagged Spread")
    axes[0].set_xlabel("Lagged Spread")
    axes[0].set_ylabel("Delta Spread")

    shock_path = np.array([persistence**step for step in range(21)], dtype=float)
    axes[1].plot(range(len(shock_path)), shock_path, color=COLORS["accent"], linewidth=1.8)
    axes[1].set_title("Implied Shock Decay Path")
    axes[1].set_xlabel("Days")
    axes[1].set_ylabel("Relative Shock Size")
    annotation = "Half-Life unavailable" if pd.isna(half_life) else f"Estimated Half-Life: {half_life:.2f} days"
    axes[1].text(0.03, 0.95, annotation, transform=axes[1].transAxes, va="top")
    return _finalize_figure(fig, output_path)


def plot_monte_carlo_equity_simulations(
    returns: pd.Series,
    output_path: str | Path,
    n_simulations: int = 250,
    random_seed: int = 42,
) -> Path:
    """Save bootstrap Monte Carlo equity simulations."""
    paths = _simulate_monte_carlo_paths(returns=returns, n_simulations=n_simulations, random_seed=random_seed)
    if paths.empty:
        return _save_message_figure("Monte Carlo Equity Simulations", output_path)
    fig, ax = plt.subplots(figsize=(12, 6))
    for column in paths.columns:
        ax.plot(paths.index, paths[column], color=COLORS["equity"], alpha=0.06, linewidth=0.9)
    ax.set_title("Monte Carlo Equity Simulations")
    ax.set_xlabel("Simulation Step")
    ax.set_ylabel("Portfolio Value")
    return _finalize_figure(fig, output_path)


def plot_terminal_wealth_distribution(
    returns: pd.Series,
    output_path: str | Path,
    n_simulations: int = 1000,
    random_seed: int = 42,
) -> Path:
    """Save the simulated terminal wealth distribution."""
    paths = _simulate_monte_carlo_paths(returns=returns, n_simulations=n_simulations, random_seed=random_seed)
    if paths.empty:
        return _save_message_figure("Terminal Wealth Distribution", output_path)
    terminal_values = paths.iloc[-1]
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.hist(terminal_values, bins=40, color=COLORS["accent"], alpha=0.72, edgecolor="white")
    ax.axvline(terminal_values.mean(), color=COLORS["positive"], linestyle="--", linewidth=1.8, label="Mean")
    ax.set_title("Terminal Wealth Distribution")
    ax.set_xlabel("Terminal Wealth")
    ax.set_ylabel("Frequency")
    ax.legend(loc="best")
    return _finalize_figure(fig, output_path)


def plot_probability_of_loss(
    returns: pd.Series,
    output_path: str | Path,
    n_simulations: int = 1000,
    random_seed: int = 42,
) -> Path:
    """Save the probability of terminal loss from Monte Carlo simulations."""
    paths = _simulate_monte_carlo_paths(returns=returns, n_simulations=n_simulations, random_seed=random_seed)
    if paths.empty:
        return _save_message_figure("Probability of Loss", output_path)
    terminal_values = paths.iloc[-1]
    probability_of_loss = float((terminal_values < 1.0).mean())
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.bar(["Probability of Loss", "Probability of Gain"], [probability_of_loss, 1.0 - probability_of_loss], color=[COLORS["drawdown"], COLORS["positive"]])
    ax.set_ylim(0.0, 1.0)
    ax.yaxis.set_major_formatter(mtick.PercentFormatter(xmax=1.0))
    ax.set_title("Probability of Loss")
    return _finalize_figure(fig, output_path)


def plot_stress_test_scenarios(
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series,
    output_path: str | Path,
    benchmark_name: str = "Benchmark",
) -> Path:
    """Save scenario stress windows for major market selloffs when available."""
    scenarios = {
        "2008 Crisis": ("2008-09-01", "2009-03-31"),
        "COVID Crash": ("2020-02-01", "2020-04-30"),
        "2022 Bear": ("2022-01-01", "2022-10-31"),
    }

    fig, axes = plt.subplots(nrows=3, ncols=1, figsize=(12, 10), sharex=False)
    for ax, (scenario_name, (start_date, end_date)) in zip(axes, scenarios.items()):
        sample = pd.concat(
            [
                portfolio_returns.rename("portfolio"),
                benchmark_returns.rename("benchmark"),
            ],
            axis=1,
        ).loc[start_date:end_date].dropna(how="any")

        if sample.empty:
            ax.axis("off")
            ax.text(0.5, 0.5, f"{scenario_name}\nUnavailable in current sample.", ha="center", va="center", fontsize=12)
            continue

        portfolio_path = (1.0 + sample["portfolio"]).cumprod() - 1.0
        benchmark_path = (1.0 + sample["benchmark"]).cumprod() - 1.0
        ax.plot(portfolio_path.index, portfolio_path.values, color=COLORS["equity"], linewidth=1.8, label="Portfolio")
        ax.plot(benchmark_path.index, benchmark_path.values, color=COLORS["benchmark"], linewidth=1.6, label=benchmark_name)
        ax.set_title(scenario_name)
        ax.set_ylabel("Cumulative Return")
        _format_percent_axis(ax)
        ax.legend(loc="best")
        _format_time_axis(ax)

    fig.suptitle("Stress Test Scenarios", y=1.02, fontsize=15, fontweight="bold")
    return _finalize_figure(fig, output_path)


def plot_rolling_information_ratio(
    returns: pd.Series,
    benchmark_returns: pd.Series,
    output_path: str | Path,
    window: int = 63,
    periods_per_year: int = 252,
) -> Path:
    """Save a rolling information ratio chart."""
    metric = rolling_information_ratio(
        returns=returns,
        benchmark_returns=benchmark_returns,
        window=window,
        periods_per_year=periods_per_year,
    )
    if metric.dropna().empty:
        return _save_message_figure("Rolling Information Ratio", output_path)
    fig, ax = plt.subplots(figsize=(12, 4.5))
    ax.plot(metric.index, metric.values, color=COLORS["accent"], linewidth=1.75)
    ax.axhline(0.0, color="#0f172a", linewidth=0.9, linestyle="--")
    ax.set_title(f"Rolling {window}-Day Information Ratio")
    ax.set_ylabel("Information Ratio")
    _format_time_axis(ax)
    return _finalize_figure(fig, output_path)


def plot_tracking_error(
    returns: pd.Series,
    benchmark_returns: pd.Series,
    output_path: str | Path,
    window: int = 63,
    periods_per_year: int = 252,
) -> Path:
    """Save a rolling tracking error chart."""
    metric = rolling_tracking_error(
        returns=returns,
        benchmark_returns=benchmark_returns,
        window=window,
        periods_per_year=periods_per_year,
    )
    if metric.dropna().empty:
        return _save_message_figure("Tracking Error", output_path)
    fig, ax = plt.subplots(figsize=(12, 4.5))
    ax.plot(metric.index, metric.values, color=COLORS["benchmark"], linewidth=1.75)
    ax.set_title(f"Rolling {window}-Day Tracking Error")
    ax.set_ylabel("Tracking Error")
    _format_percent_axis(ax)
    _format_time_axis(ax)
    return _finalize_figure(fig, output_path)


def plot_active_return(
    returns: pd.Series,
    benchmark_returns: pd.Series,
    output_path: str | Path,
) -> Path:
    """Save the cumulative active return path."""
    active_returns = active_return_series(returns, benchmark_returns)
    if active_returns.dropna().empty:
        return _save_message_figure("Active Return", output_path)
    cumulative_active = active_returns.cumsum()
    fig, ax = plt.subplots(figsize=(12, 4.8))
    ax.plot(cumulative_active.index, cumulative_active.values, color=COLORS["equity"], linewidth=1.75)
    ax.axhline(0.0, color="#0f172a", linewidth=0.9)
    ax.set_title("Active Return")
    ax.set_ylabel("Cumulative Active Return")
    _format_percent_axis(ax)
    _format_time_axis(ax)
    return _finalize_figure(fig, output_path)


def plot_capture_ratios(
    returns: pd.Series,
    benchmark_returns: pd.Series,
    output_path: str | Path,
) -> Path:
    """Save up-capture and down-capture ratios."""
    ratios = calculate_capture_ratios(returns=returns, benchmark_returns=benchmark_returns)
    if ratios.dropna().empty:
        return _save_message_figure("Capture Ratios", output_path)
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.bar(ratios.index, ratios.values, color=[COLORS["positive"], COLORS["negative"]], alpha=0.85)
    ax.axhline(1.0, color=COLORS["neutral"], linestyle="--", linewidth=1.0)
    ax.set_title("Up-Capture and Down-Capture Ratios")
    ax.set_ylabel("Capture Ratio")
    return _finalize_figure(fig, output_path)


def save_interactive_dashboard(
    equity_curve: pd.Series,
    drawdown: pd.Series,
    regimes: pd.Series,
    strategy_returns: pd.DataFrame,
    output_path: str | Path,
    benchmark_returns: pd.Series | None = None,
    strategy_weights: pd.DataFrame | None = None,
) -> Path:
    """Save an interactive Plotly dashboard."""
    cumulative_strategy_returns = strategy_returns.apply(_cumulative_returns)
    aligned_regimes = _aligned_regimes(regimes, equity_curve.index)
    regime_codes = pd.Categorical(aligned_regimes).codes

    rows = 5 if strategy_weights is not None else 4
    subplot_titles = [
        "Equity Curve",
        "Drawdown",
        "Strategy Cumulative Returns",
        "Regime Codes",
    ]
    if strategy_weights is not None:
        subplot_titles.append("Strategy Weights")

    figure = make_subplots(rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.04, subplot_titles=tuple(subplot_titles))
    figure.add_trace(go.Scatter(x=equity_curve.index, y=equity_curve.values, name="Equity"), row=1, col=1)

    if benchmark_returns is not None:
        benchmark_curve = (_cumulative_returns(benchmark_returns) + 1.0).rename("benchmark_equity")
        figure.add_trace(go.Scatter(x=benchmark_curve.index, y=benchmark_curve.values, name="Benchmark", line={"color": COLORS["benchmark"]}), row=1, col=1)

    figure.add_trace(go.Scatter(x=drawdown.index, y=drawdown.values, fill="tozeroy", name="Drawdown", line={"color": COLORS["drawdown"]}), row=2, col=1)

    for column in cumulative_strategy_returns.columns:
        figure.add_trace(go.Scatter(x=cumulative_strategy_returns.index, y=cumulative_strategy_returns[column], name=column), row=3, col=1)

    figure.add_trace(go.Scatter(x=aligned_regimes.index, y=regime_codes, mode="lines", name="Regime Code", text=aligned_regimes.astype(str)), row=4, col=1)

    if strategy_weights is not None:
        for column in strategy_weights.columns:
            figure.add_trace(go.Scatter(x=strategy_weights.index, y=strategy_weights[column], stackgroup="one", name=f"{column} Weight"), row=5, col=1)

    figure.update_layout(height=1300 if strategy_weights is not None else 1100, width=1250, title_text="Institutional Regime-Aware Backtest Dashboard")

    path = Path(output_path)
    ensure_directory(path.parent)
    figure.write_html(path)
    return path


def generate_full_report(
    results: BacktestResult,
    benchmark_returns: pd.Series,
    regimes: pd.Series,
    strategy_returns: pd.DataFrame,
    output_dir: str | Path = "outputs/figures",
    reports_dir: str | Path = "outputs/reports",
    *,
    benchmark_prices: pd.Series | None = None,
    benchmark_name: str = "SPY",
    prices: pd.DataFrame | None = None,
    strategy_outputs: Mapping[str, StrategyOutput] | None = None,
    transition_matrix: pd.DataFrame | None = None,
    periods_per_year: int = 252,
    risk_free_rate: float = 0.0,
    random_seed: int = 42,
) -> FullReportArtifacts:
    """Generate a comprehensive hedge-fund-style analytics package."""
    figures_dir = ensure_directory(output_dir)
    reports_dir_path = ensure_directory(reports_dir)
    figure_paths: dict[str, Path] = {}
    report_paths: dict[str, Path] = {}

    benchmark_returns = benchmark_returns.reindex(results.portfolio_returns.index).fillna(0.0)
    strategy_weights = results.strategy_weights.reindex(strategy_returns.index).fillna(0.0)
    aligned_regimes = _aligned_regimes(regimes, results.portfolio_returns.index)

    if benchmark_prices is None:
        benchmark_prices = (1.0 + benchmark_returns.fillna(0.0)).cumprod().rename(benchmark_name)

    performance_summary = pd.concat(
        [
            calculate_performance_metrics(
                results.portfolio_returns,
                turnover=results.turnover,
                risk_free_rate=risk_free_rate,
                periods_per_year=periods_per_year,
            ).rename(lambda metric: f"Portfolio {metric}"),
            calculate_performance_metrics(
                benchmark_returns,
                risk_free_rate=risk_free_rate,
                periods_per_year=periods_per_year,
            ).rename(lambda metric: f"{benchmark_name} {metric}"),
            pd.Series(
                {
                    "Tracking Error": tracking_error(
                        results.portfolio_returns,
                        benchmark_returns,
                        periods_per_year=periods_per_year,
                    ),
                    "Information Ratio": information_ratio(
                        results.portfolio_returns,
                        benchmark_returns,
                        periods_per_year=periods_per_year,
                    ),
                    "Rolling Beta (Latest 63D)": rolling_beta(results.portfolio_returns, benchmark_returns, window=63).iloc[-1],
                    "Rolling Alpha (Latest 63D)": rolling_alpha(
                        results.portfolio_returns,
                        benchmark_returns,
                        window=63,
                        periods_per_year=periods_per_year,
                    ).iloc[-1],
                    "Up Capture": calculate_capture_ratios(results.portfolio_returns, benchmark_returns)["Up Capture"],
                    "Down Capture": calculate_capture_ratios(results.portfolio_returns, benchmark_returns)["Down Capture"],
                }
            ),
        ]
    )
    performance_summary_frame = performance_summary.rename_axis("metric").to_frame(name="value")
    report_paths["performance_summary"] = save_dataframe(
        performance_summary_frame,
        reports_dir_path / "performance_summary.csv",
    )

    drawdown_table = drawdown_periods(results.portfolio_returns, top_n=10)
    report_paths["drawdown_table"] = save_dataframe(
        drawdown_table,
        reports_dir_path / "drawdown_table.csv",
        index=False,
    )

    regime_stats = regime_statistics(
        returns=results.portfolio_returns,
        regimes=aligned_regimes,
        periods_per_year=periods_per_year,
    )
    report_paths["regime_statistics"] = save_dataframe(regime_stats, reports_dir_path / "regime_statistics.csv")

    strategy_stats = strategy_statistics_by_regime(
        strategy_returns=strategy_returns,
        regimes=aligned_regimes,
        periods_per_year=periods_per_year,
    )
    report_paths["strategy_statistics"] = save_dataframe(
        strategy_stats.reset_index(),
        reports_dir_path / "strategy_statistics.csv",
        index=False,
    )

    figure_paths["equity_curve"] = plot_equity_curve(results.equity_curve, figures_dir / "equity_curve.png")
    figure_paths["monthly_returns_heatmap"] = plot_monthly_returns_heatmap(results.portfolio_returns, figures_dir / "monthly_returns_heatmap.png")
    figure_paths["annual_returns_bar"] = plot_annual_returns_bar(results.portfolio_returns, figures_dir / "annual_returns_bar.png")
    figure_paths["rolling_volatility"] = plot_rolling_volatility(results.portfolio_returns, figures_dir / "rolling_volatility.png", periods_per_year=periods_per_year)
    figure_paths["rolling_sharpe"] = plot_rolling_sharpe(results.portfolio_returns, figures_dir / "rolling_sharpe_63d.png", periods_per_year=periods_per_year)
    figure_paths["rolling_sortino"] = plot_rolling_sortino(results.portfolio_returns, figures_dir / "rolling_sortino_63d.png", periods_per_year=periods_per_year)
    figure_paths["rolling_beta"] = plot_rolling_beta(results.portfolio_returns, benchmark_returns, figures_dir / "rolling_beta_vs_benchmark.png")
    figure_paths["rolling_alpha"] = plot_rolling_alpha(results.portfolio_returns, benchmark_returns, figures_dir / "rolling_alpha.png", periods_per_year=periods_per_year)
    figure_paths["underwater"] = plot_underwater(results.drawdown, figures_dir / "underwater_plot.png")
    figure_paths["return_distribution"] = plot_return_distribution_histogram(results.portfolio_returns, figures_dir / "return_distribution_histogram.png")
    figure_paths["qq_plot"] = plot_qq_returns(results.portfolio_returns, figures_dir / "qq_plot.png")
    figure_paths["autocorrelation"] = plot_autocorrelation(results.portfolio_returns, figures_dir / "autocorrelation_plot.png")
    figure_paths["cumulative_returns_comparison"] = plot_cumulative_returns_comparison(
        portfolio_returns=results.portfolio_returns,
        benchmark_returns=benchmark_returns,
        strategy_returns=strategy_returns,
        output_path=figures_dir / "cumulative_returns_comparison.png",
        benchmark_name=benchmark_name,
    )
    figure_paths["var_cvar_distribution"] = plot_var_cvar_distribution(results.portfolio_returns, figures_dir / "var_cvar_distribution.png")
    figure_paths["rolling_var"] = plot_rolling_var(results.portfolio_returns, figures_dir / "rolling_var_95.png")
    figure_paths["drawdown_duration"] = plot_drawdown_duration(results.drawdown, figures_dir / "drawdown_duration.png")
    figure_paths["worst_drawdown_table"] = plot_worst_drawdown_table(results.portfolio_returns, figures_dir / "worst_drawdown_table.png")
    figure_paths["position_exposure"] = plot_position_exposure(results.combined_positions, figures_dir / "position_exposure.png")
    figure_paths["turnover"] = plot_turnover(results.turnover, figures_dir / "turnover.png")
    figure_paths["hit_rate_by_month"] = plot_hit_rate_by_month(results.portfolio_returns, figures_dir / "hit_rate_by_month.png")
    figure_paths["profit_factor_by_year"] = plot_profit_factor_by_year(results.portfolio_returns, figures_dir / "profit_factor_by_year.png")
    figure_paths["regime_overlay"] = plot_regime_overlay_on_price(benchmark_prices, aligned_regimes, figures_dir / "regime_overlay_on_price.png")
    figure_paths["regime_frequency"] = plot_regime_frequency(aligned_regimes, figures_dir / "regime_frequency.png")
    if transition_matrix is not None:
        figure_paths["transition_matrix"] = plot_transition_matrix(transition_matrix, figures_dir / "transition_matrix_heatmap.png")
    figure_paths["regime_duration_distribution"] = plot_regime_duration_distribution(aligned_regimes, figures_dir / "regime_duration_distribution.png")
    figure_paths["regime_return_boxplots"] = plot_regime_specific_return_boxplots(results.portfolio_returns, aligned_regimes, figures_dir / "regime_specific_return_boxplots.png")
    figure_paths["regime_sharpe_ratios"] = plot_regime_specific_sharpe_ratios(results.portfolio_returns, aligned_regimes, figures_dir / "regime_specific_sharpe_ratios.png", periods_per_year=periods_per_year)
    figure_paths["strategy_performance_by_regime"] = plot_strategy_performance_by_regime(strategy_returns, aligned_regimes, figures_dir / "strategy_performance_by_regime.png", periods_per_year=periods_per_year)
    figure_paths["dynamic_strategy_weights"] = plot_dynamic_strategy_weights(strategy_weights, figures_dir / "dynamic_strategy_weights.png")
    figure_paths["contribution_to_return"] = plot_contribution_to_return(strategy_returns, strategy_weights, figures_dir / "contribution_to_return.png")
    figure_paths["risk_contribution"] = plot_risk_contribution(strategy_returns, strategy_weights, figures_dir / "risk_contribution.png", periods_per_year=periods_per_year)
    figure_paths["correlation_heatmap"] = plot_correlation_heatmap(strategy_returns, figures_dir / "strategy_correlation_heatmap.png")
    figure_paths["rolling_correlation_matrix"] = plot_rolling_correlation_matrix(strategy_returns, figures_dir / "rolling_correlation_matrix.png")
    figure_paths["monte_carlo_equity_simulations"] = plot_monte_carlo_equity_simulations(results.portfolio_returns, figures_dir / "monte_carlo_equity_simulations.png", random_seed=random_seed)
    figure_paths["terminal_wealth_distribution"] = plot_terminal_wealth_distribution(results.portfolio_returns, figures_dir / "terminal_wealth_distribution.png", random_seed=random_seed)
    figure_paths["probability_of_loss"] = plot_probability_of_loss(results.portfolio_returns, figures_dir / "probability_of_loss.png", random_seed=random_seed)
    figure_paths["stress_test_scenarios"] = plot_stress_test_scenarios(results.portfolio_returns, benchmark_returns, figures_dir / "stress_test_scenarios.png", benchmark_name=benchmark_name)
    figure_paths["rolling_information_ratio"] = plot_rolling_information_ratio(results.portfolio_returns, benchmark_returns, figures_dir / "rolling_information_ratio.png", periods_per_year=periods_per_year)
    figure_paths["tracking_error"] = plot_tracking_error(results.portfolio_returns, benchmark_returns, figures_dir / "tracking_error.png", periods_per_year=periods_per_year)
    figure_paths["active_return"] = plot_active_return(results.portfolio_returns, benchmark_returns, figures_dir / "active_return.png")
    figure_paths["capture_ratios"] = plot_capture_ratios(results.portfolio_returns, benchmark_returns, figures_dir / "capture_ratios.png")

    trade_table = pd.DataFrame()
    if strategy_outputs:
        trade_table = _extract_trade_table(strategy_returns=strategy_returns, strategy_outputs=strategy_outputs)
        for strategy_name, strategy_output in strategy_outputs.items():
            if prices is None:
                continue
            representative = _representative_signal_series(strategy_name, strategy_output, prices)
            if representative is None:
                continue
            price_series, signal_series, asset_label = representative
            figure_paths[f"signal_plot_{strategy_name}"] = plot_signal_plot(
                price=price_series,
                signal=signal_series,
                output_path=figures_dir / f"signal_plot_{strategy_name}.png",
                title=f"Signal Plot: {strategy_name.replace('_', ' ').title()} ({asset_label})",
                asset_label=asset_label,
            )

        if "pairs_trading" in strategy_outputs:
            pairs_output = strategy_outputs["pairs_trading"]
            diagnostics = pairs_output.diagnostics if pairs_output.diagnostics is not None else pd.DataFrame()
            metadata = pairs_output.metadata or {}
            if not diagnostics.empty:
                figure_paths["spread_time_series"] = plot_spread_time_series(diagnostics["spread"], figures_dir / "spread_time_series.png")
                figure_paths["spread_zscore"] = plot_spread_zscore(
                    diagnostics["spread_z_score"],
                    figures_dir / "spread_zscore.png",
                    entry_threshold=float(metadata.get("entry_threshold", 2.0)),
                    exit_threshold=float(metadata.get("exit_threshold", 0.5)),
                )
                figure_paths["hedge_ratio"] = plot_hedge_ratio(diagnostics["hedge_ratio"], figures_dir / "hedge_ratio_through_time.png")
                if prices is not None:
                    asset_x = str(metadata.get("asset_x", "asset_x"))
                    asset_y = str(metadata.get("asset_y", "asset_y"))
                    if asset_x in prices.columns and asset_y in prices.columns:
                        figure_paths["cointegration_test_summary"] = plot_cointegration_test_summary(
                            asset_x_prices=prices[asset_x],
                            asset_y_prices=prices[asset_y],
                            output_path=figures_dir / "cointegration_test_summary.png",
                            asset_x_label=asset_x,
                            asset_y_label=asset_y,
                        )
                figure_paths["half_life_visualization"] = plot_half_life_visualization(
                    diagnostics["spread"],
                    figures_dir / "mean_reversion_half_life.png",
                )

    figure_paths["trade_return_distribution"] = plot_trade_return_distribution(trade_table, figures_dir / "trade_return_distribution.png")
    figure_paths["trade_duration_distribution"] = plot_trade_duration_distribution(trade_table, figures_dir / "trade_duration_distribution.png")

    report_paths["interactive_dashboard"] = save_interactive_dashboard(
        equity_curve=results.equity_curve,
        drawdown=results.drawdown,
        regimes=aligned_regimes,
        strategy_returns=strategy_returns,
        strategy_weights=strategy_weights,
        benchmark_returns=benchmark_returns,
        output_path=reports_dir_path / "performance_dashboard.html",
    )

    return FullReportArtifacts(figures=figure_paths, reports=report_paths)
