from __future__ import annotations

import math
from typing import Iterable

import numpy as np
import pandas as pd


TRADING_DAYS_PER_YEAR = 252


def _clean_series(series: pd.Series) -> pd.Series:
    """Return a numeric, nan-safe time series."""
    clean = pd.to_numeric(series, errors="coerce")
    return clean.replace([np.inf, -np.inf], np.nan).dropna()


def align_series(left: pd.Series, right: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Align two series to the same timestamp index."""
    aligned = pd.concat([left.rename("left"), right.rename("right")], axis=1).dropna(how="any")
    return aligned["left"], aligned["right"]


def cumulative_return(returns: pd.Series) -> float:
    """Compute cumulative return."""
    clean_returns = _clean_series(returns)
    if clean_returns.empty:
        return float("nan")
    return float((1.0 + clean_returns).prod() - 1.0)


def annualized_return(returns: pd.Series, periods_per_year: int = TRADING_DAYS_PER_YEAR) -> float:
    """Compute annualized geometric return."""
    clean_returns = _clean_series(returns)
    if clean_returns.empty:
        return float("nan")

    total_return = (1.0 + clean_returns).prod()
    years = len(clean_returns) / periods_per_year
    if years <= 0:
        return float("nan")
    return float(total_return ** (1.0 / years) - 1.0)


def annualized_volatility(returns: pd.Series, periods_per_year: int = TRADING_DAYS_PER_YEAR) -> float:
    """Compute annualized volatility."""
    clean_returns = _clean_series(returns)
    if clean_returns.empty:
        return float("nan")
    return float(clean_returns.std(ddof=0) * math.sqrt(periods_per_year))


def sharpe_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.0,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float:
    """Compute annualized Sharpe ratio."""
    clean_returns = _clean_series(returns)
    if clean_returns.empty:
        return float("nan")

    excess_returns = clean_returns - risk_free_rate / periods_per_year
    volatility = excess_returns.std(ddof=0)
    if np.isclose(volatility, 0.0):
        return float("nan")
    return float(excess_returns.mean() / volatility * math.sqrt(periods_per_year))


def _downside_deviation(excess_returns: pd.Series) -> float:
    """Compute downside deviation from an excess-return series."""
    negative_returns = np.minimum(excess_returns.to_numpy(dtype=float), 0.0)
    if negative_returns.size == 0:
        return float("nan")
    downside_deviation = math.sqrt(np.mean(np.square(negative_returns)))
    if np.isclose(downside_deviation, 0.0):
        return float("nan")
    return float(downside_deviation)


def sortino_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.0,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float:
    """Compute annualized Sortino ratio using downside deviation."""
    clean_returns = _clean_series(returns)
    if clean_returns.empty:
        return float("nan")

    excess_returns = clean_returns - risk_free_rate / periods_per_year
    downside_deviation = _downside_deviation(excess_returns)
    if pd.isna(downside_deviation):
        return float("nan")
    return float(excess_returns.mean() / downside_deviation * math.sqrt(periods_per_year))


def drawdown_series(returns: pd.Series) -> pd.Series:
    """Compute the portfolio drawdown series from returns."""
    clean_returns = pd.to_numeric(returns, errors="coerce").fillna(0.0)
    equity_curve = (1.0 + clean_returns).cumprod()
    running_peak = equity_curve.cummax()
    return (equity_curve / running_peak - 1.0).rename("drawdown")


def maximum_drawdown(returns: pd.Series) -> float:
    """Compute maximum drawdown."""
    drawdown = drawdown_series(returns)
    if drawdown.empty:
        return float("nan")
    return float(drawdown.min())


def calmar_ratio(returns: pd.Series, periods_per_year: int = TRADING_DAYS_PER_YEAR) -> float:
    """Compute Calmar ratio."""
    max_dd = maximum_drawdown(returns)
    if pd.isna(max_dd) or np.isclose(max_dd, 0.0):
        return float("nan")
    return float(annualized_return(returns, periods_per_year=periods_per_year) / abs(max_dd))


def win_rate(returns: pd.Series) -> float:
    """Compute the fraction of non-zero days that are profitable."""
    clean_returns = _clean_series(returns)
    active_returns = clean_returns[clean_returns != 0.0]
    if active_returns.empty:
        return float("nan")
    return float((active_returns > 0.0).mean())


def profit_factor(returns: pd.Series) -> float:
    """Compute profit factor as gross profits divided by gross losses."""
    clean_returns = _clean_series(returns)
    gross_profit = clean_returns[clean_returns > 0.0].sum()
    gross_loss = clean_returns[clean_returns < 0.0].sum()
    if np.isclose(gross_loss, 0.0):
        return float("nan")
    return float(gross_profit / abs(gross_loss))


def average_turnover(turnover: pd.Series | None) -> float:
    """Compute average daily turnover."""
    if turnover is None:
        return float("nan")
    clean_turnover = _clean_series(turnover)
    if clean_turnover.empty:
        return float("nan")
    return float(clean_turnover.mean())


def rolling_sharpe(
    returns: pd.Series,
    window: int = 63,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
    risk_free_rate: float = 0.0,
) -> pd.Series:
    """Compute a rolling Sharpe ratio."""
    clean_returns = pd.to_numeric(returns, errors="coerce")
    excess_returns = clean_returns - risk_free_rate / periods_per_year
    rolling_mean = excess_returns.rolling(window=window).mean()
    rolling_std = excess_returns.rolling(window=window).std(ddof=0)
    sharpe = rolling_mean.div(rolling_std.replace(0.0, np.nan)).mul(math.sqrt(periods_per_year))
    return sharpe.rename(f"rolling_sharpe_{window}")


def rolling_sortino(
    returns: pd.Series,
    window: int = 63,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
    risk_free_rate: float = 0.0,
) -> pd.Series:
    """Compute a rolling Sortino ratio."""
    clean_returns = pd.to_numeric(returns, errors="coerce")
    excess_returns = clean_returns - risk_free_rate / periods_per_year

    def _window_sortino(values: np.ndarray) -> float:
        sample = pd.Series(values).dropna()
        if sample.empty:
            return float("nan")
        downside_deviation = _downside_deviation(sample)
        if pd.isna(downside_deviation):
            return float("nan")
        return float(sample.mean() / downside_deviation * math.sqrt(periods_per_year))

    result = excess_returns.rolling(window=window).apply(_window_sortino, raw=True)
    return result.rename(f"rolling_sortino_{window}")


def rolling_volatility(
    returns: pd.Series,
    window: int = 21,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> pd.Series:
    """Compute annualized rolling volatility."""
    clean_returns = pd.to_numeric(returns, errors="coerce")
    rolling = clean_returns.rolling(window=window).std(ddof=0).mul(math.sqrt(periods_per_year))
    return rolling.rename(f"rolling_volatility_{window}")


def active_return_series(returns: pd.Series, benchmark_returns: pd.Series) -> pd.Series:
    """Compute active returns versus a benchmark."""
    portfolio, benchmark = align_series(returns, benchmark_returns)
    return (portfolio - benchmark).rename("active_return")


def tracking_error(
    returns: pd.Series,
    benchmark_returns: pd.Series,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float:
    """Compute annualized tracking error."""
    active_returns = active_return_series(returns, benchmark_returns)
    if active_returns.empty:
        return float("nan")
    return float(active_returns.std(ddof=0) * math.sqrt(periods_per_year))


def rolling_tracking_error(
    returns: pd.Series,
    benchmark_returns: pd.Series,
    window: int = 63,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> pd.Series:
    """Compute rolling annualized tracking error."""
    portfolio, benchmark = align_series(returns, benchmark_returns)
    active_returns = portfolio - benchmark
    rolling = active_returns.rolling(window=window).std(ddof=0).mul(math.sqrt(periods_per_year))
    return rolling.rename(f"rolling_tracking_error_{window}")


def information_ratio(
    returns: pd.Series,
    benchmark_returns: pd.Series,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float:
    """Compute annualized information ratio."""
    active_returns = active_return_series(returns, benchmark_returns)
    if active_returns.empty:
        return float("nan")
    tracking = active_returns.std(ddof=0)
    if np.isclose(tracking, 0.0):
        return float("nan")
    return float(active_returns.mean() / tracking * math.sqrt(periods_per_year))


def rolling_information_ratio(
    returns: pd.Series,
    benchmark_returns: pd.Series,
    window: int = 63,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> pd.Series:
    """Compute a rolling information ratio."""
    portfolio, benchmark = align_series(returns, benchmark_returns)
    active_returns = portfolio - benchmark
    rolling_mean = active_returns.rolling(window=window).mean()
    rolling_std = active_returns.rolling(window=window).std(ddof=0)
    ratio = rolling_mean.div(rolling_std.replace(0.0, np.nan)).mul(math.sqrt(periods_per_year))
    return ratio.rename(f"rolling_information_ratio_{window}")


def rolling_beta(
    returns: pd.Series,
    benchmark_returns: pd.Series,
    window: int = 63,
) -> pd.Series:
    """Compute rolling beta relative to a benchmark."""
    portfolio, benchmark = align_series(returns, benchmark_returns)
    rolling_mean_portfolio = portfolio.rolling(window=window).mean()
    rolling_mean_benchmark = benchmark.rolling(window=window).mean()
    covariance = (portfolio * benchmark).rolling(window=window).mean() - (
        rolling_mean_portfolio * rolling_mean_benchmark
    )
    benchmark_variance = benchmark.rolling(window=window).var(ddof=0).replace(0.0, np.nan)
    beta = covariance.div(benchmark_variance)
    return beta.rename(f"rolling_beta_{window}")


def rolling_alpha(
    returns: pd.Series,
    benchmark_returns: pd.Series,
    window: int = 63,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
    risk_free_rate: float = 0.0,
) -> pd.Series:
    """Compute rolling annualized CAPM alpha."""
    portfolio, benchmark = align_series(returns, benchmark_returns)
    risk_free_daily = risk_free_rate / periods_per_year
    beta = rolling_beta(portfolio, benchmark, window=window)
    mean_portfolio = portfolio.rolling(window=window).mean() - risk_free_daily
    mean_benchmark = benchmark.rolling(window=window).mean() - risk_free_daily
    alpha = (mean_portfolio - beta * mean_benchmark).mul(periods_per_year)
    return alpha.rename(f"rolling_alpha_{window}")


def value_at_risk(returns: pd.Series, confidence_level: float = 0.95) -> float:
    """Compute historical Value at Risk at a specified confidence level."""
    clean_returns = _clean_series(returns)
    if clean_returns.empty:
        return float("nan")
    return float(clean_returns.quantile(1.0 - confidence_level))


def conditional_value_at_risk(returns: pd.Series, confidence_level: float = 0.95) -> float:
    """Compute historical Conditional Value at Risk at a specified confidence level."""
    clean_returns = _clean_series(returns)
    if clean_returns.empty:
        return float("nan")
    var_threshold = value_at_risk(clean_returns, confidence_level=confidence_level)
    tail_losses = clean_returns[clean_returns <= var_threshold]
    if tail_losses.empty:
        return float("nan")
    return float(tail_losses.mean())


def rolling_value_at_risk(
    returns: pd.Series,
    window: int = 63,
    confidence_level: float = 0.95,
) -> pd.Series:
    """Compute rolling historical Value at Risk."""
    clean_returns = pd.to_numeric(returns, errors="coerce")
    var = clean_returns.rolling(window=window).quantile(1.0 - confidence_level)
    confidence_label = int(confidence_level * 100)
    return var.rename(f"rolling_var_{confidence_label}_{window}")


def monthly_return_table(returns: pd.Series) -> pd.DataFrame:
    """Pivot monthly compounded returns into a year-by-month table."""
    clean_returns = _clean_series(returns)
    if clean_returns.empty:
        return pd.DataFrame()

    monthly_returns = (1.0 + clean_returns).resample("ME").prod() - 1.0
    monthly_frame = monthly_returns.to_frame(name="return")
    monthly_frame["year"] = monthly_frame.index.year
    monthly_frame["month"] = monthly_frame.index.month

    pivot = monthly_frame.pivot(index="year", columns="month", values="return")
    pivot = pivot.reindex(columns=range(1, 13))
    pivot.columns = [
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ]

    annual_total = (1.0 + clean_returns).resample("YE").prod() - 1.0
    pivot["Annual Total"] = annual_total.reindex(pd.to_datetime(pivot.index.astype(str) + "-12-31")).to_numpy()
    pivot.index.name = "Year"
    return pivot.sort_index()


def annual_return_series(returns: pd.Series) -> pd.Series:
    """Compute yearly compounded returns."""
    clean_returns = _clean_series(returns)
    if clean_returns.empty:
        return pd.Series(dtype=float, name="annual_return")
    annual = (1.0 + clean_returns).resample("YE").prod() - 1.0
    annual.index = annual.index.year
    annual.name = "annual_return"
    annual.index.name = "Year"
    return annual


def drawdown_periods(returns: pd.Series, top_n: int | None = None) -> pd.DataFrame:
    """Extract drawdown periods sorted from worst to best."""
    clean_returns = pd.to_numeric(returns, errors="coerce").fillna(0.0)
    if clean_returns.empty:
        return pd.DataFrame(
            columns=["Start Date", "Trough Date", "Recovery Date", "Depth", "Duration", "Recovery Days"]
        )

    equity_curve = (1.0 + clean_returns).cumprod()
    drawdown = equity_curve.div(equity_curve.cummax()) - 1.0
    index_positions = {timestamp: position for position, timestamp in enumerate(drawdown.index)}

    periods: list[dict[str, object]] = []
    peak_date = drawdown.index[0]
    in_drawdown = False
    start_date = drawdown.index[0]
    trough_date = drawdown.index[0]
    trough_depth = 0.0

    for timestamp, depth in drawdown.items():
        if np.isclose(depth, 0.0):
            if in_drawdown:
                recovery_days = index_positions[timestamp] - index_positions[trough_date]
                duration = index_positions[timestamp] - index_positions[start_date]
                periods.append(
                    {
                        "Start Date": start_date,
                        "Trough Date": trough_date,
                        "Recovery Date": timestamp,
                        "Depth": trough_depth,
                        "Duration": duration,
                        "Recovery Days": recovery_days,
                    }
                )
                in_drawdown = False
            peak_date = timestamp
            continue

        if not in_drawdown:
            in_drawdown = True
            start_date = peak_date
            trough_date = timestamp
            trough_depth = float(depth)
        elif depth < trough_depth:
            trough_date = timestamp
            trough_depth = float(depth)

    if in_drawdown:
        last_timestamp = drawdown.index[-1]
        periods.append(
            {
                "Start Date": start_date,
                "Trough Date": trough_date,
                "Recovery Date": pd.NaT,
                "Depth": trough_depth,
                "Duration": index_positions[last_timestamp] - index_positions[start_date],
                "Recovery Days": np.nan,
            }
        )

    table = pd.DataFrame(periods)
    if table.empty:
        return table

    table = table.sort_values(by="Depth").reset_index(drop=True)
    if top_n is not None:
        table = table.head(top_n).copy()
    return table


def drawdown_duration_series(drawdown: pd.Series) -> pd.Series:
    """Compute the current drawdown duration in bars."""
    clean_drawdown = pd.to_numeric(drawdown, errors="coerce").fillna(0.0)
    durations: list[int] = []
    current_duration = 0
    for value in clean_drawdown:
        if value < 0:
            current_duration += 1
        else:
            current_duration = 0
        durations.append(current_duration)
    return pd.Series(durations, index=clean_drawdown.index, name="drawdown_duration")


def regime_duration_table(regimes: pd.Series) -> pd.DataFrame:
    """Return consecutive regime runs with start, end, and duration."""
    clean_regimes = regimes.dropna()
    if clean_regimes.empty:
        return pd.DataFrame(columns=["Regime", "Start Date", "End Date", "Duration"])

    groups = (clean_regimes != clean_regimes.shift()).cumsum()
    rows: list[dict[str, object]] = []
    for _, run in clean_regimes.groupby(groups):
        rows.append(
            {
                "Regime": run.iloc[0],
                "Start Date": run.index[0],
                "End Date": run.index[-1],
                "Duration": int(len(run)),
            }
        )
    return pd.DataFrame(rows)


def monthly_win_rate(returns: pd.Series) -> pd.Series:
    """Compute monthly win rate from daily returns."""
    clean_returns = _clean_series(returns)
    if clean_returns.empty:
        return pd.Series(dtype=float, name="monthly_win_rate")
    monthly = clean_returns.resample("ME").apply(lambda sample: float((sample > 0.0).mean()) if len(sample) else np.nan)
    return monthly.rename("monthly_win_rate")


def profit_factor_by_year(returns: pd.Series) -> pd.Series:
    """Compute yearly profit factor."""
    clean_returns = _clean_series(returns)
    if clean_returns.empty:
        return pd.Series(dtype=float, name="profit_factor")
    yearly = clean_returns.resample("YE").apply(profit_factor)
    yearly.index = yearly.index.year
    yearly.index.name = "Year"
    return yearly.rename("profit_factor")


def calculate_capture_ratios(returns: pd.Series, benchmark_returns: pd.Series) -> pd.Series:
    """Compute up-capture and down-capture ratios."""
    portfolio, benchmark = align_series(returns, benchmark_returns)

    def _capture(mask: pd.Series) -> float:
        portfolio_slice = portfolio[mask]
        benchmark_slice = benchmark[mask]
        if portfolio_slice.empty or benchmark_slice.empty:
            return float("nan")
        benchmark_total = (1.0 + benchmark_slice).prod() - 1.0
        if np.isclose(benchmark_total, 0.0):
            return float("nan")
        portfolio_total = (1.0 + portfolio_slice).prod() - 1.0
        return float(portfolio_total / benchmark_total)

    up_capture = _capture(benchmark > 0.0)
    down_capture = _capture(benchmark < 0.0)
    return pd.Series({"Up Capture": up_capture, "Down Capture": down_capture}, name="capture_ratio")


def regime_statistics(
    returns: pd.Series,
    regimes: pd.Series,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> pd.DataFrame:
    """Summarize performance and persistence statistics by regime."""
    aligned = pd.concat([returns.rename("returns"), regimes.rename("regime")], axis=1).dropna(how="any")
    if aligned.empty:
        return pd.DataFrame()
    portfolio = aligned["returns"]
    aligned_regimes = aligned["regime"].astype(str)

    durations = regime_duration_table(aligned_regimes)
    duration_summary = durations.groupby("Regime")["Duration"].agg(["mean", "median", "max"]).rename(
        columns={
            "mean": "Average Duration",
            "median": "Median Duration",
            "max": "Max Duration",
        }
    )

    rows: list[dict[str, object]] = []
    for regime, sample in portfolio.groupby(aligned_regimes):
        rows.append(
            {
                "Regime": regime,
                "Observations": int(len(sample)),
                "Frequency": float(len(sample) / len(portfolio)),
                "Mean Return": float(sample.mean()),
                "Annualized Return": annualized_return(sample, periods_per_year=periods_per_year),
                "Annualized Volatility": annualized_volatility(sample, periods_per_year=periods_per_year),
                "Sharpe Ratio": sharpe_ratio(sample, periods_per_year=periods_per_year),
            }
        )

    stats = pd.DataFrame(rows).set_index("Regime").sort_index()
    if not duration_summary.empty:
        stats = stats.join(duration_summary, how="left")
    return stats


def strategy_statistics_by_regime(
    strategy_returns: pd.DataFrame,
    regimes: pd.Series,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> pd.DataFrame:
    """Compute per-strategy statistics split by regime."""
    if strategy_returns.empty:
        return pd.DataFrame()

    aligned = strategy_returns.join(regimes.rename("regime"), how="inner").dropna(subset=["regime"])
    rows: list[dict[str, object]] = []
    for strategy in strategy_returns.columns:
        overall_sample = aligned[strategy].dropna()
        if not overall_sample.empty:
            rows.append(
                {
                    "Strategy": strategy,
                    "Regime": "All",
                    "Mean Return": float(overall_sample.mean()),
                    "Annualized Return": annualized_return(overall_sample, periods_per_year=periods_per_year),
                    "Annualized Volatility": annualized_volatility(overall_sample, periods_per_year=periods_per_year),
                    "Sharpe Ratio": sharpe_ratio(overall_sample, periods_per_year=periods_per_year),
                    "Win Rate": win_rate(overall_sample),
                    "Profit Factor": profit_factor(overall_sample),
                }
            )

        for regime, sample in aligned.groupby("regime")[strategy]:
            sample = sample.dropna()
            if sample.empty:
                continue
            rows.append(
                {
                    "Strategy": strategy,
                    "Regime": regime,
                    "Mean Return": float(sample.mean()),
                    "Annualized Return": annualized_return(sample, periods_per_year=periods_per_year),
                    "Annualized Volatility": annualized_volatility(sample, periods_per_year=periods_per_year),
                    "Sharpe Ratio": sharpe_ratio(sample, periods_per_year=periods_per_year),
                    "Win Rate": win_rate(sample),
                    "Profit Factor": profit_factor(sample),
                }
            )

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).set_index(["Strategy", "Regime"]).sort_index()


def volatility_contribution(
    strategy_returns: pd.DataFrame,
    strategy_weights: pd.DataFrame | None = None,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> pd.Series:
    """Estimate volatility contribution by strategy from the covariance matrix."""
    clean_returns = strategy_returns.dropna(how="all")
    if clean_returns.empty:
        return pd.Series(dtype=float, name="volatility_contribution")

    covariance = clean_returns.fillna(0.0).cov(ddof=0) * periods_per_year
    strategy_names = list(covariance.columns)

    if strategy_weights is None or strategy_weights.empty:
        weights = pd.Series(1.0 / len(strategy_names), index=strategy_names)
    else:
        weights = strategy_weights.reindex(columns=strategy_names).fillna(0.0).mean()
        weight_sum = weights.sum()
        if np.isclose(weight_sum, 0.0):
            weights = pd.Series(1.0 / len(strategy_names), index=strategy_names)
        else:
            weights = weights / weight_sum

    covariance_matrix = covariance.to_numpy(dtype=float)
    weight_vector = weights.to_numpy(dtype=float)
    portfolio_volatility = float(np.sqrt(weight_vector @ covariance_matrix @ weight_vector))
    if np.isclose(portfolio_volatility, 0.0):
        return pd.Series(0.0, index=strategy_names, name="volatility_contribution")

    marginal_contribution = covariance_matrix @ weight_vector / portfolio_volatility
    contribution = weight_vector * marginal_contribution
    return pd.Series(contribution, index=strategy_names, name="volatility_contribution")


def half_life_of_mean_reversion(spread: pd.Series) -> float:
    """Estimate mean-reversion half-life from a spread series."""
    clean_spread = _clean_series(spread)
    if len(clean_spread) < 3:
        return float("nan")

    lagged = clean_spread.shift(1).dropna()
    delta = clean_spread.diff().dropna()
    aligned_lagged, aligned_delta = align_series(lagged, delta)
    if aligned_lagged.empty:
        return float("nan")

    x_values = aligned_lagged.to_numpy(dtype=float)
    y_values = aligned_delta.to_numpy(dtype=float)
    slope, intercept = np.polyfit(x_values, y_values, deg=1)
    if slope >= 0 or np.isclose(slope, 0.0):
        return float("nan")
    return float(-math.log(2.0) / slope)


def calculate_performance_metrics(
    returns: pd.Series,
    turnover: pd.Series | None = None,
    risk_free_rate: float = 0.0,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> pd.Series:
    """Compute institutional-style portfolio performance metrics."""
    metrics = {
        "Cumulative Return": cumulative_return(returns),
        "Annualized Return": annualized_return(returns, periods_per_year=periods_per_year),
        "Annualized Volatility": annualized_volatility(returns, periods_per_year=periods_per_year),
        "Sharpe Ratio": sharpe_ratio(
            returns,
            risk_free_rate=risk_free_rate,
            periods_per_year=periods_per_year,
        ),
        "Sortino Ratio": sortino_ratio(
            returns,
            risk_free_rate=risk_free_rate,
            periods_per_year=periods_per_year,
        ),
        "Maximum Drawdown": maximum_drawdown(returns),
        "Calmar Ratio": calmar_ratio(returns, periods_per_year=periods_per_year),
        "Win Rate": win_rate(returns),
        "Profit Factor": profit_factor(returns),
        "Average Turnover": average_turnover(turnover),
        "VaR 95": value_at_risk(returns, confidence_level=0.95),
        "CVaR 95": conditional_value_at_risk(returns, confidence_level=0.95),
        "VaR 99": value_at_risk(returns, confidence_level=0.99),
        "CVaR 99": conditional_value_at_risk(returns, confidence_level=0.99),
    }
    return pd.Series(metrics, name="value")
