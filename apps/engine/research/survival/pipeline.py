"""18 independently dispatched layers over Q's existing research/backtest engines.

No strategy fitting receives final-test data. Legacy experiments are explicitly
retrospective: this adapter cannot certify their already-seen history as true OOS.
"""
from dataclasses import dataclass, field, replace
from typing import Callable, Protocol

import numpy as np
import pandas as pd

from backtesting import VectorizedBacktester, WalkForwardConfig, WalkForwardValidator
from data.models import MarketDataBundle
from data.validation import DataQualityConfig, MarketDataQualityValidator
from evidence.storage import digest
from research.workspace import ResearchRequest, clean_json, pipeline_for, rows, subset_bundle
from strategies.base import StrategySignal
from .execution import execution_stress
from .methods import method
from .models import LayerResult, SurvivalConfig, VERSION, apply_gates, summarize
from .statistics import (NeedData, block_bootstrap, chronological_splits, deflated_sharpe,
                         factor_fit, fdr, hac_mean, metrics, pbo, walk_folds)


def strategy_key(request):
    values = request.model_dump()
    for key in ('name', 'hypothesis', 'snapshot_run_id', 'min_oos_sharpe', 'train_window', 'test_window'):
        values.pop(key, None)
    return digest(values)


class FactorProvider(Protocol):
    """Return realized factor returns, names and source/version for exact dates.

    Attribution only; these contemporaneous factors must never feed signals.
    """
    def __call__(self, dates: pd.Index) -> tuple[pd.DataFrame, dict]: ...


@dataclass
class Context:
    request: ResearchRequest
    bundle: MarketDataBundle
    config: SurvivalConfig
    experiment_id: str
    provenance: dict
    peers: dict[str, pd.Series] = field(default_factory=dict)
    prior_trials: list[dict] = field(default_factory=list)
    paper: dict | None = None
    factor_provider: FactorProvider | None = None
    filtered_regimes: pd.Series | None = None
    regime_provenance: dict | None = None
    trial_sink: Callable = lambda trial: None
    cache: dict = field(default_factory=dict)

    @property
    def prices(self):
        return self.bundle.close()

    @property
    def evaluation(self):
        return self.prices.index[max(126, max(s.lookback for s in self.request.sleeves) + 2):]

    @property
    def splits(self):
        return chronological_splits(len(self.evaluation), self.config.train_fraction, self.config.validation_fraction)

    @property
    def base(self):
        if 'base' not in self.cache:
            self.cache['base'] = pipeline_for(self.request).run(self.bundle)
        return self.cache['base']

    @property
    def returns(self):
        return self.base.backtest.returns.loc[self.evaluation]

    def stats(self, series):
        return metrics(series, self.config.annualization)

    def result(self, layer_id, metrics=None, diagnostics=None, reasons=None, status="PASS", hard=False):
        return LayerResult(**method(layer_id), status=status, metrics=clean_json(metrics or {}),
                           diagnostics=clean_json(diagnostics or {}), reasons=reasons or [], hard_failure=hard)


