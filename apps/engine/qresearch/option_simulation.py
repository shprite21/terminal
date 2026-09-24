"""Seeded GBM, prior-event quotes and next-event delta hedging for Q.

Quote skew and stochastic customer flow adapt quant-research project 03.
Positions/cash are owned by option_account, never by pricing or the UI.
"""
from math import ceil, exp, floor, sqrt, trunc
from types import SimpleNamespace

import numpy as np
from pydantic import Field, model_validator

from .options import PricingConfig, values
from .option_account import Account
from .origins.options.order_flow import OrderFlowConfig, OrderFlowSimulator


class SimulationConfig(PricingConfig):
    initial_cash: float = Field(100_000, ge=1, le=1e9)
    seed: int = Field(42, ge=0, le=2**32-1)
    steps: int = Field(780, ge=2, le=10_000)
    steps_per_day: int = Field(78, ge=1, le=1440)
    drift: float = Field(.04, ge=-1, le=1)
    multiplier: int = Field(100, ge=1, le=1000)
    max_contracts: int = Field(25, ge=1, le=1000)
    spread_bps: float = Field(35, ge=0, le=1000)
    min_spread: float = Field(.03, ge=.001, le=100)
    tick_size: float = Field(.01, ge=.0001, le=100)
    inventory_skew: float = Field(.12, ge=0, le=1)
    arrival_probability: float = Field(.62, ge=0, le=1)
    mean_quantity: float = Field(4, gt=0, le=25)
    option_fee_per_contract: float = Field(.02, ge=0, le=100)
    hedge_threshold_shares: float = Field(15, ge=0, le=100_000)
    hedge_cost_bps: float = Field(.5, ge=0, le=100)
    hedge_slippage_bps: float = Field(1, ge=0, le=100)

    @model_validator(mode='after')
    def before_expiry(self):
        if self.steps/(252*self.steps_per_day) >= self.maturity_years:
            raise ValueError('Simulation must end before expiry; shorten steps or extend maturity. Terminal positions are marked, not settled.')
        return self


