"""Project 01's strategy families with training-only HMM forward filtering."""
import warnings
import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import StandardScaler
from scipy.special import logsumexp
from pydantic import Field

from .cointegration import estimate,spread_targets
from .equity_account import AccountConfig,simulate_account,funding_exposure,ACCOUNT_LIMITATIONS
from .origins.regime.strategies.momentum import MomentumStrategy
from .origins.regime.strategies.mean_reversion import MeanReversionStrategy

STRATEGIES=['momentum','mean_reversion','statistical_arbitrage']
BUDGETS={'high_volatility':np.array([.1,.1,.1]),'trend':np.array([.65,.15,.2]),'range':np.array([.15,.45,.4])}


class RegimeConfig(AccountConfig):
    history_id: str = ''
    initial_train: int = Field(252,ge=160,le=1000)
    refit_every: int = Field(63,ge=20,le=252)
    seed: int = Field(42,ge=0,le=2**31-1)
    iterations: int = Field(200,ge=50,le=500)


def forward_step(prior,log_emission,transition=None):
    """P(state_t | observations through t), never backward smoothed."""
    prior=np.asarray(prior,float)
    if transition is not None:prior=prior@np.asarray(transition,float)
    with np.errstate(divide='ignore'):joint=np.log(prior)+np.asarray(log_emission,float)
    normalizer=logsumexp(joint)
    if not np.isfinite(normalizer):raise ValueError('Invalid HMM filtering likelihood')
    return np.exp(joint-normalizer)


def emissions(observed,means,covariances):
    x=np.atleast_2d(observed);result=np.empty((len(x),len(means)))
    for s,(mean,cov) in enumerate(zip(means,covariances)):
        factor=np.linalg.cholesky(cov)
        residual=np.linalg.solve(factor,(x-mean).T)
        result[:,s]=-.5*(len(mean)*np.log(2*np.pi)+2*np.log(np.diag(factor)).sum()+(residual**2).sum(axis=0))
    return result


def features(prices):
    # Equal-weight geometric price index; all rolling windows end at this close.
    market=pd.Series(np.log(np.asarray(prices,float)).mean(axis=1));daily=market.diff()
    return pd.DataFrame({'daily_return':daily,'volatility_20':daily.rolling(20).std(),
        'momentum_20':market.diff(20),'trend_20_60':market.rolling(20).mean()-market.rolling(60).mean()})


