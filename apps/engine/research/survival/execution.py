"""Whole-share liquidity stress composed with Q's existing execution simulator."""
import numpy as np
import pandas as pd

from execution.simulator import ExecutionConfig, ExecutionSimulator, Order
from .statistics import NeedData, metrics


def execution_stress(prices, volumes, targets, request, config, delay=1, slippage_multiplier=1):
    if not request.long_only or request.max_gross_exposure > 1 or (targets < -1e-10).any().any():
        raise NeedData("Volume/cash stress supports unlevered long-only mandates; short locate/collateral model unavailable")
    if volumes.shape != prices.shape or volumes.isna().any().any() or (volumes < 0).any().any():
        raise NeedData("Liquidity stress needs complete nonnegative share-volume history")
    if not np.isfinite(volumes.to_numpy()).all():
        raise NeedData("Volume contains nonfinite values")
    # Signal sizing and participation use only completed bars. Fill price is the
    # execution close; an unfilled remainder expires (not retrospectively filled).
    adv = volumes.rolling(20, min_periods=20).mean().shift(1).fillna(0)
    simulator = ExecutionSimulator(ExecutionConfig(
        commission_bps=request.commission_bps,
        slippage_bps=request.slippage_bps * slippage_multiplier + config.spread_bps / 2,
        max_participation_rate=config.participation_rate))
    frequency = {"daily": None, "weekly": "W-FRI", "monthly": "M"}[request.rebalance]
    periods = prices.index.to_period(frequency) if frequency else None
    cash = request.initial_capital
    holdings = np.zeros(len(prices.columns), dtype=np.int64)
    scheduled = {}
    navs, cash_rows, fills, capacities = [], [], [], []
    clipped = 0
    for i, date in enumerate(prices.index):
        px = prices.iloc[i].to_numpy(float)
        if i in scheduled:
            signal_i, desired = scheduled.pop(i)
            delta = desired - holdings
            # Sells release cash before buys. Lexical column order is deterministic.
            for j in sorted(range(len(delta)), key=lambda j: (delta[j] > 0, str(prices.columns[j]))):
                quantity = int(delta[j])
                if not quantity:
                    continue
                cap = int(adv.iloc[i, j] * config.participation_rate)
                allowed = int(np.sign(quantity) * min(abs(quantity), cap))
                if allowed > 0:
                    unit_cost = px[j] * (1 + simulator.config.slippage_bps / 10000 + request.commission_bps / 10000)
                    allowed = min(allowed, int(max(cash, 0) / unit_cost))
                clipped += int(allowed != quantity)
                if not allowed:
                    continue
                symbol = prices.columns[j]
                fill = simulator.simulate_orders([Order(date, symbol, allowed, "buy" if allowed > 0 else "sell")], prices)[0]
                cash -= allowed * fill.price + fill.commission
                holdings[j] += allowed
                if cash < -1e-7 or (holdings < 0).any():
                    raise ValueError("Whole-share cash conservation failure")
                fills.append({"signal_date": str(prices.index[signal_i]), "date": str(date),
                              "symbol": symbol, "quantity": allowed, "price": fill.price,
                              "commission": fill.commission, "slippage": fill.slippage})
        nav = float(cash + holdings @ px)
        navs.append(nav)
        cash_rows.append(float(cash))
        is_close = frequency is None or (i + 1 < len(prices) and periods[i] != periods[i + 1])
        if is_close and i + delay < len(prices):
            desired = np.floor(targets.iloc[i].clip(lower=0).to_numpy() * nav / px).astype(np.int64)
            scheduled[i + delay] = (i, desired)
            change = np.abs(desired - holdings) * px / max(nav, 1e-12)
            for j in range(len(change)):
                if change[j] > 0 and adv.iloc[i, j] > 0:
                    capacities.append(float(config.participation_rate * adv.iloc[i, j] * px[j] / change[j]))
    returns = pd.Series(np.diff(np.r_[request.initial_capital, navs]) / np.r_[request.initial_capital, navs][:-1], index=prices.index)
    return {"metrics": {**metrics(returns, config.annualization), "clipped_orders": clipped,
                        "filled_orders": len(fills), "minimum_cash": min(cash_rows),
                        "indicative_capacity_p10": float(np.quantile(capacities, .1)) if capacities else None},
            "delay_bars": delay, "slippage_multiplier": slippage_multiplier,
            "fills": fills, "returns": returns.tolist(), "dates": [str(d) for d in prices.index],
            "ending_positions": dict(zip(prices.columns, holdings.tolist()))}
