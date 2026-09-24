from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
import math
import numpy as np
import pandas as pd

from .models import Strategy, Calendar
from .actions import validated_actions, split_factor, apply_actions


def money(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def charges(strategy, day, side, turnover):
    schedules = [s for s in strategy.costs if s.start <= day <= s.end]
    if len(schedules) != 1:
        raise ValueError("No unique effective-dated cost schedule for " + str(day))
    s = schedules[0]
    brokerage = min(s.brokerage_cap, max(s.brokerage_min, turnover * s.brokerage_rate))
    result = {"brokerage": money(brokerage), "stt": money(turnover * (s.stt_buy if side == "BUY" else s.stt_sell)),
              "exchange": money(turnover * s.exchange_rate), "sebi": money(turnover * s.sebi_rate),
              "ipft": money(turnover * s.ipft_rate), "stamp": money(turnover * s.stamp_buy) if side == "BUY" else 0.0,
              "dp": money(s.dp_per_debit) if side == "SELL" else 0.0}
    result["gst"] = money(sum(result[k] for k in ("brokerage", "exchange", "sebi", "ipft", "dp")) * s.gst_rate)
    return result


def features(frame, strategy, calendar, actions=()):
    """Features see only trailing observations available by this session's close."""
    data = frame.copy()
    actions = validated_actions(actions, calendar, set(strategy.universe) | set(frame.instrument))
    data["date"] = data.date.map(lambda v: date.fromisoformat(str(v)))
    data["available_at"] = data.available_at.map(lambda v: datetime.fromisoformat(str(v)))
    data = data[data.instrument.isin(strategy.universe)].sort_values(["instrument", "date"])
    rows = []
    for instrument, group in data.groupby("instrument", sort=True):
        history = list(group.itertuples())
        for index in range(strategy.lookback, len(history)):
            row = history[index]
            close_time = calendar.sessions[row.date][1]
            window = history[index - strategy.lookback:index + 1]
            if any(r.available_at > close_time for r in window):
                continue
            # Require all trailing exchange sessions; never compress missing bars.
            expected = [d for d in calendar.sessions if window[0].date <= d <= row.date]
            if len(expected) != len(window):
                continue
            raw = row.close * split_factor(actions, instrument, window[0].date, row.date) / window[0].close - 1
            score = -raw if strategy.feature == "mean_reversion" else raw
            average_volume = sum(r.volume * split_factor(actions, instrument, r.date, row.date) for r in window[-strategy.lookback:]) / strategy.lookback
            average_turnover = sum(r.volume * r.close for r in window[-strategy.lookback:]) / strategy.lookback
            ratio = row.volume / average_volume if average_volume else None
            eligible = average_turnover >= strategy.min_daily_turnover and row.volume > 0
            if strategy.feature == "volume_momentum":
                eligible = eligible and ratio is not None and ratio >= strategy.volume_ratio
            rows.append({"instrument": instrument, "date": str(row.date), "decision_at": close_time.isoformat(),
                         "score": score, "close": row.close, "trailing_volume": average_volume,
                         "trailing_turnover": average_turnover, "volume_ratio": ratio, "eligible": eligible})
    result = pd.DataFrame(rows)
    if not result.empty and strategy.feature == "relative_strength":
        mask = result.eligible
        result.loc[mask, "score"] = result.loc[mask].groupby("date").score.rank(pct=True, method="average")
    return result


def simulate(frame, strategy: Strategy, calendar: Calendar, start, end, cancelled=lambda: False, progress=lambda a,b: None, actions=()):
    if not strategy.acknowledge_limitations:
        raise ValueError("Review and acknowledge dataset and execution limitations")
    dates = sorted(d for d in calendar.sessions if start <= d <= end)
    if not dates:
        raise ValueError("No exchange sessions in evaluation period")
    for day in dates:
        if sum(s.start <= day <= s.end for s in strategy.costs) != 1:
            raise ValueError("Cost schedules do not cover the full evaluation period")
    bars = {(date.fromisoformat(str(r.date)), r.instrument): r for r in frame.itertuples() if r.instrument in strategy.universe}
    # Full coverage required even when no positions are open.
    if any((day, instrument) not in bars for day in dates for instrument in strategy.universe):
        raise ValueError("Missing market observations: simulation blocked; no shortened period")
    actions = validated_actions(actions, calendar, set(frame.instrument))
    signals = features(frame, strategy, calendar, actions)
    cash, positions, queue = strategy.initial_cash, {}, []
    orders, fills, trades, equity, holdings = [], [], [], [], []
    receivables, cash_movements = [], []
    cumulative_cost = cumulative_impact = turnover = 0.0
    next_order = 1

    def new_order(instrument, side, quantity, created, due, reason, score=None):
        nonlocal next_order
        order = {"id": next_order, "instrument": instrument, "side": side, "quantity": int(quantity), "created_at": created,
                 "original_quantity": int(quantity),
                 "due_date": str(due), "reason": reason, "score": score, "status": "pending", "filled_quantity": 0,
                 "execution_kind": "simulated execution"}
        next_order += 1
        orders.append(order)
        return order

    for index, day in enumerate(dates):
        if cancelled():
            raise InterruptedError("Research cancelled")
        traded_today, volume_used = set(), {}
        today = {instrument: bars[day, instrument] for instrument in strategy.universe}
        cash_movements.extend(apply_actions(positions, actions, day, receivables, queue))
        for entitlement in list(receivables):
            if entitlement["pay_date"] <= str(day):
                cash += entitlement["amount"]
                cash_movements.append({"date": str(day), "kind": "dividend_payment", **entitlement})
                receivables.remove(entitlement)
        # Stops apply to positions carried into the session; opening entries activate next session.
        for instrument in sorted(positions):
            pos, bar = positions[instrument], today[instrument]
            stop = pos["entry_price"] * (1 - strategy.stop_fraction) if strategy.stop_fraction else None
            target = pos["entry_price"] * (1 + strategy.target_fraction) if strategy.target_fraction else None
            reference, reason = None, None
            if stop and bar.open <= stop:
                reference, reason = bar.open, "stop_gap"
            elif target and bar.open >= target:
                reference, reason = bar.open, "target_gap"
            elif stop and bar.low <= stop:
                reference, reason = stop, "stop_first_if_ambiguous"
            elif target and bar.high > target:  # A mere touch is not sufficient for a target limit.
                reference, reason = target, "target_penetrated"
            if reference is not None:
                # A scheduled opening sell has precedence over later intrabar events.
                if not any(o["instrument"] == instrument and o["side"] == "SELL" and o["due_date"] == str(day) for o in queue):
                    order = new_order(instrument, "SELL", pos["quantity"], pos["entry_at"], day, reason)
                    order["reference"] = reference
                    queue.append(order)
        due = [o for o in queue if o["due_date"] == str(day)]
        queue = [o for o in queue if o["due_date"] != str(day)]
        # Intrabar exits cannot fund opening buys in the same session.
        due.sort(key=lambda o: (1 if "reference" in o else 0, 0 if o["side"] == "SELL" else 1, -(o["score"] or 0), o["instrument"], o["id"]))
        for order in due:
            instrument, side = order["instrument"], order["side"]
            bar = today[instrument]
            remaining_volume = max(0, int(bar.volume * strategy.participation) - volume_used.get(instrument, 0))
            quantity = min(order["quantity"], remaining_volume)
            reference = order.get("reference", bar.open)
            impact = (strategy.slippage_bps + strategy.spread_bps / 2) / 10000
            price = reference * (1 + impact if side == "BUY" else 1 - impact)
            if side == "SELL":
                quantity = min(quantity, positions.get(instrument, {}).get("quantity", 0))
            elif instrument in positions or len(positions) >= strategy.max_positions:
                quantity = 0
            else:
                # Opening observed prices may constrain an already-sized order; never increase it.
                marked = sum(p["quantity"] * today[i].open for i, p in positions.items())
                nav = cash + marked
                budget = min(cash, nav * strategy.position_fraction, max(0, nav * strategy.max_exposure - marked))
                low, high = 0, quantity
                while low < high:
                    middle = (low + high + 1) // 2
                    required = middle * price + sum(charges(strategy, day, side, middle * price).values())
                    if required <= budget:
                        low = middle
                    else:
                        high = middle - 1
                quantity = low
            if quantity <= 0:
                order["status"] = "expired_unfilled"
                continue
            fees = charges(strategy, day, side, quantity * price)
            total_fees = sum(fees.values())
            order.update(status="filled" if quantity == order["quantity"] else "partial_remainder_cancelled", filled_quantity=quantity)
            execution_time = calendar.sessions[day][0].isoformat() if "reference" not in order else "intrabar time unknown: " + str(day)
            fills.append({"order_id": order["id"], "instrument": instrument, "date": str(day), "time": execution_time,
                          "side": side, "quantity": quantity, "price": price, "reference_price": reference,
                          "fees": fees, "execution_kind": "simulated execution"})
            cumulative_cost += total_fees
            cumulative_impact += abs(price - reference) * quantity
            turnover += quantity * price
            volume_used[instrument] = volume_used.get(instrument, 0) + quantity
            traded_today.add(instrument)
            if side == "BUY":
                cash -= quantity * price + total_fees
                positions[instrument] = {"quantity": quantity, "entry_price": price, "entry_cost_per_share": total_fees / quantity,
                                         "entry_index": index, "entry_date": str(day), "entry_at": execution_time}
            else:
                cash += quantity * price - total_fees
                pos = positions[instrument]
                pnl = quantity * (price - pos["entry_price"] - pos["entry_cost_per_share"]) - total_fees
                trades.append({"instrument": instrument, "entry_date": pos["entry_date"], "exit_date": str(day), "quantity": quantity,
                               "entry_price": pos["entry_price"], "exit_price": price, "net_pnl": pnl,
                               "holding_sessions": index - pos["entry_index"], "exit_order_id": order["id"], "execution_kind": "simulated execution"})
                pos["quantity"] -= quantity
                if not pos["quantity"]:
                    del positions[instrument]
        market_value = sum(p["quantity"] * today[i].close for i, p in positions.items())
        dividend_receivable = sum(r["amount"] for r in receivables)
        nav = cash + market_value + dividend_receivable
        if cash < -1e-6 or nav <= 0:
            raise ValueError("Portfolio accounting or solvency check failed")
        equity.append({"date": str(day), "cash": cash, "market_value": market_value, "dividend_receivable": dividend_receivable, "equity": nav,
                       "gross_same_positions": nav + cumulative_cost + cumulative_impact,
                       "costs": cumulative_cost, "spread_slippage": cumulative_impact,
                       "exposure": market_value / nav, "turnover_value": turnover})
        holdings.extend({"date": str(day), "instrument": i, "quantity": p["quantity"], "close": today[i].close, "value": p["quantity"] * today[i].close} for i,p in sorted(positions.items()))
        # Signals and orders are generated after the completed session.
        due_index = index + strategy.execution_delay
        if due_index < len(dates):
            due_day = dates[due_index]
            pending = {o["instrument"] for o in queue}
            for instrument, pos in sorted(positions.items()):
                if index - pos["entry_index"] + 1 >= strategy.holding_sessions and instrument not in pending:
                    queue.append(new_order(instrument, "SELL", pos["quantity"], calendar.sessions[day][1].isoformat(), due_day, "holding_horizon"))
            candidates = signals[(signals.date == str(day)) & signals.eligible & (signals.score > strategy.threshold)] if not signals.empty else signals
            if not candidates.empty:
                for candidate in candidates.sort_values(["score", "instrument"], ascending=[False, True]).itertuples():
                    instrument = candidate.instrument
                    if instrument in positions or instrument in pending or instrument in traded_today:
                        continue
                    quantity = min(int(nav * strategy.position_fraction / candidate.close), int(candidate.trailing_volume * strategy.participation))
                    if quantity > 0:
                        queue.append(new_order(instrument, "BUY", quantity, candidate.decision_at, due_day, "signal", candidate.score))
        progress(index + 1, len(dates))
    for order in queue:
        order["status"] = "expired_end_of_evaluation"
    selected_signals = signals[(signals.date >= str(start)) & (signals.date <= str(end))] if not signals.empty else signals
    signal_records = selected_signals.astype(object).where(pd.notna(selected_signals), None).to_dict("records")
    return {"equity": equity, "holdings": holdings, "orders": orders, "fills": fills, "trades": trades,
            "cash_movements": cash_movements, "dividend_receivables": receivables,
            "open_positions": positions, "signals": signal_records,
            "metrics": metrics(equity, trades, strategy.initial_cash),
            "execution_label": "Simulated executions from real historical observations"}


def metrics(equity, trades, initial_cash):
    frame = pd.DataFrame(equity)
    values = np.array([initial_cash] + frame.equity.tolist(), dtype=float)
    returns = values[1:] / values[:-1] - 1
    peaks = np.maximum.accumulate(values)
    drawdown = values / peaks - 1
    duration = longest = 0
    for value in drawdown:
        duration = duration + 1 if value < -1e-12 else 0
        longest = max(longest, duration)
    days = (date.fromisoformat(frame.date.iloc[-1]) - date.fromisoformat(frame.date.iloc[0])).days + 1
    total = values[-1] / initial_cash - 1
    pnl = [t["net_pnl"] for t in trades]
    wins, losses = [p for p in pnl if p > 0], [p for p in pnl if p < 0]
    sd = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0
    monthly = pd.Series(returns, index=pd.to_datetime(frame.date)).groupby(pd.to_datetime(frame.date).dt.strftime("%Y-%m").to_numpy()).apply(lambda x: float(np.prod(1+x)-1)).to_dict()
    annual = pd.Series(returns, index=pd.to_datetime(frame.date)).groupby(pd.to_datetime(frame.date).dt.strftime("%Y").to_numpy()).apply(lambda x: float(np.prod(1+x)-1)).to_dict()
    return {"total_return": total, "gross_same_positions_return": float(frame.gross_same_positions.iloc[-1] / initial_cash - 1),
            "cagr": float((1 + total) ** (365.25 / days) - 1) if days >= 365 else None,
            "annualized_volatility": sd * math.sqrt(252) if len(returns) >= 20 else None,
            "sharpe_zero_rf": float(np.mean(returns) / sd * math.sqrt(252)) if sd > 0 and len(returns) >= 20 else None,
            "max_drawdown": float(drawdown.min()), "max_drawdown_sessions": longest,
            "mean_exposure": float(frame.exposure.mean()), "time_invested": float((frame.market_value > 0).mean()),
            "turnover_over_initial_cash": float(frame.turnover_value.iloc[-1] / initial_cash),
            "trade_count": len(trades), "win_rate": len(wins)/len(pnl) if pnl else None,
            "average_win": float(np.mean(wins)) if wins else None, "average_loss": float(np.mean(losses)) if losses else None,
            "expectancy": float(np.mean(pnl)) if pnl else None, "profit_factor": sum(wins)/-sum(losses) if losses else None,
            "mean_holding_sessions": float(np.mean([t["holding_sessions"] for t in trades])) if trades else None,
            "costs": float(frame.costs.iloc[-1]), "spread_slippage": float(frame.spread_slippage.iloc[-1]),
            "worst_session_return": float(returns.min()), "daily_5pct_quantile": float(np.quantile(returns, .05)) if len(returns) >= 20 else None,
            "monthly_returns": monthly, "annual_returns": annual,
            "pnl_by_instrument": {i: sum(t["net_pnl"] for t in trades if t["instrument"] == i) for i in sorted({t["instrument"] for t in trades})},
            "largest_winning_exit_pnl": max(wins) if wins else None,
            "limitations": "CAGR requires one year; volatility/Sharpe require 20 sessions and remain uncertain. Annualization 252; risk-free zero. Exit-lot counts include partial exits. Gross uses the same positions and adds explicit costs and modeled impact back; not a separately resized frictionless portfolio."}
