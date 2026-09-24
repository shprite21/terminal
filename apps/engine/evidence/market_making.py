"""Seeded two-venue event scenarios, never represented as real exchange data."""
import math
from typing import Literal
import numpy as np
import pandas as pd
from pydantic import Field
from .models import Contract
from .storage import digest
from .lab_provenance import lab_fingerprint


class MMConfig(Contract):
    strategy: Literal["Market making", "Latency arbitrage", "Market making + latency arbitrage"] = "Market making + latency arbitrage"
    seed: int = Field(default=42, ge=0, lt=2**32)
    events: int = Field(default=3000, ge=100, le=20000)
    step_ms: int = Field(default=100, ge=10, le=1000)
    volatility_bps: float = Field(default=8, ge=0, le=100)
    venue_lag_ms: int = Field(default=300, ge=0, le=5000)
    feed_latency_ms: int = Field(default=100, ge=0, le=5000)
    order_latency_ms: int = Field(default=100, ge=0, le=5000)
    refresh_ms: int = Field(default=500, ge=10, le=10000)
    market_spread_bps: float = Field(default=4, gt=0, le=100)
    quote_half_spread_bps: float = Field(default=4, gt=0, le=100)
    skew_bps: float = Field(default=5, ge=0, le=100)
    min_edge_bps: float = Field(default=1, ge=0, le=100)
    maker_fee_bps: float = Field(default=.5, ge=0, le=100)
    taker_fee_bps: float = Field(default=1, ge=0, le=100)
    queue_ahead: int = Field(default=10, ge=0, le=10000)
    order_size: int = Field(default=5, ge=1, le=100)
    max_inventory: int = Field(default=50, ge=1, le=1000)
    initial_cash: float = Field(default=100000, ge=1000, le=1e9)


def make_events(config):
    c = MMConfig.model_validate(config)
    rng = np.random.default_rng(c.seed)
    change = rng.normal(0, c.volatility_bps/10000*math.sqrt(c.step_ms/1000), c.events)
    fast = 100*np.exp(np.cumsum(change))
    lag = math.ceil(c.venue_lag_ms/c.step_ms)
    slow = fast[np.maximum(0, np.arange(c.events)-lag)]
    return pd.DataFrame({"time_ms": np.arange(c.events)*c.step_ms, "fast_mid": fast, "slow_mid": slow,
                         "buy_volume": rng.poisson(4, c.events), "sell_volume": rng.poisson(4, c.events)})


