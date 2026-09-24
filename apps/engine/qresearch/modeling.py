"""Q adaptations of project 04's efficient-frontier and chronological ARIMA notebooks."""
import warnings
from inspect import signature
from typing import Literal

import numpy as np
from pydantic import BaseModel,ConfigDict,Field
from scipy.optimize import minimize
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.stattools import acf,adfuller


class FrontierConfig(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False,validate_default=True)
    history_id: str = ''
    max_weight: float = Field(1,gt=0,le=1)
    shrinkage: float = Field(.1,ge=0,le=1)
    points: int = Field(25,ge=2,le=100)
    annualization: int = Field(252,ge=1,le=366)
    risk_free_rate: float = Field(0,ge=-.2,le=1)


def efficient_weights(mean,covariance,cap,points,cancel=lambda:False,progress=lambda *_:None):
    mean=np.asarray(mean,float);cov=np.asarray(covariance,float);n=len(mean)
    if cap*n<1-1e-12:raise ValueError('Asset count × maximum weight must be at least 1')
    if cov.shape!=(n,n) or not np.isfinite(cov).all() or not np.isfinite(mean).all():raise ValueError('Invalid moments')
    if not np.allclose(cov,cov.T) or np.linalg.eigvalsh(cov).min() < -1e-10:raise ValueError('Covariance must be positive semidefinite')
    scaled=cov/max(float(np.diag(cov).max()),1e-12)
    def solve(initial,target=None):
        constraints=[dict(type='eq',fun=lambda w:float(w.sum()-1),jac=lambda w:np.ones(n))]
        if target is not None:constraints.append(dict(type='eq',fun=lambda w:float(w@mean-target),jac=lambda w:mean))
        opt=minimize(lambda w:float(w@scaled@w),initial,jac=lambda w:2*scaled@w,
                     method='SLSQP',bounds=[(0,cap)]*n,constraints=constraints,
                     options={'ftol':1e-12,'maxiter':1000})
        w=opt.x
        if (not opt.success or not np.isfinite(w).all() or abs(w.sum()-1)>1e-8 or w.min() < -1e-9
                or w.max()>cap+1e-9 or (target is not None and abs(w@mean-target)>1e-8)):
            raise ValueError('Efficient-frontier optimization did not satisfy its constraints')
        return w
    minimum=solve(np.ones(n)/n)
    maximum=np.zeros(n);remaining=1.
    for i in np.argsort(-mean,kind='stable'):
        maximum[i]=min(cap,remaining);remaining-=maximum[i]
    low,high=float(minimum@mean),float(maximum@mean)
    result=[]
    for i,alpha in enumerate(np.linspace(0,1,points) if high-low>1e-10 else [0.]):
        if cancel():raise InterruptedError()
        target=low+alpha*(high-low)
        w=minimum if alpha==0 else solve((1-alpha)*minimum+alpha*maximum,target)
        result.append((w,float(w@mean),float(np.sqrt(max(w@cov@w,0.)))))
        progress(i+1,points)
    return result


def frontier(config,history,frame,cancel=lambda:False,progress=lambda *_:None):
    assets=history['assets'];prices=frame[assets].to_numpy(float)
    returns=prices[1:]/prices[:-1]-1
    mean=returns.mean(axis=0)*config.annualization
    sample=np.atleast_2d(np.cov(returns,rowvar=False,ddof=1))*config.annualization
    cov=(1-config.shrinkage)*sample+config.shrinkage*np.diag(np.diag(sample))
    solutions=efficient_weights(mean,cov,config.max_weight,config.points,cancel,progress)
    rows=[dict(point=i,annual_return=ret,annual_volatility=vol,
               sharpe=(ret-config.risk_free_rate)/vol if vol>1e-12 else None,
               **{a:float(w[j]) for j,a in enumerate(assets)}) for i,(w,ret,vol) in enumerate(solutions)]
    weights={a:float(solutions[0][0][j]) for j,a in enumerate(assets)}
    return dict(name=('SYNTHETIC · ' if history['synthetic'] else '')+'Efficient frontier',synthetic=history['synthetic'],
        currency=history['currency'],history_id=config.history_id,
        calibration=dict(first=frame.date.iloc[0],last=frame.date.iloc[-1],observations=len(frame),assets=assets,
                         annual_simple_mean=mean.tolist(),sample_covariance=sample.tolist(),used_covariance=cov.tolist()),
        allocation=dict(history_id=config.history_id,as_of=frame.date.iloc[-1],weights=weights,selection='minimum variance'),
        results={'Efficient frontier':{'metrics':{'minimum_volatility':rows[0]['annual_volatility'],'minimum_variance_return':rows[0]['annual_return']},
                                      'frontier':rows,'minimum_variance_weights':[dict(asset=a,weight=w) for a,w in weights.items()]}},
        charts=[dict(section='Efficient frontier',table='frontier',keys=['annual_return'],x='annual_volatility',label='Efficient frontier · annual expected return versus volatility')],
        limitations=['Adapted from project 04. Long-only fully invested mean–variance optimization using sample simple returns; annualized with the configured observation count. These are in-sample estimates, not proven future returns.',
                    'Shrinkage blends covariance toward its own diagonal, preserving units and asset variances. Each optimizer result must satisfy weight, budget and target-return constraints.',
                    'Only the efficient branch above the minimum-variance return is plotted. A zero-volatility Sharpe ratio is undefined and shown as null.',
                    'The saved minimum-variance weights can feed Q risk simulation. They are a frozen research allocation, not an executed account; no fees, turnover, liquidity or whole-share fills are assumed.'])


