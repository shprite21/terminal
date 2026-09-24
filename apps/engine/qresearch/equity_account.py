"""Cash-constrained whole-share account for Q's multi-strategy research.

The account receives target WEIGHTS observed at each close. It freezes whole
share targets then, and can execute them only at the next observed close.
"""
import numpy as np
from pydantic import BaseModel,ConfigDict,Field


class AccountConfig(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False,validate_default=True)
    initial_cash: float = Field(100_000,ge=100,le=1e9)
    commission_bps: float = Field(2,ge=0,le=100)
    slippage_bps: float = Field(3,ge=0,le=100)
    annual_borrow_rate: float = Field(.03,ge=0,le=1)
    short_collateral: float = Field(1.5,ge=1,le=3)
    maximum_gross: float = Field(1,gt=0,le=1.5)
    annualization: int = Field(252,ge=1,le=366)


def funding_exposure(config):
    return min(config.maximum_gross*.8,.8/max(config.short_collateral-1,1e-12))


def performance(equity,annualization=252):
    equity=np.asarray(equity,float)
    if len(equity)<2 or not np.isfinite(equity).all():raise ValueError('At least two finite account observations required')
    daily=np.divide(np.diff(equity),equity[:-1],out=np.zeros(len(equity)-1),where=equity[:-1]>0)
    std=float(daily.std(ddof=1)) if len(daily)>1 else 0.
    drawdown=float(np.min(equity/np.maximum.accumulate(equity)-1))
    annual_return=float((equity[-1]/equity[0])**(annualization/len(daily))-1) if (equity>0).all() else None
    downside=float(np.sqrt(np.mean(np.minimum(daily,0)**2)))
    return dict(net_pnl=float(equity[-1]-equity[0]),total_return=float(equity[-1]/equity[0]-1),
        sharpe=float(daily.mean()/std*np.sqrt(annualization)) if std>1e-12 and (equity>0).all() else None,
        max_drawdown_percent=100*drawdown,annualized_return=annual_return,
        calmar=annual_return/abs(drawdown) if annual_return is not None and drawdown < -1e-12 else None,
        sortino=float(daily.mean()/downside*np.sqrt(annualization)) if downside>1e-12 and (equity>0).all() else None,
        observations=len(daily),insolvent=bool((equity<=0).any()))