def simulate_mm(events, config):
    c = MMConfig.model_validate(config)
    required = ["time_ms", "fast_mid", "slow_mid", "buy_volume", "sell_volume"]
    if not set(required).issubset(events) or len(events) != c.events:
        raise ValueError("Complete synthetic event stream required.")
    values = events[required].to_numpy(float)
    if not np.isfinite(values).all() or (events[["fast_mid", "slow_mid"]] <= 0).any().any():
        raise ValueError("Invalid synthetic event fields.")
    if not np.array_equal(events.time_ms, np.arange(c.events)*c.step_ms) or (events[["buy_volume", "sell_volume"]] < 0).any().any():
        raise ValueError("Invalid event timing or volume.")
    fast, slow = events.fast_mid.to_numpy(), events.slow_mid.to_numpy()
    feed_steps = math.ceil(c.feed_latency_ms/c.step_ms)
    # Even zero configured order latency acts no earlier than the next event.
    order_steps = max(1, math.ceil(c.order_latency_ms/c.step_ms))
    refresh = max(1, math.ceil(c.refresh_ms/c.step_ms))
    cash, inventory, fees = c.initial_cash, 0, 0.0
    pending_quotes, pending_arb = {}, {}
    active = {}
    fills, curve, decisions = [], [], []
    arb_pnl = 0.0
    rejected = 0
    half = c.market_spread_bps/20000
    maker_enabled = c.strategy != "Latency arbitrage"
    arb_enabled = c.strategy != "Market making"

    def execute(side, quantity, price, i, kind, fee_bps):
        nonlocal cash, inventory, fees
        sign = 1 if side == "BUY" else -1
        fee = quantity*price*fee_bps/10000
        cash -= sign*quantity*price + fee
        inventory += sign*quantity
        fees += fee
        fills.append({"time_ms": int(events.time_ms.iloc[i]), "side": side, "quantity": quantity,
                      "price": float(price), "fee": float(fee), "kind": kind,
                      "execution_kind": "simulated execution on synthetic events"})

    for i in range(c.events):
        bid, ask = slow[i]*(1-half), slow[i]*(1+half)
        # Old quotes remain executable until the replacement reaches the venue.
        if i in pending_quotes:
            active = pending_quotes.pop(i)
            for side in list(active):
                if (side == "BUY" and active[side]["price"] >= ask) or (side == "SELL" and active[side]["price"] <= bid):
                    del active[side]
                    rejected += 1  # post-only rejection; never assume free aggressive fills
        for side, volume, touch in [("BUY", events.sell_volume.iloc[i], bid), ("SELL", events.buy_volume.iloc[i], ask)]:
            quote = active.get(side)
            if quote is None:
                continue
            reachable = quote["price"] >= touch if side == "BUY" else quote["price"] <= touch
            if not reachable:
                continue
            consumed = min(quote["ahead"], int(volume))
            quote["ahead"] -= consumed
            available = max(0, int(volume)-consumed)
            risk_capacity = c.max_inventory-inventory if side == "BUY" else c.max_inventory+inventory
            # Gross inventory exposure also cannot exceed initial collateral.
            risk_capacity = min(risk_capacity, max(0, int(c.initial_cash/slow[i])-abs(inventory)))
            qty = min(quote["remaining"], available, max(0, risk_capacity))
            if qty:
                execute(side, qty, quote["price"], i, "maker", c.maker_fee_bps)
                quote["remaining"] -= qty
                if not quote["remaining"]:
                    del active[side]
        if i in pending_arb:
            direction = pending_arb.pop(i)
            # Paired market orders execute at arrival prices, not the observed stale prices.
            qty = min(c.order_size, max(0, int(c.initial_cash*.1/(2*max(fast[i], slow[i])))))
            if qty:
                before = cash
                if direction == 1:
                    execute("BUY", qty, ask, i, "arb_slow", c.taker_fee_bps)
                    execute("SELL", qty, fast[i]*(1-half), i, "arb_fast_hedge", c.taker_fee_bps)
                else:
                    execute("SELL", qty, bid, i, "arb_slow", c.taker_fee_bps)
                    execute("BUY", qty, fast[i]*(1+half), i, "arb_fast_hedge", c.taker_fee_bps)
                arb_pnl += cash-before
        observed = i-feed_steps
        arrival = i+order_steps
        if observed >= 0 and arrival < c.events and i % refresh == 0:
            if maker_enabled:
                center = fast[observed]*(1-inventory/c.max_inventory*c.skew_bps/10000)
                pending_quotes[arrival] = {side: {"price": float(center*(1+sign*c.quote_half_spread_bps/10000)),
                                                  "remaining": c.order_size, "ahead": c.queue_ahead}
                                           for side, sign in [("BUY", -1), ("SELL", 1)]}
            if arb_enabled:
                buy_slow = fast[observed]*(1-half)-slow[observed]*(1+half)
                sell_slow = slow[observed]*(1-half)-fast[observed]*(1+half)
                edge = max(buy_slow, sell_slow)/fast[observed]*10000
                if edge > c.min_edge_bps+2*c.taker_fee_bps:
                    pending_arb[arrival] = 1 if buy_slow > sell_slow else -1
                    decisions.append({"time_ms": int(events.time_ms.iloc[i]), "observed_time_ms": int(events.time_ms.iloc[observed]),
                                      "arrival_ms": arrival*c.step_ms, "observed_edge_bps": float(edge)})
        if i == c.events-1 and inventory:
            execute("SELL" if inventory > 0 else "BUY", abs(inventory), bid if inventory > 0 else ask,
                    i, "terminal_liquidation", c.taker_fee_bps)
        nav = cash+inventory*slow[i]
        if nav <= 0:
            raise ValueError("Scenario insolvent; lower order size or inventory limit.")
        curve.append({"time_ms": int(events.time_ms.iloc[i]), "equity": float(nav), "pnl": float(nav-c.initial_cash),
                      "inventory": inventory, "fees": float(fees), "arb_pnl": float(arb_pnl),
                      "fast_mid": float(fast[i]), "slow_mid": float(slow[i]),
                      "bid_quote": active.get("BUY", {}).get("price"), "ask_quote": active.get("SELL", {}).get("price")})
    navs = np.r_[c.initial_cash, [x["equity"] for x in curve]]
    metrics = {"net_pnl": float(navs[-1]-navs[0]), "net_return": float(navs[-1]/navs[0]-1),
               "max_drawdown": float((navs/np.maximum.accumulate(navs)-1).min()), "fees": float(fees),
               "fills": len(fills), "arb_round_trips": sum(f["kind"] == "arb_slow" for f in fills),
               "arb_pnl": float(arb_pnl), "post_only_rejections": rejected,
               "peak_abs_inventory": max(abs(r["inventory"]) for r in curve), "ending_inventory": inventory}
    return {"configuration": c.model_dump(), "metrics": metrics, "curve": curve, "fills": fills, "decisions": decisions,
            "effective_feed_ms": feed_steps*c.step_ms, "effective_order_ms": order_steps*c.step_ms}


