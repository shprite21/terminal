import numpy as np
import pandas as pd
import pytest
import os
import subprocess
import sys
from scipy.stats import multivariate_normal

from evidence.storage import Store,canonical
from qresearch.history import ScenarioConfig,scenario
from qresearch.equity_account import AccountConfig,simulate_account,funding_exposure,performance
from qresearch.cointegration import estimate,spread_targets
from qresearch.basket import BasketConfig,basket
from qresearch.regimes import RegimeConfig,regimes,forward_step,emissions,STRATEGIES
from qresearch.risk_simulation import RiskConfig
from qresearch.service import run
from qresearch.replay import replay


def fixture(n=360):
    rng=np.random.default_rng(11)
    common=4+np.cumsum(rng.normal(.001,.012,n));residual=np.zeros(n)
    for i in range(1,n):residual[i]=.3*residual[i-1]+rng.normal(0,.02)
    frame=pd.DataFrame({'date':pd.bdate_range('2000-01-03',periods=n).strftime('%Y-%m-%d'),
                        'A':np.exp(common+residual),'B':np.exp(common)})
    return {'assets':['A','B'],'currency':'USD','synthetic':True},frame


def test_shared_account_independent_cash_positions_and_attribution():
    prices=np.array([[100,50],[102,49],[101,52],[99,51],[103,48]],float)
    dates=[f'2000-01-0{i}' for i in range(1,6)]
    targets=np.zeros((5,2,2));targets[:,0,0]=.3;targets[:,1,1]=-.25
    config=AccountConfig(initial_cash=10000)
    result=simulate_account(prices,dates,targets,['long','short'],['A','B'],config,liquidate=True)
    holdings=np.zeros((2,2));cash=10000
    for i,row in enumerate(result['equity']):
        if i:cash-=float((np.maximum(-holdings,0)*prices[i-1]).sum())*.03/252
        for trade in [t for t in result['trades'] if t['date']==row['date']]:
            assert trade['signal_date']<trade['date'] and isinstance(trade['quantity'],int)
            if trade['accepted']:
                s=['long','short'].index(trade['strategy']);a=['A','B'].index(trade['asset'])
                cash-=trade['quantity']*trade['price']+trade['commission'];holdings[s,a]+=trade['quantity']
        assert row['cash']==pytest.approx(cash)
        assert row['equity']==pytest.approx(cash+(holdings*prices[i]).sum())
        assert row['reserve']==pytest.approx((np.maximum(-holdings,0)*prices[i]).sum()*1.5)
        assert row['free_cash']>=0
        assert sum(sum(v for k,v in a.items() if k!='date') for a in result['attribution'][:i+1])==pytest.approx(row['equity']-10000)
    assert result['equity'][-1]['positions']=={'A':0,'B':0}
    assert result['trades'][0]['quantity']==30 # Quantity frozen at 100, not recomputed at 102.
    assert result['metrics']['commission']>0 and result['metrics']['borrow']>0


def test_account_rejects_unfunded_gap_and_does_not_change_past():
    prices=np.array([[100.],[200.],[200.],[210.]])
    targets=np.ones((4,1,1))*.8
    cfg=AccountConfig(initial_cash=1000)
    result=simulate_account(prices,['a','b','c','d'],targets,['s'],['A'],cfg)
    assert result['equity'][1]['rebalance'].startswith('rejected')
    assert result['equity'][1]['cash']==1000 and result['equity'][1]['commission']==0
    changed=prices.copy();changed[-1]*=5
    alternate=simulate_account(changed,['a','b','c','d'],targets,['s'],['A'],cfg)
    assert result['equity'][:-1]==alternate['equity'][:-1]


def test_account_boundaries_metrics_and_cancellation():
    assert funding_exposure(AccountConfig(short_collateral=1))==pytest.approx(.8)
    assert funding_exposure(AccountConfig(short_collateral=3))==pytest.approx(.4)
    m=performance([100.,110.,99.,108.9],annualization=3)
    assert m['calmar']==pytest.approx(.089/.1)
    assert m['sharpe']==pytest.approx(np.mean([.1,-.1,.1])/np.std([.1,-.1,.1],ddof=1)*np.sqrt(3))
    assert performance([100.,100.,100.])['calmar'] is None
    with pytest.raises(InterruptedError):
        simulate_account([[100.],[100.]],['a','b'],np.zeros((2,1,1)),['s'],['A'],AccountConfig(),cancel=lambda:True)
    h,f=fixture()
    with pytest.raises(InterruptedError):basket(BasketConfig(),h,f,cancel=lambda:True)
    with pytest.raises(InterruptedError):regimes(RegimeConfig(),h,f,cancel=lambda:True)


def test_cointegration_estimates_and_shifted_spread_normalization():
    h,f=fixture();prices=f[h['assets']].to_numpy()
    eg=estimate(prices,'eg');jo=estimate(prices,'johansen')
    assert eg['eligible'] and jo['eligible']
    assert eg['weights']==pytest.approx([.5,-.5],abs=.03)
    assert jo['rank']==1
    w=np.array(eg['weights']);_,diag=spread_targets(prices,h['assets'],w,250,359)
    spread=np.log(prices)@w
    assert diag[0]['z_score']==pytest.approx((spread[250]-spread[230:250].mean())/spread[230:250].std())
    assert not estimate(np.ones((100,2)))['eligible']


