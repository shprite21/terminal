import math
import json

import numpy as np
import pytest
from pydantic import ValidationError

from qresearch.options import PricingConfig, values
from qresearch.option_account import Account
from qresearch.option_simulation import SimulationConfig, simulate


def test_black_scholes_reference_and_independent_greek_finite_differences():
    for kind in ['call', 'put']:
        x = [100., 100., 1., .05, .2, kind]
        v = values(*x)
        assert v['price'] == pytest.approx(10.450583572185565 if kind=='call' else 5.573526022256971)
        for index, greek, sign in [(0,'delta',1),(2,'theta',-1),(3,'rho',1),(4,'vega',1)]:
            h = 1e-4
            lower, upper = x.copy(), x.copy()
            lower[index] -= h; upper[index] += h
            expected = sign*(values(*upper)['price']-values(*lower)['price'])/(2*h)
            assert v[greek] == pytest.approx(expected, rel=1e-6)
        h = .01
        assert v['gamma'] == pytest.approx((values(100+h,*x[1:])['price']-2*v['price']+values(100-h,*x[1:])['price'])/h**2,rel=1e-6)


def test_parity_and_deterministic_forward_moneyness():
    for s,k,t,r,vol in [(80,110,.3,-.02,.8),(100,102,1,.1,0),(105,100,1,-.1,0),(100,100,1e-10,0,1e-10)]:
        call, put = values(s,k,t,r,vol,'call'), values(s,k,t,r,vol,'put')
        assert call['price']-put['price'] == pytest.approx(s-k*math.exp(-r*t), abs=2e-12)
        assert call['delta']-put['delta'] == pytest.approx(1)
    v = values(100,102,1,.1,0)
    assert v['delta'] == 1  # spot below strike, but forward above strike
    assert v['rho'] == pytest.approx(102*math.exp(-.1))
    assert v['theta'] == pytest.approx(-.1*v['rho'])
    kink=values(100,100,0,0,.2)
    assert kink['price']==0 and kink['delta']==.5 and kink['gamma'] is None


@pytest.mark.parametrize('change',[{'spot':float('nan')},{'rate':float('inf')},{'volatility':-1},{'option_type':'binary'}])
def test_invalid_pricing_inputs(change):
    with pytest.raises(ValidationError): PricingConfig(**change)


def test_account_rejects_unfunded_and_noninteger_trades_without_mutation():
    a=Account(1000,100,100,'call',2)
    before=vars(a).copy()
    assert not a.transact('option',-1,2,1,100)['accepted']
    assert not a.transact('stock',11,100,0,100)['accepted']
    assert vars(a)==before
    with pytest.raises(ValueError): a.transact('stock',.5,100,0,100)
    assert a.transact('option',1,2,1,100)['accepted']
    assert a.cash==799 and a.contracts==1 and a.fees==1


def test_reproducibility_timing_inventory_and_cash_reconcile():
    config=SimulationConfig(steps=150,arrival_probability=1,hedge_threshold_shares=0)
    result=simulate(config)
    assert result==simulate(config)
    # Standard JSON numeric/bool types, never strings introduced by default=str.
    parsed=json.loads(json.dumps(result,allow_nan=False))
    run=parsed['results']['Options simulation']; rows=run['equity']; trades=run['trades']
    cash=config.initial_cash; shares=contracts=0; fees=0
    assert trades and any(t['asset']=='stock' and t['accepted'] for t in trades)
    for row in rows:
        for t in [t for t in trades if t['step']==row['step']]:
            assert t['signal_step'] < t['step']
            assert isinstance(t['accepted'], bool)
            if t['accepted']:
                multiplier=config.multiplier if t['asset']=='option' else 1
                expected=-t['quantity']*t['price']*multiplier-t['fee']
                assert t['cash_flow']==pytest.approx(expected)
                cash+=expected; fees+=t['fee']
                if t['asset']=='option':contracts+=t['quantity']
                else:shares+=t['quantity']
        assert row['cash']==pytest.approx(cash)
        assert row['fees']==pytest.approx(fees)
        assert row['cash']>=0
        assert row['shares']==shares and row['contracts']==contracts
        assert isinstance(shares,int) and abs(contracts)<=config.max_contracts
        assert row['equity']==pytest.approx(cash+shares*row['spot']+contracts*config.multiplier*row['fair_value'])
    m=run['metrics']
    assert m['option_pnl']+m['hedge_pnl']==pytest.approx(m['net_pnl'])
    assert m['delta_rmse_shares']==pytest.approx(np.sqrt(np.mean(np.array([r['net_delta'] for r in rows[1:]])**2)))
    for previous,current in zip(rows,rows[1:]):
        expected=(previous['shares']*(current['spot']-previous['spot'])
                  +previous['contracts']*config.multiplier*(current['fair_value']-previous['fair_value']))
        assert current['hedging_error']==pytest.approx(expected)


def test_cpp_reference_values_and_shared_boundary_masks():
    from pathlib import Path
    from qresearch.option_benchmark import compile_cpp,cpp_values
    binary,_=compile_cpp(Path(__file__).resolve().parents[3]/'.data/q-research-validation/cpp')
    inputs=[[100.,100.,1.,.05,.2,'call'],[100.,100.,1.,.05,.2,'put'],
            [100.,102.,1.,.1,0.,'call'],[100.,100.,0.,0.,.2,'call']]
    result=cpp_values(binary,inputs)['outputs']
    assert result[0][0]==pytest.approx(10.450583572185565)
    assert result[1][0]==pytest.approx(5.573526022256971)
    assert result[2][1]==1 and result[2][5]==pytest.approx(102*math.exp(-.1))
    assert result[3]==[0,.5,None,None,None,0]
    # Independent finite differences applied to the native executable itself.
    perturb=[[100.+h,100.,1.,.05,.2,'call'] for h in [-.01,0,.01]]
    native=cpp_values(binary,perturb)['outputs']
    assert native[1][1]==pytest.approx((native[2][0]-native[0][0])/.02,rel=1e-6)
    assert native[1][2]==pytest.approx((native[2][0]-2*native[1][0]+native[0][0])/.01**2,rel=1e-6)


def test_future_path_changes_cannot_change_past_or_the_pending_hedge_target():
    config=SimulationConfig(steps=60,arrival_probability=1,hedge_threshold_shares=0)
    path=np.linspace(100,103,61)
    altered=path.copy(); altered[31:]*=1.4
    original=simulate(config,spots=path)['results']['Options simulation']
    changed=simulate(config,spots=altered)['results']['Options simulation']
    assert original['equity'][:31]==changed['equity'][:31]
    assert [t for t in original['trades'] if t['step']<=30]==[t for t in changed['trades'] if t['step']<=30]
    for run in [original,changed]:
        for trade in run['trades']:
            if trade['asset']=='stock':
                prior=run['equity'][trade['signal_step']]
                assert trade['quantity']==prior['hedge_target']-prior['shares']


def test_empty_flow_and_cancellation_and_expiry_bounds():
    result=simulate(SimulationConfig(steps=10,arrival_probability=0))['results']['Options simulation']
    assert result['metrics']['net_pnl']==0 and result['trades']==[]
    with pytest.raises(InterruptedError):simulate(SimulationConfig(),cancel=lambda:True)
    with pytest.raises(ValidationError):SimulationConfig(maturity_years=0)
    with pytest.raises(ValidationError):SimulationConfig(steps=252,steps_per_day=1,maturity_years=1)