class ForecastConfig(BaseModel):
    model_config=ConfigDict(extra='forbid',validate_default=True)
    history_id: str = ''
    asset: str = ''
    target: Literal['price','return'] = 'price'
    p: int = Field(1,ge=0,le=4)
    d: int = Field(1,ge=0,le=2)
    q: int = Field(1,ge=0,le=4)
    test_observations: int = Field(63,ge=5,le=250)
    refit_every: int = Field(20,ge=1,le=100)


def stationarity(values):
    values=np.asarray(values,float)
    if np.ptp(values)<1e-12:
        return dict(status='constant series; ADF and ACF undefined',adf_statistic=None,p_value=None,
                    autocorrelation=[dict(lag=i,acf=None) for i in range(min(21,len(values)))])
    result_mode={'result_object':False} if 'result_object' in signature(adfuller).parameters else {}
    adf=adfuller(values,autolag='AIC',maxlag=min(10,len(values)//4-1),**result_mode)
    correlations=acf(values,nlags=min(20,len(values)-1),fft=False)
    return dict(status='computed',adf_statistic=float(adf[0]),p_value=float(adf[1]),
                used_lags=int(adf[2]),observations=int(adf[3]),
                autocorrelation=[dict(lag=i,acf=float(x)) for i,x in enumerate(correlations)])


def forecast(config,history,frame,cancel=lambda:False,progress=lambda *_:None):
    asset=config.asset or history['assets'][0]
    if asset not in history['assets']:raise ValueError('Select an asset from the frozen history')
    prices=frame[asset].to_numpy(float)
    series=prices if config.target=='price' else prices[1:]/prices[:-1]-1
    dates=frame.date.to_list() if config.target=='price' else frame.date.to_list()[1:]
    split=len(series)-config.test_observations
    if split<40 or len(series)>2000:raise ValueError('ARIMA needs at least 40 training observations and at most 2,000 total observations')
    training=series[:split]
    diagnostics=stationarity(training)
    differenced=stationarity(np.diff(training,n=config.d)) if config.d else diagnostics
    # Training-only scaling improves optimization of small return series.
    center=float(training.mean());scale=max(float(training.std()),1e-8)
    observed=((training-center)/scale).tolist()
    rows=[];fits=[];fit=None
    constant=np.ptp(training)<1e-12
    if constant:raise ValueError('ARIMA training series is constant; model estimation is undefined. Use the reported constant-history risk case instead.')
    for t in range(config.test_observations):
        if cancel():raise InterruptedError()
        if t%config.refit_every==0:
            with warnings.catch_warnings(record=True) as captured:
                warnings.simplefilter('always')
                fit=ARIMA(np.asarray(observed),order=(config.p,config.d,config.q)).fit(method_kwargs={'maxiter':200})
            converged=bool(fit.mle_retvals.get('converged',True))
            fits.append(dict(forecast_date=dates[split+t],fit_last_date=dates[split+t-1],observations=len(observed),
                             converged=converged,warnings=sorted({str(w.message) for w in captured})))
            if not converged:raise ValueError('ARIMA optimization did not converge; no validated forecast result was saved')
        predicted=float(fit.forecast(1)[0]*scale+center)
        actual=float(series[split+t]);naive=float(series[split+t-1])
        if not np.isfinite(predicted):raise ValueError('ARIMA forecast is non-finite')
        rows.append(dict(date=dates[split+t],information_through=dates[split+t-1],actual=actual,arima=predicted,
                         naive=naive,arima_error=actual-predicted,naive_error=actual-naive))
        # The observation is appended only AFTER its forecast has been recorded.
        standardized=(actual-center)/scale
        observed.append(standardized)
        fit=fit.append([standardized],refit=False)
        progress(t+1,config.test_observations)
    metrics={}
    for name in ['arima','naive']:
        errors=np.array([r[name+'_error'] for r in rows])
        metrics[name+'_rmse']=float(np.sqrt(np.mean(errors**2)))
        metrics[name+'_mae']=float(np.mean(np.abs(errors)))
    return dict(name=('SYNTHETIC · ' if history['synthetic'] else '')+asset+' · ARIMA versus naive',synthetic=history['synthetic'],
        history_id=config.history_id,calibration=dict(asset=asset,target=config.target,train_first=dates[0],train_last=dates[split-1],
            test_first=dates[split],test_last=dates[-1],training_observations=split,test_observations=len(rows),
            training_stationarity=diagnostics,differenced_training_stationarity=differenced),
        results={'Forecast validation':{'metrics':metrics,'forecasts':rows,'fits':fits,
                                       'training_acf':diagnostics['autocorrelation'],
                                       'differenced_training_acf':differenced['autocorrelation']}},
        charts=[dict(section='Forecast validation',table='forecasts',keys=['actual','arima','naive'],x='date',label='One-observation-ahead forecasts · '+config.target),
                dict(section='Forecast validation',table='forecasts',keys=['arima_error','naive_error'],x='date',label='Forecast errors on identical dates'),
                dict(section='Forecast validation',table='training_acf',keys=['acf'],x='lag',label='Training autocorrelation')],
        limitations=['Adapted from project 04. The specified ARIMA order is fixed before testing. Fits use only prior observations; between refits the model state updates after each observation without re-estimating parameters.',
            'ARIMA and the last-observation naive baseline are scored on every identical test date, including the first. RMSE and MAE use price units or fractional simple returns according to target.',
            'ADF/ACF diagnostics use training observations only; they do not guarantee future stationarity. Fit warnings remain recorded; nonconverged fits fail rather than being labeled validated.',
            'Forecasts are research estimates, not trade signals or return guarantees. Repeatedly selecting orders after viewing these test results consumes their independence. No execution, costs or new future calendar dates are inferred.'])