def integrity(c):
    failures, warnings, symbols = [], [], []
    reference = None
    for symbol, frame in c.bundle.ohlcv.items():
        missing = [f for f in ('Open', 'High', 'Low', 'Close', 'Volume') if f not in frame]
        if missing:
            failures.append(f"{symbol}: missing fields {missing}")
            continue
        if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
            failures.append(f"{symbol}: duplicate or unordered timestamps")
        if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.isna().any():
            failures.append(f"{symbol}: invalid date index")
        if reference is not None and not frame.index.equals(reference):
            failures.append(f"{symbol}: missing/misaligned sessions; no forward-fill repair permitted")
        reference = frame.index
        columns = ['Open', 'High', 'Low', 'Close'] + (['Adj Close'] if 'Adj Close' in frame else [])
        values = frame[columns].to_numpy(float)
        if not np.isfinite(values).all() or (values <= 0).any():
            failures.append(f"{symbol}: missing/nonpositive/nonfinite prices")
        if (frame.High < frame.Low).any() or (frame.Close > frame.High).any() or (frame.Close < frame.Low).any():
            failures.append(f"{symbol}: inconsistent high/low/close")
        if ((frame.Open > frame.High) | (frame.Open < frame.Low)).any():
            warnings.append(f"{symbol}: open outside high/low; inspect source adjustment consistency")
        if frame.Volume.isna().any() or not np.isfinite(frame.Volume).all() or (frame.Volume < 0).any():
            warnings.append(f"{symbol}: invalid volume; capacity/execution layer unavailable")
        symbols.append({"symbol": symbol, "rows": len(frame), "duplicate_timestamps": int(frame.index.duplicated().sum())})
    if not c.bundle.ohlcv:
        failures.append("No OHLCV observations")
    if failures:
        return c.result(1, {"integrity_errors": len(failures)}, {"symbols": symbols}, failures + warnings, "FAIL", True)
    quality = MarketDataQualityValidator(DataQualityConfig(stale_days=c.config.stale_bars, split_ratio_threshold=c.config.gap_warning)).validate(c.bundle.ohlcv)
    count = len(quality.stale_prices) + len(quality.outliers) + len(quality.adjustment_warnings)
    if count:
        warnings.append(f"{count} stale-price/outlier/adjustment flags; inspect raw observations")
    benchmark = c.bundle.benchmark
    if benchmark is not None and (benchmark.index.has_duplicates or not benchmark.index.is_monotonic_increasing or not benchmark.index.equals(reference)
                                  or not np.isfinite(benchmark['Close']).all() or (benchmark['Close'] <= 0).any()):
        failures.append("Benchmark is missing, nonfinite, nonpositive or misaligned")
    if len(c.evaluation) < 6:
        failures.append("Insufficient observations after common signal warmup")
    checks = []
    if not failures:
        # Independent prefix reruns detect full-sample normalization, future labels,
        # feature backfills and future-dependent signal implementations where sampled.
        ends = sorted(set([len(c.prices) // 2] + [len(c.prices) - len(c.evaluation) + stop for _, stop in c.splits.values() if stop < len(c.evaluation)]))
        full = c.base.weights
        for stop in ends:
            prefix = pipeline_for(c.request).run(subset_bundle(c.bundle, c.prices.index[:stop])).weights
            error = float(np.max(np.abs(full.iloc[:stop].to_numpy() - prefix.to_numpy())))
            checks.append({"prefix_end": str(prefix.index[-1]), "max_signal_difference": error})
            if not np.isfinite(error) or error > 1e-10:
                failures.append(f"Signal changes when future bars are removed at {prefix.index[-1]}")
        if pipeline_for(c.request).backtest_config.execution_lag < 1:
            failures.append("Signals must execute no earlier than the next eligible bar")
    warnings += ["Archived history has already been examined; temporal splitting cannot restore untouched OOS.",
                 "PIT constituent/delisting ledger unavailable: survivorship bias is not cleared.",
                 "Exchange-session completeness and corporate-action correctness need verified calendars/ledgers."]
    if c.request.data_mode in {'synthetic', 'demo'}:
        warnings.append("SYNTHETIC fixture: mechanics only, not empirical investment evidence")
    return c.result(1, {"integrity_errors": len(failures), "quality_flags": count, "prefix_checks": len(checks)},
                    {"symbols": symbols, "prefix_checks": checks, "stale_prices": rows(quality.stale_prices),
                     "outliers": rows(quality.outliers), "adjustment_warnings": rows(quality.adjustment_warnings),
                     "survivorship_audit": {"status": "N-A", "reason": "No PIT membership/delisting ledger"},
                     "train_test_contamination": "Known prior exposure to archived data"},
                    failures + warnings, "FAIL" if failures else "WARN", bool(failures))


def segments(c):
    segment_rows = []
    for name, (start, stop) in c.splits.items():
        values = c.returns.iloc[start:stop]
        segment_rows.append({"segment": name, "start": str(values.index[0]), "end": str(values.index[-1]),
                             **c.stats(values), "meets_minimum": len(values) >= c.config.min_observations})
    return c.result(2, {"segments": len(segment_rows), "test_sharpe": segment_rows[-1]['sharpe'], "true_oos_sharpe": None},
                    {"segments": segment_rows, "true_oos": {"status": "N-A", "reason": "Dates were inspected in the underlying experiment"}},
                    ["Frozen rules evaluated independently in each segment with prior position context. Final segment is retrospective, not true OOS."], "WARN")


def walkforward(c):
    end = c.evaluation[c.splits['validation'][1] - 1]
    prices = c.prices.loc[:end]
    train = max(c.config.train_window, max(s.lookback for s in c.request.sleeves) + 2, 126)
    folds = walk_folds(len(prices), train, c.config.test_window, c.config.walk_mode, c.config.max_folds)
    if not folds:
        raise NeedData("No full forward fold before the final chronological test segment")
    selected = prices.iloc[:folds[-1][2]]
    def factory(frame, parameters=None):
        return StrategySignal('survival', pipeline_for(c.request).run(subset_bundle(c.bundle, frame.index)).weights)
    result = WalkForwardValidator(WalkForwardConfig(train_window=train, min_train_window=train,
                                                   test_window=c.config.test_window, mode=c.config.walk_mode),
                                  pipeline_for(c.request).backtest_config).evaluate(selected, factory)
    return c.result(3, {**c.stats(result.oos_returns), "folds": len(result.windows),
                        "sharpe_dispersion": float(result.window_metrics.test_sharpe.std(ddof=1)) if len(result.windows) > 1 else None},
                    {"folds": rows(result.window_metrics, 'fold'), "mode": c.config.walk_mode,
                     "unused_development_bars": len(prices) - len(selected), "parameters_fitted": False},
                    ["Rules frozen; train windows supply history, not parameter optimization. Repeated research remains retrospective."] , "WARN")


def variants(c):
    if 'variants' in c.cache:
        return c.cache['variants']
    stop = c.splits['validation'][1]
    index = c.evaluation[:stop]
    bundle = subset_bundle(c.bundle, c.prices.loc[:index[-1]].index)
    configs = [c.request]
    for i, sleeve in enumerate(c.request.sleeves):
        for scale in c.config.parameter_scales:
            if scale == 1:
                continue
            candidate = c.request.model_dump()
            candidate['sleeves'][i]['lookback'] = min(252, max(5, round(sleeve.lookback * scale)))
            # Preserve a valid mandate's train warmup while perturbing signal horizons.
            candidate['train_window'] = max(candidate['train_window'], candidate['sleeves'][i]['lookback'] + 2)
            configs.append(ResearchRequest.model_validate(candidate))
    seen, results, paths, attempted = set(), [], {}, []
    for request in configs:
        key = strategy_key(request)
        if key in seen:
            continue
        seen.add(key)
        record = {"candidate_id": key, "parameters": request.model_dump(), "dates": [str(d) for d in index]}
        try:
            net = pipeline_for(request).run(bundle).backtest.returns.loc[index]
            stat = c.stats(net)
            try:
                significance = hac_mean(net, c.config.hac_lags, c.config.confidence, c.config.min_observations)
            except NeedData:
                significance = None
            record.update(status='completed', metrics=stat, returns=net.tolist(), inference=significance)
            paths[key] = net
            results.append({"candidate_id": key, "lookbacks": {s.strategy: s.lookback for s in request.sleeves}, **stat})
        except (ValueError, ArithmeticError) as exc:
            record.update(status='failed', reason=str(exc), returns=None, inference=None)
            results.append({"candidate_id": key, "status": "FAIL", "reason": str(exc)})
        c.trial_sink(clean_json(record))
        attempted.append(record)
    c.cache['variants'] = (results, pd.DataFrame(paths), attempted)
    return c.cache['variants']


def stability(c):
    results, panel, trials = variants(c)
    if len(panel.columns) < 2:
        raise NeedData("Fewer than two distinct valid local parameter paths")
    sharpes = [r['metrics']['sharpe'] for r in trials if r.get('metrics', {}).get('sharpe') is not None]
    if len(sharpes) < 2:
        raise NeedData("Local parameter Sharpes are degenerate")
    return c.result(4, {"variants": len(trials), "valid_variants": panel.shape[1], "sharpe_min": min(sharpes),
                        "sharpe_max": max(sharpes), "sharpe_range": max(sharpes) - min(sharpes),
                        "positive_fraction": float(np.mean(np.array(sharpes) > 0))},
                    {"surface": results, "scope": "One-at-a-time local lookback ranges; development segment only"},
                    ["Sign changes across neighbors: configuration may be knife-edge"] if min(sharpes) < 0 < max(sharpes) else [],
                    "WARN" if min(sharpes) < 0 < max(sharpes) or any(t['status'] == 'failed' for t in trials) else "PASS")


def costs(c):
    base = pipeline_for(c.request).backtest_config
    def run(multiplier, extra=0):
        config = replace(base, transaction_cost_bps=base.transaction_cost_bps * multiplier + extra,
                         slippage_bps=(base.slippage_bps + c.config.spread_bps / 2) * multiplier,
                         annual_borrow_bps=base.annual_borrow_bps * multiplier)
        return VectorizedBacktester(config).run(c.prices, c.base.weights).returns.loc[c.evaluation]
    scenarios = [{"multiplier": multiplier, **c.stats(run(multiplier))} for multiplier in (1, 2, 3)]
    break_even, reason = None, None
    baseline = scenarios[0]['total_return']
    if c.base.backtest.turnover.sum() <= 0:
        reason = "No turnover; no finite per-traded-notional break-even cost"
    elif baseline <= 0:
        break_even = 0.
        reason = "Baseline already loses money; no additional cost capacity"
    else:
        def return_at(bps):
            try:
                return c.stats(run(1, bps))['total_return']
            except ValueError:
                return -1.  # Insolvency brackets a zero-return root.
        if return_at(1000) > 0:
            reason = "Break-even above bounded 1000 extra bps search"
        else:
            lo, hi = 0., 1000.
            for _ in range(20):
                middle = (lo + hi) / 2
                if return_at(middle) > 0:
                    lo = middle
                else:
                    hi = middle
            break_even = (lo + hi) / 2
    return c.result(5, {"return_at_3x": scenarios[-1]['total_return'], "break_even_extra_bps": break_even},
                    {"scenarios": scenarios, "break_even_note": reason, "spread_bps": c.config.spread_bps,
                     "borrow_stressed": True}, ["Net return is nonpositive at 3x assumed costs"] if scenarios[-1]['total_return'] <= 0 else [],
                    "WARN" if scenarios[-1]['total_return'] <= 0 else "PASS")


def liquidity(c):
    scenarios = []
    for delay, multiplier in sorted(set([(1, 1), (c.config.execution_delay, c.config.slippage_shock)])):
        scenario = execution_stress(c.prices, c.bundle.volume(), c.base.weights, c.request, c.config, delay, multiplier)
        net = pd.Series(scenario.pop('returns'), index=c.prices.index).loc[c.evaluation]
        scenario['metrics'].update(c.stats(net))
        scenarios.append(scenario)
    stressed = scenarios[-1]['metrics']
    return c.result(6, stressed, {"scenarios": scenarios, "participation_rate": c.config.participation_rate},
                    ["Daily adjusted-unit capacity is indicative; volume does not provide executable quotes or an impact curve."], "WARN")


def bootstrap(c):
    output = block_bootstrap(c.returns, seed=c.config.seed, samples=c.config.bootstrap_samples,
                             block_length=c.config.block_length, confidence=c.config.confidence,
                             annualization=c.config.annualization, minimum=c.config.min_observations)
    return c.result(7, {"loss_probability": output['loss_probability'], "intervals": output['intervals']}, output,
                    ["Intervals condition on this observed return history; they do not account for the full research search."], "WARN")


def significance(c):
    result = hac_mean(c.returns, c.config.hac_lags, c.config.confidence, c.config.min_observations)
    unresolved = result['ci_low'] <= 0
    return c.result(8, result, reasons=["Mean-return confidence interval includes zero; evidence is inconclusive"] if unresolved else ["Unadjusted inference; inspect the repeated-trial layer"], status="WARN")


def trial_family(c):
    _, _, current = variants(c)
    combined = {}
    # Deduplicate identical configurations/path evaluations, retain failed attempts
    # separately in persistence. Never combine incompatible sample dates.
    for trial in c.prior_trials + current:
        if trial.get('dates') == current[0]['dates']:
            combined[trial['candidate_id']] = trial
    return list(combined.values())


def multiple_testing(c):
    family = trial_family(c)
    usable = [t for t in family if t.get('inference')]
    adjusted = fdr([t['inference']['p_one_sided'] for t in usable])
    return c.result(9, {"recorded_trials": len(family), "valid_tests": len(usable), "unusable_trials": len(family)-len(usable),
                        "known_experiment_book_attempts": len(c.provenance.get('known_research_history', [])),
                        "minimum_adjusted_p": min(adjusted)},
                    {"tests": [{"candidate_id": t['candidate_id'], "p": t['inference']['p_one_sided'], "adjusted_p": q} for t,q in zip(usable, adjusted)],
                     "all_trials": [{"candidate_id": t['candidate_id'], "status": t['status'], "reason": t.get('reason')} for t in family]},
                    ["BY adjustment covers recorded comparable trials only. Prior external/adaptive research is unknown; this is exploratory inference."], "WARN")


def overfitting(c):
    family = trial_family(c)
    usable = [t for t in family if t.get('returns') is not None]
    outputs, reasons = {}, []
    panel = np.array([t['returns'] for t in usable]).T
    try:
        if len(usable) > c.config.max_cscv_trials:
            raise NeedData(f"{len(usable)} candidate paths exceed the configured CSCV limit {c.config.max_cscv_trials}; no selective downsampling applied")
        outputs['pbo'] = pbo(panel, c.config.cscv_blocks, c.config.min_observations)
    except NeedData as exc:
        outputs['pbo'] = {"status": "N-A", "reason": str(exc)}
        reasons.append(str(exc))
    try:
        candidate = next(t for t in usable if t['candidate_id'] == strategy_key(c.request))
        sharpes = [float(np.mean(t['returns']) / np.std(t['returns'], ddof=1)) if np.std(t['returns'], ddof=1) > 1e-12 else np.nan for t in usable]
        outputs['dsr'] = deflated_sharpe(candidate['returns'], sharpes, c.config.effective_trials, c.config.min_observations)
    except (NeedData, StopIteration) as exc:
        outputs['dsr'] = {"status": "N-A", "reason": str(exc) or "Baseline candidate unavailable"}
        reasons.append(outputs['dsr']['reason'])
    return c.result(10, {"pbo": outputs['pbo'].get('pbo'), "dsr": outputs['dsr'].get('dsr'), "trials": len(family)}, outputs,
                    reasons + ["Small local trial grids do not capture all researcher choices. DSR/CSCV remain conditional diagnostics."],
                    "N-A" if all(v.get('status') == 'N-A' for v in outputs.values()) else "WARN")


def regimes(c):
    labels = {'Q existing regimes': c.base.regimes.shift(1)}
    if c.bundle.benchmark is not None:
        benchmark = c.bundle.benchmark.Close
        trend = benchmark.pct_change(126, fill_method=None).shift(1)
        labels['Market trend'] = pd.Series(np.where(trend >= 0, 'bull', 'bear'), index=trend.index).where(trend.notna())
        vol = benchmark.pct_change(fill_method=None).rolling(21).std().shift(1)
        threshold = vol.expanding(min_periods=63).median().shift(1)
        labels['Volatility'] = pd.Series(np.where(vol >= threshold, 'high', 'low'), index=vol.index).where(threshold.notna())
    if c.filtered_regimes is not None:
        if not c.regime_provenance or c.regime_provenance.get('method') != 'train_only_forward_filter':
            raise NeedData("HMM states require verified train-only forward-filter provenance")
        labels['Filtered HMM'] = c.filtered_regimes.shift(1)
    table = []
    for name, series in labels.items():
        grouped = c.returns.groupby(series.reindex(c.evaluation))
        for label, values in grouped:
            table.append({"classification": name, "state": str(label), "observations": len(values),
                          "status": "PASS" if len(values) >= c.config.min_observations else "N-A",
                          **(c.stats(values) if len(values) >= c.config.min_observations else {}),
                          "sum_daily_returns": float(values.sum())})
    own = [abs(r['sum_daily_returns']) for r in table if r['classification'] == 'Q existing regimes']
    concentration = max(own) / sum(own) if own and sum(own) else None
    return c.result(11, {"regime_groups": len(table), "absolute_return_concentration": concentration},
                    {"states": table, "hmm": c.regime_provenance or {"status": "N-A", "reason": "This experiment has rule-based regimes; no aligned filtered HMM artifact"}},
                    ["Sparse states and unavailable HMM coverage require review; concentration is descriptive."], "WARN")


def attribution(c):
    if c.factor_provider:
        factors, source = c.factor_provider(c.evaluation)
        if not factors.index.equals(c.evaluation):
            raise NeedData("Factor provider dates must match exactly; no silent fill/drop")
    elif c.bundle.benchmark is not None:
        factors = c.bundle.benchmark.Close.pct_change(fill_method=None).loc[c.evaluation].to_frame('benchmark')
        source = {"name": c.request.benchmark, "fingerprint": c.provenance.get('dataset_hash'), "factors": "benchmark_only"}
    else:
        raise NeedData("No aligned benchmark or factor provider")
    result = factor_fit(c.returns, factors, c.config.hac_lags, c.config.confidence, c.config.min_observations)
    if 'benchmark' in factors:
        result['benchmark_return'] = c.stats(factors.benchmark)['total_return']
        result['active_total_return'] = c.stats(c.returns)['total_return'] - result['benchmark_return']
    return c.result(12, {**result, "annualized_arithmetic_alpha": result['daily_alpha'] * c.config.annualization},
                    {"factor_names": list(factors.columns), "source": source, "style_factors": "N-A unless a verified FactorProvider is supplied"},
                    ["Only connected factors can explain exposures; residual alpha depends on the model."], "WARN")


def universes(c):
    symbols = sorted(c.bundle.ohlcv)
    if len(symbols) < 3:
        raise NeedData("Leave-one-out robustness needs at least three available instruments")
    end = c.evaluation[c.splits['validation'][1]-1]
    table = []
    for omitted in symbols[:c.config.max_universe_subsets]:
        bundle = subset_bundle(c.bundle, c.prices.loc[:end].index)
        bundle.ohlcv = {s: frame for s, frame in bundle.ohlcv.items() if s != omitted}
        raw = c.request.model_dump()
        raw['symbols'] = [s for s in symbols if s != omitted]
        try:
            net = pipeline_for(ResearchRequest.model_validate(raw)).run(bundle).backtest.returns.loc[c.evaluation[:c.splits['validation'][1]]]
            table.append({"omitted": omitted, "universe": raw['symbols'], **c.stats(net), "status": "PASS"})
        except (ValueError, ArithmeticError) as exc:
            table.append({"omitted": omitted, "status": "FAIL", "reason": str(exc)})
    positive = sum(r.get('total_return', -1) > 0 for r in table)
    return c.result(13, {"subsets": len(table), "positive_fraction": positive / len(table)}, {"subsets": table},
                    ["Development dates only; deterministic alphabetical leave-one-out subsets. No alternative-asset or sector feed is implied."], "WARN")


def temporal(c):
    yearly = [{"year": int(year), **c.stats(values), "partial_year": len(values) < c.config.annualization,
               "sum_daily_returns": float(values.sum())} for year, values in c.returns.groupby(c.returns.index.year) if len(values) >= 2]
    rolling = []
    window = max(c.config.min_observations, 63)
    for stop in range(window, len(c.returns) + 1, 21):
        values = c.returns.iloc[stop-window:stop]
        rolling.append({"start": str(values.index[0]), "end": str(values.index[-1]), **c.stats(values)})
    if not yearly:
        raise NeedData("Not enough observations for a subperiod")
    concentration = [abs(r['sum_daily_returns']) for r in yearly]
    sharpes = [r['sharpe'] for r in rolling if r['sharpe'] is not None]
    return c.result(14, {"years": len(yearly), "absolute_return_concentration": max(concentration)/sum(concentration) if sum(concentration) else None,
                         "rolling_sharpe_dispersion": float(np.std(sharpes, ddof=1)) if len(sharpes) > 1 else None},
                    {"yearly": yearly, "rolling": rolling, "structural_break_test": {"status": "N-A", "reason": "No prespecified break date/model"}},
                    ["Isolated periods and dependent rolling estimates require interpretation; no structural-break p-value inferred."], "WARN")


def interaction(c):
    sleeves, removal = {}, []
    config = pipeline_for(c.request).backtest_config
    for sleeve in c.request.sleeves:
        signal = c.base.signals[sleeve.strategy]
        sleeves[sleeve.strategy] = VectorizedBacktester(config).run(c.prices, signal.weights).returns.loc[c.evaluation]
    panel = pd.DataFrame(sleeves)
    if len(sleeves) > 1:
        for sleeve in c.request.sleeves:
            raw = c.request.model_dump()
            raw['sleeves'] = [s for s in raw['sleeves'] if s['strategy'] != sleeve.strategy]
            budget = sum(s['budget'] for s in raw['sleeves'])
            for s in raw['sleeves']:
                s['budget'] = s['budget'] / budget * 100
            counterfactual = pipeline_for(ResearchRequest.model_validate(raw)).run(c.bundle).backtest.returns.loc[c.evaluation]
            base, without = c.stats(c.returns), c.stats(counterfactual)
            removal.append({"sleeve": sleeve.strategy, "without": without,
                            "incremental_return": base['total_return']-without['total_return'],
                            "incremental_volatility": base['volatility']-without['volatility']})
    peers = []
    for name, returns in c.peers.items():
        aligned = pd.concat([c.returns.rename('candidate'), returns.rename('peer')], axis=1).dropna()
        if len(aligned) < c.config.min_observations or (aligned.std() < 1e-12).any():
            peers.append({"experiment_id": name, "status": "N-A", "reason": "Insufficient aligned nonconstant returns"})
            continue
        mix = c.config.portfolio_mix * aligned.candidate + (1-c.config.portfolio_mix) * aligned.peer
        mixed, original = c.stats(mix), c.stats(aligned.peer)
        peers.append({"experiment_id": name, "correlation": float(aligned.corr().iloc[0,1]),
                      "candidate_weight": c.config.portfolio_mix, "mixed": mixed,
                      "incremental_return": mixed['total_return'] - original['total_return'],
                      "incremental_volatility": mixed['volatility'] - original['volatility']})
    if len(sleeves) < 2 and not peers:
        raise NeedData("Need multiple alpha sleeves or a selected peer experiment")
    covariance = panel.cov() * c.config.annualization
    weights = np.array([s.budget/100 for s in c.request.sleeves])
    variance = float(weights @ covariance.to_numpy() @ weights)
    contribution = weights * (covariance.to_numpy() @ weights) / variance if variance > 0 else np.full(len(weights), np.nan)
    return c.result(15, {"sleeves": len(sleeves), "peers": len(peers)},
                    {"correlations": rows(panel.corr(), 'sleeve'), "counterfactuals": removal, "peers": peers,
                     "standalone_covariance_risk_fraction": dict(zip(panel.columns, contribution.tolist())),
                     "overlap": [{"left": a, "right": b, "mean_absolute_target_overlap": float(np.minimum(c.base.signals[a].weights.abs(), c.base.signals[b].weights.abs()).sum(axis=1).mean())} for i,a in enumerate(sleeves) for b in list(sleeves)[i+1:]]},
                    ["Covariance contributions use standalone budget-weighted sleeves; allocated counterfactuals capture nonlinear constraints."], "WARN")


def tails(c):
    x = c.returns
    if len(x) < max(c.config.min_observations, 60):
        raise NeedData("Empirical 95% tail needs >=60 daily returns (at least three expected tail observations)")
    q = float(x.quantile(.05))
    equity = np.r_[1., np.cumprod(1+x.to_numpy())]
    underwater = equity < np.maximum.accumulate(equity) - 1e-12
    longest = current = 0
    spells = []
    start = None
    for i, down in enumerate(underwater):
        current = current+1 if down else 0
        longest = max(longest, current)
        if down and start is None:
            start = i
        elif not down and start is not None:
            spells.append({"start": str(x.index[start-1]), "recovered": str(x.index[i-1]), "bars": i-start})
            start = None
    if start is not None:
        spells.append({"start": str(x.index[start-1]), "recovered": None, "bars": len(equity)-start})
    weight = c.base.backtest.weights.loc[c.evaluation[-1]]
    net = float(weight.sum())
    return c.result(16, {"var95_loss": -q, "es95_loss": -float(x[x <= q].mean()),
                         "max_drawdown": c.stats(x)['max_drawdown'],
                         "longest_underwater_bars": longest, "current_underwater_bars": current,
                         "synthetic_gap_return": net*c.config.shock_return,
                         "worst_20_bar_return": float((1+x).rolling(20).apply(np.prod, raw=True).min()-1)},
                    {"worst_days": [{"date": str(d), "return": float(v)} for d,v in x.nsmallest(10).items()],
                     "drawdown_spells": spells, "gap": {"asset_shock": c.config.shock_return, "net_weight": net},
                     "worst_closed_trades": {"status": "N-A", "reason": "Fractional weight engine has no closed-trade ledger"}},
                    ["Historical tail estimates and frozen-weight synthetic shocks exclude unobserved liquidity crises."], "WARN")


def paper(c):
    if not c.paper or not c.paper.get('observations'):
        raise NeedData("No subsequent observations in a prospectively registered forward paper record")
    output = dict(c.paper)
    output.pop('evaluated_at', None)
    if output['observations'] < c.config.min_observations:
        output['performance'] = None
    return c.result(17, {"observations": output['observations'], "mean_cost_drift_bps": output['mean_cost_drift_bps'],
                         "mean_return_drift": output['mean_return_drift'], "risk_breaches": len(output['breaches']),
                         "mean_absolute_weight_deviation": output['mean_absolute_weight_deviation'],
                         "recorded_fills": output['recorded_fills']}, output,
                    ["User-recorded paper observations are not broker verified; insufficient samples suppress performance inference."], "WARN")


def live(c):
    raise NeedData("Live feed, reconciliation and authenticated execution ledger are not connected. Read-only monitor contract exists; live orders remain disabled.")


LAYERS = [integrity, segments, walkforward, stability, costs, liquidity, bootstrap, significance,
          multiple_testing, overfitting, regimes, attribution, universes, temporal, interaction, tails, paper, live]


def run_pipeline(context: Context, progress=lambda layer: None):
    results = []
    integrity_failed = False
    for number, calculate in enumerate(LAYERS, 1):
        try:
            if number not in context.config.layers:
                raise NeedData("Layer not requested by this saved configuration")
            if integrity_failed and 2 <= number <= 16:
                raise NeedData("Blocked by hard integrity failure; financial diagnostics would be unreliable")
            result = calculate(context)
        except NeedData as exc:
            result = context.result(number, reasons=[str(exc)], status="N-A")
        except Exception as exc:
            # Retain failure and continue independent layers; never label a crashed
            # calculation as an unsupported statistical test or discard the run.
            result = context.result(number, reasons=[f"Calculation failed: {type(exc).__name__}: {str(exc)[:500]}"], status="FAIL", hard=number == 1)
        result = apply_gates(result, context.config)
        if number == 1 and result.hard_failure:
            integrity_failed = True
        results.append(result)
        progress(result.model_dump())
    return clean_json({"version": VERSION, "experiment_id": context.experiment_id,
                       "config": context.config.model_dump(), "provenance": context.provenance,
                       "strategy_version": strategy_key(context.request), "request": context.request.model_dump(),
                       "synthetic": context.request.data_mode in {'demo', 'synthetic'},
                       "layers": [r.model_dump() for r in results], "summary": summarize(results, context.config)})
