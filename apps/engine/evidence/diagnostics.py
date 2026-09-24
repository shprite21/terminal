from __future__ import annotations

from datetime import date
import numpy as np
import pandas as pd
from .engine import features
from .actions import validated_actions, split_factor


def signal_study(frame, strategy, calendar, start, end, horizons=(1, 5, 20), actions=()):
    actions = validated_actions(actions, calendar, set(frame.instrument))
    signals = features(frame, strategy, calendar, actions)
    if signals.empty:
        return {"status": "unavailable", "reason": "Insufficient trailing real observations", "observations": []}
    dates = sorted(calendar.sessions)
    date_index = {str(day): index for index, day in enumerate(dates)}
    closes = {(str(r.date), r.instrument): r.close for r in frame.itertuples()}
    rows = []
    for row in signals.itertuples():
        if not row.eligible or not str(start) <= row.date <= str(end):
            continue
        for horizon in horizons:
            index = date_index[row.date] + horizon
            if index >= len(dates) or dates[index] > end:
                continue  # Evaluation labels never cross the named partition.
            later = closes.get((str(dates[index]), row.instrument))
            if later is not None:
                rows.append({"instrument": row.instrument, "date": row.date, "label_end": str(dates[index]), "horizon": horizon,
                             "score": row.score, "forward_return": later * split_factor(actions, row.instrument, date.fromisoformat(row.date), dates[index]) / row.close - 1})
    if not rows:
        return {"status": "unavailable", "reason": "No in-partition forward labels", "observations": []}
    labels = pd.DataFrame(rows)
    summaries = []
    for horizon, group in labels.groupby("horizon"):
        ics, spreads, buckets = [], [], []
        for day, cross in group.groupby("date"):
            if len(cross) >= 3 and cross.score.nunique() > 1 and cross.forward_return.nunique() > 1:
                ics.append(float(cross.score.rank().corr(cross.forward_return.rank())))
                ranked = cross.assign(bucket=pd.qcut(cross.score.rank(method="first"), 3, labels=["low", "middle", "high"]))
                means = ranked.groupby("bucket", observed=True).forward_return.mean()
                spreads.append(float(means["high"] - means["low"]))
                buckets.extend({"date": day, "bucket": str(bucket), "return": float(value)} for bucket, value in means.items())
        # Nonoverlapping chronological blocks of date-level means; no invented price paths.
        means = group.groupby("date").forward_return.mean().to_numpy()
        blocks = [float(np.mean(means[i:i+horizon])) for i in range(0, len(means)-horizon+1, horizon)]
        se = float(np.std(blocks, ddof=1)/np.sqrt(len(blocks))) if len(blocks) >= 5 else None
        persistence_pairs = group.sort_values(["instrument", "date"])
        lagged = persistence_pairs.groupby("instrument").score.shift(1)
        persistence = persistence_pairs.score.corr(lagged) if lagged.notna().sum() >= 3 and lagged.std() > 0 and persistence_pairs.score.std() > 0 else None
        summaries.append({"horizon": int(horizon), "observations": len(group), "sessions": int(group.date.nunique()),
                          "mean_forward_return": float(group.forward_return.mean()), "mean_rank_ic": float(np.mean(ics)) if ics else None,
                          "top_minus_bottom_equal_weight": float(np.mean(spreads)) if spreads else None,
                          "date_mean_block_standard_error": se, "nonoverlapping_blocks": len(blocks),
                          "signal_persistence": float(persistence) if persistence is not None and np.isfinite(persistence) else None,
                          "bucket_returns": buckets})
    return {"status": "completed", "summaries": summaries, "observations": rows,
            "limitations": "Labels are split-aware close-to-close price returns excluding dividends, not executable returns. Date-level block uncertainty is descriptive and requires at least five blocks; residual dependence may remain. Quantiles/IC require at least three contemporaneously eligible instruments. No sector analysis without attributable classifications."}


def purged_training(observations, evaluation_start, evaluation_end, embargo_sessions=0, calendar=None):
    """Inclusive label intervals: every training label must end before evaluation."""
    cutoff = evaluation_start
    if embargo_sessions:
        if calendar is None:
            raise ValueError("Calendar required for embargo")
        prior = sorted(d for d in calendar.sessions if d < evaluation_start)
        if len(prior) < embargo_sessions:
            return []
        cutoff = prior[-embargo_sessions]
    return [row for row in observations if date.fromisoformat(row["date"]) < cutoff and date.fromisoformat(row["label_end"]) < cutoff]


def combine_returns(first, second, fixed_weight):
    if not 0 <= fixed_weight <= 1:
        raise ValueError("Fixed weight must be in [0,1]")
    if set(first) != set(second):
        raise ValueError("Return dates differ: explicit complete alignment required")
    days = sorted(first)
    a, b = np.array([first[d] for d in days]), np.array([second[d] for d in days])
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("Invalid supplied returns")
    correlation = float(np.corrcoef(a,b)[0,1]) if len(days) >= 3 and a.std() and b.std() else None
    return {"correlation": correlation, "fixed_weight": fixed_weight, "returns": dict(zip(days, (fixed_weight*a+(1-fixed_weight)*b).tolist()))}
