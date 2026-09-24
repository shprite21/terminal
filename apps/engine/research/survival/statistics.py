"""Established diagnostics; see docs/strategy-survival.md for formulas and sources.

Daily simple net returns, zero cash hurdle, sample SD (ddof=1). No function
silently fills missing observations or treats a constant series as Sharpe zero.
"""
from itertools import combinations
import math

import numpy as np
from scipy.stats import kurtosis, norm, rankdata, skew
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests


class NeedData(ValueError):
    """A statistical precondition is absent; present N-A and this explanation."""


def sample(values, minimum=2):
    x = np.asarray(values, dtype=float)
    if x.ndim != 1 or len(x) < minimum or not np.isfinite(x).all() or (x <= -1).any():
        raise NeedData(f"Need {minimum} finite simple returns above -100%, with no missing observations")
    return x


def metrics(values, annualization=252):
    x = sample(values)
    equity = np.r_[1., np.cumprod(1 + x)]
    sd = float(x.std(ddof=1))
    return {"observations": len(x), "total_return": float(equity[-1] - 1),
            "cagr": float(equity[-1] ** (annualization / len(x)) - 1),
            "sharpe": float(x.mean() / sd * np.sqrt(annualization)) if sd > 1e-12 else None,
            "volatility": sd * np.sqrt(annualization),
            "max_drawdown": float(np.min(equity / np.maximum.accumulate(equity) - 1))}


def chronological_splits(n, train_fraction=.6, validation_fraction=.2):
    a, b = int(n * train_fraction), int(n * (train_fraction + validation_fraction))
    if not 1 < a < b - 1 < n - 2:
        raise NeedData("Three non-overlapping chronological segments need at least two observations each")
    return {"train": (0, a), "validation": (a, b), "chronological_test": (b, n)}


def walk_folds(n, train_window, test_window, mode="expanding", max_folds=8):
    """Full, disjoint forward tests only. Oldest folds retained under the explicit cap."""
    if train_window < 2 or test_window < 2 or max_folds < 1 or mode not in {"rolling", "expanding"}:
        raise ValueError("Invalid walk-forward window construction")
    return [(0 if mode == "expanding" else stop - train_window, stop, stop + test_window)
            for stop in range(train_window, n - test_window + 1, test_window)][:max_folds]


def block_bootstrap(values, *, seed=42, samples=300, block_length=10, confidence=.95,
                    annualization=252, minimum=60):
    """Circular moving-block percentile intervals. Stationary weak dependence assumed.

    Blocks retain local serial dependence; wraparound is artificial and extremes
    not observed historically cannot be generated. Paths are diagnostic, not forecasts.
    """
    x = sample(values, max(minimum, block_length * 3))
    if x.std(ddof=1) < 1e-12:
        raise NeedData("Bootstrap Sharpe needs nonzero return variance")
    rng = np.random.default_rng(seed)
    starts = rng.integers(len(x), size=(samples, math.ceil(len(x) / block_length)))
    indices = (starts[..., None] + np.arange(block_length)) % len(x)
    paths = x[indices.reshape(samples, -1)[:, :len(x)]]
    draws = [metrics(path, annualization) for path in paths]
    alpha = (1 - confidence) / 2
    intervals = {}
    distributions = {}
    for key in ("sharpe", "cagr", "total_return", "max_drawdown"):
        values = [row[key] for row in draws if row[key] is not None]
        if len(values) < samples:
            raise NeedData("Degenerate bootstrap paths: reduce block length or collect more variation")
        intervals[key] = {"low": float(np.quantile(values, alpha)),
                          "median": float(np.median(values)), "high": float(np.quantile(values, 1 - alpha)),
                          "confidence": confidence}
        distributions[key] = values
    return {"intervals": intervals, "distributions": distributions,
            "loss_probability": float(np.mean(np.prod(1 + paths, axis=1) < 1)),
            "samples": samples, "seed": seed, "block_length": block_length}


def hac_mean(values, lags=5, confidence=.95, minimum=60):
    """Intercept-only OLS with Newey-West/Bartlett HAC, asymptotic normal inference.

    H0: expected daily net return <= 0 (one-sided p). Weak stationarity, finite
    moments and sufficiently long history assumed. Bandwidth is user-configured.
    """
    x = sample(values, max(minimum, 2 * lags + 3))
    if x.std(ddof=1) < 1e-12:
        raise NeedData("HAC mean inference needs nonzero return variance")
    fit = sm.OLS(x, np.ones((len(x), 1))).fit(cov_type="HAC", cov_kwds={"maxlags": lags}, use_t=False)
    se = float(fit.bse[0])
    if not np.isfinite(se) or se <= 1e-15:
        raise NeedData("HAC long-run variance is degenerate")
    z = float(fit.params[0] / se)
    delta = float(norm.ppf((1 + confidence) / 2) * se)
    return {"daily_mean": float(x.mean()), "standard_error": se, "z": z,
            "p_one_sided": float(norm.sf(z)), "ci_low": float(x.mean() - delta),
            "ci_high": float(x.mean() + delta), "confidence": confidence, "hac_lags": lags}


def fdr(pvalues):
    """Benjamini–Yekutieli adjusted p-values, valid under arbitrary test dependence.

    Requires individually valid p-values and a complete, prespecified family;
    tracking a partial/adaptive family does not repair undisclosed research.
    """
    p = np.asarray(pvalues, float)
    if len(p) < 2 or not np.isfinite(p).all() or ((p < 0) | (p > 1)).any():
        raise NeedData("FDR needs at least two valid p-values from a disclosed test family")
    return multipletests(p, method="fdr_by")[1].tolist()


