"""Training-only EG/Johansen estimation and causal spread signals for Q."""
from inspect import signature
import warnings

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import coint,adfuller
from statsmodels.tsa.vector_ar.vecm import coint_johansen

from .origins.arbitrage.spread_builder import WeightedSpreadBuilder
from .origins.arbitrage.signals import SignalEngine


def normalize(weights):
    real=np.real_if_close(weights,tol=1000)
    if np.iscomplexobj(real):raise ValueError('Non-real cointegration weights')
    w=np.asarray(real,float)
    if not np.isfinite(w).all() or np.abs(w).sum()<1e-12:raise ValueError('Degenerate cointegration weights')
    w=w/np.abs(w).sum()
    if w[np.argmax(np.abs(w)>1e-10)]<0:w=-w
    return w


def estimate(prices,method='auto'):
    prices=np.asarray(prices,float);n=prices.shape[1]
    if n<2 or n>12 or len(prices)<80 or not np.isfinite(prices).all() or (prices<=0).any():
        raise ValueError('Cointegration needs 2–12 assets and at least 80 positive complete training observations')
    data=np.log(prices);chosen=('eg' if n==2 else 'johansen') if method=='auto' else method
    record=dict(method=chosen,observations=len(data),eligible=False,weights=None)
    if np.min(np.std(np.diff(data,axis=0),axis=0))<1e-10:
        return {**record,'reason':'Constant or deterministic training asset; no cointegration claim'}
    with warnings.catch_warnings(record=True) as notes:
        warnings.simplefilter('always')
        try:
            if chosen=='eg':
                statistic,p,critical=coint(data[:,0],data[:,1:],trend='c',autolag='aic',maxlag=min(10,len(data)//5))
                coefficients=np.linalg.lstsq(np.column_stack([np.ones(len(data)),data[:,1:]]),data[:,0],rcond=None)[0]
                w=normalize(np.r_[1.,-coefficients[1:]])
                record.update(statistic=float(statistic) if np.isfinite(statistic) else None,p_value=float(p) if np.isfinite(p) else None,
                              critical_values=np.asarray(critical).tolist(),eligible=bool(p<.05 and np.isfinite(statistic)))
            elif chosen=='johansen':
                result=coint_johansen(data,det_order=0,k_ar_diff=1)
                if not np.isfinite(result.lr1).all() or not np.isfinite(result.evec).all():
                    return {**record,'reason':'Nonfinite Johansen statistics; fit rejected'}
                # Sequential trace test stops at the first non-rejection.
                rank=0
                for stat,crit in zip(result.lr1,result.cvt[:,1]):
                    if stat<=crit:break
                    rank+=1
                w=normalize(result.evec[:,0])
                record.update(rank=rank,trace_statistics=result.lr1.tolist(),trace_critical_95=result.cvt[:,1].tolist(),
                              eligible=bool(0<rank<n))
            else:raise ValueError('Choose auto, eg or johansen')
            if np.std(data@w)<1e-8:record.update(eligible=False,reason='Degenerate spread variance')
            record['weights']=w.tolist()
        except np.linalg.LinAlgError:
            record.update(eligible=False,reason='Singular training regression or covariance')
    record['warnings']=sorted({str(w.message) for w in notes})
    return record


def residual_stationarity(prices,weights):
    spread=np.log(np.asarray(prices,float))@np.asarray(weights,float)
    if not np.isfinite(spread).all() or np.std(spread)<1e-8:return 1.
    kwargs={'result_object':False} if 'result_object' in signature(adfuller).parameters else {}
    return float(adfuller(spread,maxlag=min(10,len(spread)//5),autolag='AIC',**kwargs)[1])


def spread_targets(prices,assets,weights,start,stop,lookback=20,entry=2.,exit=.5,exposure=1.):
    frame=pd.DataFrame(prices,columns=assets)
    statistics=WeightedSpreadBuilder().compute_statistics(frame,dict(zip(assets,weights)),lookback)
    observed=statistics.z_score.iloc[start:stop+1]
    signal=SignalEngine().generate(observed,entry,exit)['signal'].to_numpy()
    targets=np.zeros((len(frame),1,len(assets)))
    targets[start:stop+1,0,:]=signal[:,None]*np.asarray(weights)[None,:]*exposure
    diagnostics=[dict(index=start+i,spread=float(statistics.spread.iloc[start+i]),
                      z_score=float(z) if np.isfinite(z) else None,signal=float(signal[i])) for i,z in enumerate(observed)]
    return targets,diagnostics