MM_LIMITATIONS = [
    "SYNTHETIC MARKET: a toy two-venue microstructure model, not evidence of actual latency-arbitrage profitability.",
    "Seeded lognormal reference mid; slow venue is a delayed reference. Poisson aggressive volumes, constant spread, no real order book.",
    "Price-touch volume consumes assumed queue ahead; no price-time-priority reconstruction, competition or hidden liquidity.",
    "Feed and outbound delays round up to event steps; outbound delay is at least one event. Quotes replace atomically at arrival; old quotes remain live until then.",
    "Arbitrage uses delayed observations and arrival prices. Both hedge legs fill atomically with assumed depth: no legging failures, separate venue balances or transfer costs.",
    "Inventory may be short within limits. Fees are per-side assumptions. Financing, borrow fees and taxes omitted; full terminal liquidation at the synthetic spread is assumed."]


def run_mm(store, config):
    c = MMConfig.model_validate(config)
    events = make_events(c)
    rows = events.to_dict("records")
    data_id = store.put("mm_dataset", {"name": "SYNTHETIC · two-venue event scenario", "synthetic": True,
                                       "generator": "two-venue-v1", "configuration": c.model_dump(),
                                       "rows_sha256": digest(rows), "rows": rows, "numpy_version": np.__version__})
    result = simulate_mm(events, c)
    # Same market events, only our outbound latency changes.
    latency = []
    for ms in sorted({0, c.order_latency_ms, 500, 1000}):
        variant = c.model_copy(update={"order_latency_ms": ms})
        metrics = result["metrics"] if ms == c.order_latency_ms else simulate_mm(events, variant)["metrics"]
        latency.append({"outbound_latency_ms": ms, "effective_ms": max(c.step_ms, math.ceil(ms/c.step_ms)*c.step_ms), **metrics})
    return store.put("mm_report", {"name": "SYNTHETIC · " + c.strategy, "dataset_id": data_id,
                                    "engine_version": "mm-v1", "code": lab_fingerprint(), "synthetic": True, "result": result,
                                    "latency_sensitivity": latency, "limitations": MM_LIMITATIONS})