def simulate_account(prices,dates,targets,strategies,assets,config,start=0,stop=None,*,liquidate=False,cancel=lambda:False):
    prices=np.asarray(prices,float);targets=np.asarray(targets,float)
    stop=len(prices)-1 if stop is None else stop
    if (targets.shape!=(len(prices),len(strategies),len(assets)) or len(dates)!=len(prices)
        or prices.shape!=(len(dates),len(assets)) or not np.isfinite(prices).all() or (prices<=0).any()
        or not np.isfinite(targets).all() or not 0<=start<stop<len(prices)):
        raise ValueError('Invalid account prices, targets or evaluation interval')
    if (np.abs(targets).sum(axis=(1,2))>config.maximum_gross+1e-9).any():
        raise ValueError('Strategy targets exceed configured gross exposure')
    holdings=np.zeros((len(strategies),len(assets)),dtype=np.int64)
    cash=config.initial_cash;pending=None;rows=[];trades=[];attribution=[];total_fees=total_slippage=total_borrow=0.
    cumulative=np.zeros(len(strategies));peak=cash;accepted_count=rejected_count=0
    for i in range(start,stop+1):
        if cancel():raise InterruptedError()
        px=prices[i]
        mark_pnl=holdings@(px-prices[i-1]) if i>start else np.zeros(len(strategies))
        borrow=(np.maximum(-holdings,0)*prices[i-1]).sum(axis=1)*config.annual_borrow_rate/config.annualization if i>start else np.zeros(len(strategies))
        cash-=float(borrow.sum());total_borrow+=float(borrow.sum())
        costs=np.zeros(len(strategies))
        status='no change'
        if pending is not None and np.any(pending!=holdings):
            delta=pending-holdings
            fills=px*(1+np.sign(delta)*config.slippage_bps/10000)
            fees=np.abs(delta)*fills*config.commission_bps/10000
            slip=np.abs(delta)*px*config.slippage_bps/10000
            projected_cash=cash-float((delta*fills).sum()+fees.sum())
            reserve=float((np.maximum(-pending,0)*px).sum()*config.short_collateral)
            old_reserve=float((np.maximum(-holdings,0)*px).sum()*config.short_collateral)
            gross=float((np.abs(pending)*px).sum());old_gross=float((np.abs(holdings)*px).sum())
            nav=projected_cash+float((pending*px).sum())
            restoring=gross<old_gross and projected_cash-reserve>cash-old_reserve
            allowed=bool(projected_cash>=0 and nav>0 and ((projected_cash>=reserve and gross<=config.maximum_gross*nav+1e-8) or restoring))
            status='filled' if allowed else 'rejected: cash, collateral or gross exposure'
            if allowed:
                cash=projected_cash;holdings=pending.copy();costs=(fees+slip).sum(axis=1)
                total_fees+=float(fees.sum());total_slippage+=float(slip.sum());accepted_count+=1
            else:rejected_count+=1
            for s,a in zip(*np.nonzero(delta)):
                trades.append(dict(date=str(dates[i]),signal_date=str(dates[i-1]),strategy=strategies[s],asset=assets[a],
                    quantity=int(delta[s,a]),price=float(fills[s,a]),accepted=allowed,
                    commission=float(fees[s,a]) if allowed else 0.,slippage=float(slip[s,a]) if allowed else 0.,
                    cash_flow=float(-delta[s,a]*fills[s,a]-fees[s,a]) if allowed else 0.))
        pnl=mark_pnl-borrow-costs;cumulative+=pnl
        nav=cash+float((holdings*px).sum());peak=max(peak,nav)
        reserve=float((np.maximum(-holdings,0)*px).sum()*config.short_collateral)
        rows.append(dict(date=str(dates[i]),equity=nav,cash=cash,reserve=reserve,free_cash=cash-reserve,
            gross_exposure=float((np.abs(holdings)*px).sum()),drawdown_percent=100*(nav/peak-1),
            rebalance=status,commission=total_fees,slippage=total_slippage,borrow=total_borrow,
            positions={assets[a]:int(holdings[:,a].sum()) for a in range(len(assets))}))
        attribution.append(dict(date=str(dates[i]),**{strategies[s]:float(pnl[s]) for s in range(len(strategies))}))
        if not np.isclose(nav-config.initial_cash,float(cumulative.sum()),atol=1e-6,rtol=1e-10):
            raise ValueError('Account attribution did not reconcile')
        desired=targets[i]*max(nav,0)/px
        if not np.isfinite(desired).all() or np.max(np.abs(desired))>1e12:raise ValueError('Whole-share sizing exceeds numerical bounds')
        pending=np.trunc(desired).astype(np.int64)
        if liquidate and i==stop-1:pending[:]=0  # Fold end was scheduled before the run.
    return dict(metrics={**performance([r['equity'] for r in rows],config.annualization),
                         'commission':total_fees,'slippage':total_slippage,'borrow':total_borrow,
                         'accepted_rebalances':accepted_count,'rejected_rebalances':rejected_count},
                equity=rows,trades=trades,attribution=attribution,configuration=config.model_dump())


ACCOUNT_LIMITATIONS=[
    'Signals observe closing prices; whole-share target quantities are frozen then and executed no earlier than the next observed close with adverse slippage and commission. Closing-price liquidity is assumed, not established by these histories.',
    'Rebalances are atomic across all strategy sleeves and legs: the entire request is rejected if cash, short collateral or gross exposure cannot support it. Sleeves are not netted for fees, borrow or collateral. These are conservative research assumptions, not broker settlement or margin rules.',
    'Short borrow is charged each observation at the configured annual rate divided by annualization. Availability, changing borrow fees, cash interest, dividends outside adjusted history and jurisdiction-specific taxes are not modeled. Market moves may create deficits; they remain visible.',
    'No live orders are placed. Backtests in adjusted-price units assume those units can be traded and rounded as shares; they are not a reconstruction of raw historical entitlements or executable broker contracts.'
]