def simulate(config: SimulationConfig, cancel=lambda: False, progress=lambda *_: None, *, spots=None):
    dt = 1/(252*config.steps_per_day)
    rng = np.random.default_rng(config.seed)
    flow = OrderFlowSimulator(OrderFlowConfig(seed=config.seed ^ 0x5A5A5A5A,
        base_arrival_probability=config.arrival_probability, mean_quantity=config.mean_quantity))
    account = Account(config.initial_cash, config.multiplier, config.strike, config.option_type, config.max_contracts)
    if spots is not None:
        spots = np.asarray(spots, dtype=float)
        if len(spots) != config.steps+1 or not np.isfinite(spots).all() or (spots <= 0).any() or spots[0] != config.spot:
            raise ValueError('Test path must contain initial spot and exactly steps positive finite prices')
    rows, trades = [], []
    spot, quote, hedge_target, peak = config.spot, None, None, config.initial_cash
    option_cash = hedge_cash = fees_option = fees_stock = slippage = 0.
    previous_spot = spot
    for step in range(config.steps+1):
        if cancel():
            raise InterruptedError()
        if step:
            previous_spot = spot
            spot = float(spots[step]) if spots is not None else spot*exp((config.drift-.5*config.volatility**2)*dt+config.volatility*sqrt(dt)*rng.normal())
        if not np.isfinite(spot) or spot <= 0:
            raise ValueError('GBM path exceeded numerical range')
        v = values(spot, config.strike, config.maturity_years-step*dt, config.rate, config.volatility, config.option_type)
        # Change in value of positions held across the event boundary. New
        # fills and their costs are excluded, so imperfect hedging is visible.
        hedge_error = (account.shares*(spot-previous_spot)
                       + account.contracts*config.multiplier*(v['price']-rows[-1]['fair_value'])) if rows else 0.
        # Execute ONLY the target recorded at the previous observation. This
        # hedge cannot respond to today's price or today's customer fill.
        if hedge_target is not None:
            quantity = int(hedge_target-account.shares)
            if quantity:
                price = spot*(1+(1 if quantity > 0 else -1)*config.hedge_slippage_bps/10_000)
                fee = abs(quantity)*price*config.hedge_cost_bps/10_000
                fill = account.transact('stock', quantity, price, fee, spot)
                trades.append(dict(step=step, signal_step=step-1, asset='stock', quantity=quantity,
                    price=price, fee=fee if fill['accepted'] else 0., **fill))
                if fill['accepted']:
                    hedge_cash += fill['cash_flow']; fees_stock += fee
                    slippage += abs(quantity)*abs(price-spot)
        if quote is not None:
            order = flow.generate_order(step, step*dt, quote, v['price'], np.sign(spot-previous_spot))
            if order is not None:
                quantity = order.quantity * (-1 if order.side == 'buy' else 1)
                fee = abs(quantity)*config.option_fee_per_contract
                fill = account.transact('option', quantity, order.limit_price, fee, spot)
                trades.append(dict(step=step, signal_step=step-1, asset='option', quantity=quantity,
                    price=order.limit_price, fee=fee if fill['accepted'] else 0., **fill))
                if fill['accepted']:
                    option_cash += fill['cash_flow']; fees_option += fee
        net_delta = account.shares + account.contracts*config.multiplier*v['delta']
        hedge_target = trunc(-account.contracts*config.multiplier*v['delta']) if abs(net_delta)>config.hedge_threshold_shares else None
        # Same inventory skew and spread penalty as source; posted now for the
        # next event. Keep the quote attached to its exact observation.
        ratio = account.contracts/config.max_contracts
        spread = max(config.min_spread, v['price']*config.spread_bps/10_000+abs(ratio)*.10*max(v['price'], 1))
        mid = max(config.tick_size, v['price']-config.inventory_skew*ratio*max(v['price'], 1))
        bid = floor(max(config.tick_size, mid-spread/2)/config.tick_size)*config.tick_size
        ask = ceil(max(bid+config.tick_size, mid+spread/2)/config.tick_size)*config.tick_size
        quote = SimpleNamespace(bid=bid, ask=ask, mid=(bid+ask)/2)
        equity = account.cash + account.contracts*config.multiplier*v['price'] + account.shares*spot
        peak = max(peak, equity)
        rows.append(dict(step=step, elapsed_years=step*dt, spot=spot, fair_value=v['price'],
            bid=bid, ask=ask, cash=account.cash, reserve=account.reserve(spot),
            free_cash=account.cash-account.reserve(spot), contracts=account.contracts, shares=account.shares,
            net_delta=net_delta, hedge_target=hedge_target, equity=equity, pnl=equity-config.initial_cash,
            fees=account.fees, drawdown_percent=100*(equity/peak-1)))
        rows[-1]['hedging_error'] = hedge_error
        if step % 100 == 0 or step == config.steps:
            progress(step, config.steps)
    last = rows[-1]
    metrics = dict(net_pnl=last['pnl'], return_percent=100*last['pnl']/config.initial_cash,
        max_drawdown_percent=min(r['drawdown_percent'] for r in rows),
        delta_rmse_shares=float(np.sqrt(np.mean([r['net_delta']**2 for r in rows[1:]]))),
        hedging_error_rmse=float(np.sqrt(np.mean([r['hedging_error']**2 for r in rows[1:]]))),
        cumulative_hedging_error=sum(r['hedging_error'] for r in rows),
        max_absolute_delta_shares=max(abs(r['net_delta']) for r in rows),
        max_absolute_contracts=max(abs(r['contracts']) for r in rows),
        option_fees=fees_option, hedge_fees=fees_stock, hedge_slippage=slippage,
        accepted_trades=sum(t['accepted'] for t in trades), rejected_trades=sum(not t['accepted'] for t in trades),
        collateral_breach_observations=sum(r['free_cash']<0 for r in rows),
        option_pnl=option_cash+last['contracts']*config.multiplier*last['fair_value'],
        hedge_pnl=hedge_cash+last['shares']*last['spot'])
    return dict(name='SYNTHETIC options market making', synthetic=True,
        results={'Options simulation': {'metrics': metrics, 'equity': rows, 'trades': trades,
                                       'configuration': config.model_dump()}},
        charts=[dict(section='Options simulation', table='equity', keys=keys, x='step', label=label)
                for keys, label in [(['spot'], 'GBM underlying · quote units'),
                                    (['fair_value','bid','ask'], 'Option fair value and quotes for the next event'),
                                    (['contracts'], 'Option inventory · whole contracts'),
                                    (['net_delta'], 'Residual delta exposure · shares'),
                                    (['hedging_error'], 'Hedged-position mark change per event · quote units'),
                                    (['free_cash'], 'Cash after modeled collateral')]],
        limitations=['Synthetic GBM and stochastic customer orders adapted from quant-research project 03; no historical order book, queue priority or empirical fill calibration.',
            'Quotes and hedge targets use the prior event. Stock hedges fill before new customer orders. All-or-none trades must meet cash, collateral and inventory limits; rejected hedges leave residual exposure.',
            'Research collateral reserves short options at full spot notional (calls) or strike notional (puts), plus 150% of short stock value, without offsets. This is not a broker margin or settlement model. Market moves can cause collateral deficits; those remain visible and only trades restoring collateral or reducing gross exposure while improving free cash are allowed.',
            'Cash earns no interest; borrow fees, dividends and funding charges are omitted. Hedge fees and adverse slippage are charged. P&L is marked before expiry; final positions remain open and no close-out cost is assumed.',
            'Delta RMSE measures residual share-equivalent exposure after fills. Hedging error is the per-event mark change of the prior option and stock holdings, including option time decay, excluding new fills and costs; it is not a terminal payoff replication error. Time uses 252 modeled days per year, not a production exchange calendar.'])