def regimes(config,history,frame,cancel=lambda:False,progress=lambda *_:None):
    assets=history['assets'];prices=frame[assets].to_numpy(float);dates=frame.date.tolist();n=len(prices)
    if len(assets)<2 or n<config.initial_train+10 or n>2000:
        raise ValueError('HMM research needs 2–12 assets, ten test observations, and at most 2,000 total observations')
    refits=list(range(config.initial_train-1,n,config.refit_every))
    if len(refits)*config.iterations>10000:raise ValueError('Reduce HMM refits or iterations to at most 10,000 total EM iterations')
    f=features(prices);price_frame=pd.DataFrame(prices,columns=assets)
    momentum=MomentumStrategy(short_window=20,long_window=60).generate_positions(price_frame).positions.to_numpy()/len(assets)
    mr=MeanReversionStrategy(window=20,entry_threshold=1.5,exit_threshold=.5).generate_positions(price_frame).positions.to_numpy()
    # Equal gross allocation among active mean-reversion positions; flat if none.
    mr=np.divide(mr,np.abs(mr).sum(axis=1,keepdims=True),out=np.zeros_like(mr),where=np.abs(mr).sum(axis=1,keepdims=True)>0)
    targets=np.zeros((n,3,len(assets)));static=np.zeros_like(targets);probabilities=[];fits=[];labels={}
    scale_exposure=funding_exposure(config)
    for fit_number,start in enumerate(refits):
        if cancel():raise InterruptedError()
        stop=min(start+config.refit_every,n)-1
        training=f.iloc[:start+1].dropna()
        if (training.std()<1e-12).any():raise ValueError('HMM training features are constant or degenerate')
        scaler=StandardScaler();scaled=scaler.fit_transform(training)
        model=GaussianHMM(n_components=3,covariance_type='full',n_iter=config.iterations,
                          min_covar=1e-4,tol=1e-4,random_state=(config.seed+fit_number)%(2**31))
        with warnings.catch_warnings(record=True) as notes:
            warnings.simplefilter('always');model.fit(scaled)
        parameters=[model.startprob_,model.transmat_,model.means_,model.covars_]
        if any(not np.isfinite(p).all() for p in parameters):raise ValueError('Nonfinite HMM parameters; fit rejected')
        if not np.allclose(model.transmat_.sum(axis=1),1) or not np.isclose(model.startprob_.sum(),1):
            raise ValueError('HMM probabilities do not normalize')
        train_emissions=emissions(scaled,model.means_,model.covars_)
        posterior=model.startprob_
        for j,e in enumerate(train_emissions):posterior=forward_step(posterior,e,model.transmat_ if j else None)
        original_means=scaler.inverse_transform(model.means_)
        high=int(np.argmax(original_means[:,1]));remaining=[s for s in range(3) if s!=high]
        trend=max(remaining,key=lambda s:original_means[s,2]);range_state=next(s for s in remaining if s!=trend)
        state_labels={high:'high_volatility',trend:'trend',range_state:'range'}
        budgets=np.array([BUDGETS[state_labels[s]] for s in range(3)])
        cointegration=estimate(prices[:start+1])
        arb=np.zeros((n,1,len(assets)))
        if cointegration['eligible']:
            segment,_=spread_targets(prices[:stop+1],assets,cointegration['weights'],start,stop,exposure=1.)
            arb[:stop+1]=segment
        log_history=[float(v) for v in model.monitor_.history]
        change=log_history[-1]-log_history[-2] if len(log_history)>1 else None
        fit_converged=bool(change is not None and abs(change)<model.tol)
        fits.append(dict(fit=fit_number,first_date=dates[int(training.index[0])],last_date=dates[start],
            first_eligible_fill=dates[start+1] if start+1<n else None,observations=len(training),
            scaler_mean=scaler.mean_.tolist(),scaler_scale=scaler.scale_.tolist(),
            start_probabilities=model.startprob_.tolist(),transition=model.transmat_.tolist(),
            means=model.means_.tolist(),covariances=model.covars_.tolist(),state_labels={str(k):v for k,v in state_labels.items()},
            log_likelihood=log_history,converged=fit_converged,
            status='likelihood tolerance reached' if fit_converged else 'likelihood tolerance not reached; exploratory fit',
            warnings=sorted({str(w.message) for w in notes}),cointegration=cointegration))
        for i in range(start,stop+1):
            if cancel():raise InterruptedError()
            if i>start:
                x=scaler.transform(f.iloc[[i]])
                posterior=forward_step(posterior,emissions(x,model.means_,model.covars_)[0],model.transmat_)
            allocation=posterior@budgets*scale_exposure
            signals=np.stack([momentum[i],mr[i],arb[i,0]])
            targets[i]=signals*allocation[:,None]
            static[i]=signals*(scale_exposure/3)
            labels[i]=state_labels[int(np.argmax(posterior))]
            probabilities.append(dict(date=dates[i],fit=fit_number,regime=labels[i],
                **{state_labels[s]:float(posterior[s]) for s in range(3)},
                **{STRATEGIES[s]+'_budget':float(allocation[s]) for s in range(3)}))
        progress(fit_number+1,len(refits))
    account=simulate_account(prices,dates,targets,STRATEGIES,assets,config,config.initial_train-1,cancel=cancel)
    baseline=simulate_account(prices,dates,static,STRATEGIES,assets,config,config.initial_train-1,cancel=cancel)
    equity=account['equity'];attrib=account['attribution'];conditional=[];strategy_totals=[]
    # Assign every interval to the filtered state available at its starting close.
    for name in BUDGETS:
        indices=[j for j in range(1,len(equity)) if labels[config.initial_train-2+j]==name]
        returns=np.array([(equity[j]['equity']/equity[j-1]['equity']-1) if equity[j-1]['equity']>0 else 0. for j in indices])
        std=float(returns.std(ddof=1)) if len(returns)>1 else 0.
        conditional.append(dict(regime=name,observations=len(indices),
            sharpe=float(returns.mean()/std*np.sqrt(config.annualization)) if std>1e-12 and not account['metrics']['insolvent'] else None,
            worst_account_drawdown_percent=min((equity[j]['drawdown_percent'] for j in indices),default=None),
            net_pnl=sum(sum(attrib[j][s] for s in STRATEGIES) for j in indices),
            **{s:sum(attrib[j][s] for j in indices) for s in STRATEGIES}))
    for s in STRATEGIES:strategy_totals.append(dict(strategy=s,net_pnl=sum(row[s] for row in attrib)))
    final=equity[-1];nav=final['equity']
    allocation=dict(history_id=config.history_id,as_of=dates[-1],
        weights={a:final['positions'][a]*float(prices[-1,j])/nav for j,a in enumerate(assets)} if nav>0 else {},
        selection='Actual final marked whole-share net holdings; no liquidation assumed') if nav>0 else None
    return dict(name=('SYNTHETIC · ' if history['synthetic'] else '')+'HMM multi-strategy',
        synthetic=history['synthetic'],currency=history['currency'],history_id=config.history_id,
        fits=fits,allocation=allocation,baseline_account=baseline,
        results={'HMM allocation':{'metrics':account['metrics'],'equity':equity,'trades':account['trades'],
            'attribution':attrib,'strategy_totals':strategy_totals,'regime_performance':conditional,'regimes':probabilities,
            'fit_diagnostics':[dict(fit=f['fit'],first_date=f['first_date'],last_date=f['last_date'],
                first_eligible_fill=f['first_eligible_fill'],observations=f['observations'],status=f['status'],
                cointegration_eligible=f['cointegration']['eligible'],cointegration_method=f['cointegration']['method'],
                warnings=f['warnings']) for f in fits],
            'comparison':[dict(strategy='dynamic HMM',**account['metrics']),dict(strategy='static equal budgets',**baseline['metrics'])],
            'comparison_equity':[dict(date=a['date'],dynamic=a['equity'],static=b['equity']) for a,b in zip(equity,baseline['equity'])]}},
        charts=[dict(section='HMM allocation',table='comparison_equity',keys=['dynamic','static'],label='Out-of-sample equity · HMM versus static budgets'),
            dict(section='HMM allocation',table='regimes',keys=list(BUDGETS),label='Filtered regime probabilities'),
            dict(section='HMM allocation',table='regimes',keys=[s+'_budget' for s in STRATEGIES],label='Strategy gross exposure budgets'),
            dict(section='HMM allocation',table='equity',keys=['drawdown_percent'],label='Account drawdown (%)')],
        limitations=ACCOUNT_LIMITATIONS+[
            'Adapted from project 01: three-state full-covariance Gaussian HMM, expanding training refits, standardized equal-weight market log return, 20-observation volatility/momentum and 20/60 trend features. Only observations available at each decision close enter fitting or forward filtering; no evaluation-period backward smoothing or Viterbi decoding.',
            'Training emission means label the highest-volatility state, the strongest-momentum remaining state and the remaining range state. Labels are relative heuristics, not known economic truth. Likelihood histories, convergence status and parameters are frozen per fit; unconverged finite fits remain explicitly exploratory.',
            'Source moving-average momentum uses 20/60 windows. Source mean reversion uses 20-observation z-scores with entry 1.5 and exit 0.5. EG/Johansen statistical arbitrage is recalibrated only at HMM refits, uses prior-window spread normalization and resets its signal state on refit. Failed cointegration assigns that budget to cash.',
            'Probabilities blend fixed strategy budgets: trend 65/15/20%, range 15/45/40%, high volatility 10/10/10%, then apply funding headroom. Static equal budgets use the identical causal strategy signals and account assumptions; neither allocation policy is optimized on test returns.',
            'Regime Sharpe is conditional on intervals whose starting-close filtered state has that label, annualized by the configured observation count. Regime drawdown is the worst actual portfolio drawdown observed in those intervals, not a separately compounded hypothetical state portfolio. Sleeve and state P&L include costs and reconcile to the account.',
            'Final net marked holdings can feed risk simulation as a frozen allocation. Market moves can breach account caps; downstream risk validation may reject an unsupported allocation. This does not change a running deployment.'])