def test_forward_filter_and_gaussian_emissions_match_independent_formulas():
    prior=np.array([.6,.4]);transition=np.array([[.9,.1],[.2,.8]]);likelihood=np.array([.3,.7])
    expected=(prior@transition)*likelihood;expected/=expected.sum()
    assert forward_step(prior,np.log(likelihood),transition)==pytest.approx(expected)
    x=np.array([[1.,2.],[-.2,.4]]);means=np.array([[0.,0.],[1.,1.]])
    cov=np.array([[[1.,.3],[.3,2.]],[[.5,0],[0,.2]]])
    observed=emissions(x,means,cov)
    for s in range(2):assert observed[:,s]==pytest.approx(multivariate_normal.logpdf(x,means[s],cov[s]))


def test_basket_nested_selection_future_invariance_and_costs():
    h,f=fixture();cfg=BasketConfig(train_window=220,validation_window=60,test_window=70,trials=8)
    original=basket(cfg,h,f)
    changed=f.copy();changed.loc[220:,'A']*=np.linspace(1,2,len(f)-220)
    alternate=basket(cfg,h,changed)
    first=original['folds'][0];other=alternate['folds'][0]
    assert first['selected'] is not None
    for key in ['selected','inner_cointegration','outer_cointegration','outer_weights','outer_residual_adf']:
        assert first[key]==other[key]
    trials=original['results']['Basket comparison']['trials']
    assert [t for t in trials if t['fold']==0]==[t for t in alternate['results']['Basket comparison']['trials'] if t['fold']==0]
    assert any(t['status']=='COMPLETE' for t in trials)
    for fold in original['folds']:
        assert fold['calibration_last']<fold['validation_first']<=fold['validation_last']<fold['test_first']
        a,b=fold['accounts'].values()
        assert [r['date'] for r in a['equity']]==[r['date'] for r in b['equity']]
        for account in [a,b]:
            assert all(v==0 for v in account['equity'][-1]['positions'].values())
            assert all(t['signal_date']<t['date'] for t in account['trades'])
    assert any(fold['accounts']['optimized']['metrics']['commission']>0 for fold in original['folds'])
    for fold in original['folds']:
        if fold['evaluation_status']['optimized'].startswith('cash:'):
            assert fold['accounts']['optimized']['metrics']['commission']==0


def test_hmm_causal_fit_filter_and_regime_attribution():
    h=scenario(ScenarioConfig(observations=340,assets=3));f=pd.DataFrame(h['results']['History']['observations'])
    cfg=RegimeConfig(initial_train=200,refit_every=70,iterations=80)
    original=regimes(cfg,h,f)
    changed=f.copy();changed.loc[290:,'SYNTH1']*=1.5
    alternate=regimes(cfg,h,changed)
    a=original['results']['HMM allocation'];b=alternate['results']['HMM allocation'];cutoff=f.date.iloc[290]
    for key in ['equity','regimes','trades','attribution']:
        assert [r for r in a[key] if r['date']<cutoff]==[r for r in b[key] if r['date']<cutoff]
    assert original['fits'][:2]==alternate['fits'][:2]
    assert all(fit['last_date']<fit['first_eligible_fill'] for fit in original['fits'] if fit['first_eligible_fill'])
    for row in a['regimes']:assert sum(row[k] for k in ['trend','range','high_volatility'])==pytest.approx(1)
    assert np.std([r['momentum_budget'] for r in a['regimes']])>.001
    assert {t['strategy'] for t in a['trades']}==set(STRATEGIES)
    assert sum(r['net_pnl'] for r in a['regime_performance'])==pytest.approx(a['metrics']['net_pnl'])
    assert sum(r['observations'] for r in a['regime_performance'])==140
    assert sum(r['net_pnl'] for r in a['strategy_totals'])==pytest.approx(a['metrics']['net_pnl'])


@pytest.mark.parametrize('action,config',[
    ('hmm-multi-strategy',RegimeConfig()),
    ('basket-walk-forward',BasketConfig(train_window=220,validation_window=60,test_window=70,trials=6))])
def test_saved_strategy_replay_and_frozen_risk_allocation(tmp_path,action,config):
    db=Store(tmp_path/'db');key=run(db,'history-scenario',ScenarioConfig(observations=600,assets=3),lambda:False,lambda *_:None)
    config=config.model_copy(update={'history_id':key})
    result_key=run(db,action,config,lambda:False,lambda *_:None);result=db.get(result_key,'quant_result')
    path=tmp_path/'result.json';path.write_text(canonical(result),encoding='utf-8')
    assert replay(path)['verified']
    # Exercise a fresh process with a different ambient numerical thread count.
    env={**os.environ,'OMP_NUM_THREADS':'4','OPENBLAS_NUM_THREADS':'4','MKL_NUM_THREADS':'4'}
    check=subprocess.run([sys.executable,'-m','qresearch.replay',str(path)],env=env,capture_output=True,text=True,timeout=90)
    assert check.returncode==0,check.stderr
    risk_key=run(db,'multi-asset-risk',RiskConfig(history_id=key,source_result_id=result_key,horizon=2),lambda:False,lambda *_:None)
    risk=db.get(risk_key,'quant_result')
    assert risk['calibration']['weights']==result['allocation']['weights']
    assert risk['inputs']['allocation_source']==result