def deflated_sharpe(values, trial_sharpes, effective_trials, minimum=60):
    """Bailey–López de Prado (2014) DSR, using NON-annualized trial Sharpes.

    Expected maximum SR uses cross-trial SR sample variance and the Euler
    constant approximation. PSR denominator uses standardized third/fourth
    moments (Pearson kurtosis, not excess). IID returns and effective independent
    trials are assumptions, not inferred from a small correlated parameter grid.
    """
    x = sample(values, minimum)
    trial = np.asarray(trial_sharpes, float)
    if effective_trials is None:
        raise NeedData("DSR needs a documented effective independent trial count and IID-return assumption")
    if len(trial) < 2 or not np.isfinite(trial).all() or not 2 <= effective_trials <= len(trial):
        raise NeedData("DSR needs >=2 aligned trials; effective trials cannot exceed observed trials")
    sd = float(x.std(ddof=1))
    trial_sd = float(trial.std(ddof=1))
    if sd <= 1e-12 or trial_sd <= 1e-12:
        raise NeedData("DSR needs nondegenerate return and cross-trial Sharpe variance")
    sr = float(x.mean() / sd)
    expected_max = trial_sd * ((1 - np.euler_gamma) * norm.ppf(1 - 1 / effective_trials)
                              + np.euler_gamma * norm.ppf(1 - 1 / (effective_trials * np.e)))
    denominator = 1 - skew(x) * sr + (kurtosis(x, fisher=False) - 1) * sr**2 / 4
    if denominator <= 0 or not np.isfinite(denominator):
        raise NeedData("Invalid non-normal Sharpe sampling variance")
    return {"dsr": float(norm.cdf((sr - expected_max) * np.sqrt(len(x) - 1) / np.sqrt(denominator))),
            "daily_sharpe": sr, "expected_max_daily_sharpe": float(expected_max),
            "effective_trials": effective_trials, "observed_trials": len(trial)}


def pbo(matrix, blocks=8, minimum_per_half=60):
    """Exact CSCV on equal contiguous blocks; logit of winner's OOS rank/(N+1).

    PBO is fraction of logits <=0. Each combination selects the IS Sharpe winner.
    Stable column order resolves IS ties, OOS ties use average ranks. No temporal
    forecasting claim: symmetric partitions are retrospective search diagnostics.
    """
    x = np.asarray(matrix, float)
    if (x.ndim != 2 or x.shape[1] < 2 or blocks < 4 or blocks > 12 or blocks % 2
            or not np.isfinite(x).all() or (x <= -1).any()):
        raise NeedData("CSCV needs a finite aligned time-by-trial matrix and 4–12 even blocks")
    size = len(x) // blocks
    if size * blocks // 2 < minimum_per_half:
        raise NeedData(f"CSCV needs {minimum_per_half} observations in each half")
    if np.allclose(x, x[:, :1]):
        raise NeedData("Identical candidate paths cannot identify overfitting")
    x = x[:size * blocks].reshape(blocks, size, -1)
    logits = []
    ties = 0
    for chosen in combinations(range(blocks), blocks // 2):
        other = [i for i in range(blocks) if i not in chosen]
        train, test = x[list(chosen)].reshape(-1, x.shape[-1]), x[other].reshape(-1, x.shape[-1])
        a, b = train.std(axis=0, ddof=1), test.std(axis=0, ddof=1)
        if (a <= 1e-12).any() or (b <= 1e-12).any():
            raise NeedData("At least one CSCV candidate has zero variance in a partition")
        scores = train.mean(axis=0) / a
        ties += int(np.count_nonzero(scores == scores.max()) > 1)
        winner = int(np.argmax(scores))
        rank = rankdata(test.mean(axis=0) / b, method="average")[winner] / (x.shape[-1] + 1)
        logits.append(float(np.log(rank / (1 - rank))))
    return {"pbo": float(np.mean(np.array(logits) <= 0)), "logits": logits,
            "partitions": len(logits), "blocks": blocks, "discarded_tail_observations": len(matrix) % blocks,
            "tied_training_winners": ties}


def factor_fit(returns, factors, lags=5, confidence=.95, minimum=60):
    """OLS return attribution with HAC intervals, aligned realized factors only.

    Intercept is arithmetic daily alpha, not causal skill; no RF adjustment is
    implicit. Provider-specific excess returns must supply an explicit RF series.
    """
    x = sample(returns, minimum)
    f = np.asarray(factors, float)
    if f.ndim != 2 or len(f) != len(x) or not np.isfinite(f).all():
        raise NeedData("Factors must align exactly with finite strategy returns")
    design = np.column_stack([np.ones(len(x)), f])
    if len(x) < max(minimum, 10 * design.shape[1]) or np.linalg.matrix_rank(design) != design.shape[1]:
        raise NeedData("Factor model needs full rank and >=10 observations per coefficient")
    fit = sm.OLS(x, design).fit(cov_type="HAC", cov_kwds={"maxlags": lags}, use_t=False)
    return {"daily_alpha": float(fit.params[0]), "coefficients": fit.params[1:].tolist(),
            "confidence_intervals": fit.conf_int(alpha=1-confidence).tolist(),
            "alpha_p_two_sided": float(fit.pvalues[0]), "r_squared": float(fit.rsquared),
            "residual_volatility_daily": float(np.std(fit.resid, ddof=1)),
            "observations": len(x), "confidence": confidence}
