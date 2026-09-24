"""Correlated multi-asset extension of project 04's historical-return Monte Carlo."""
import math

import numpy as np
from pydantic import BaseModel,ConfigDict,Field,model_validator


class RiskConfig(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False,validate_default=True)
    history_id: str = ''
    weights: dict[str,float] = Field(default_factory=dict)
    source_result_id: str = ''
    initial_value: float = Field(100_000,ge=1,le=1e10)
    paths: int = Field(10_000,ge=10_000,le=50_000)
    horizon: int = Field(63,ge=1,le=252)
    confidence: float = Field(.95,ge=.9,le=.999)
    volatility_shock: float = Field(2,ge=1,le=5)
    correlation_strength: float = Field(.9,ge=0,le=1)
    seed: int = Field(42,ge=0,le=2**32-1)

    @model_validator(mode='after')
    def memory_bound(self):
        if self.paths*self.horizon>5_000_000:raise ValueError('Limit paths × horizon to 5,000,000')
        return self


def tail_losses(losses,confidence):
    losses=np.asarray(losses,float)
    if losses.ndim!=1 or not len(losses) or not np.isfinite(losses).all() or not 0<confidence<1:
        raise ValueError('Finite losses and a confidence strictly between zero and one required')
    # Integrate the empirical upper tail, including fractional order-statistic
    # mass. This avoids bias from rounded tail sizes or duplicated quantiles.
    ordered=np.sort(losses)[::-1]; mass=(1-confidence)*len(losses)
    whole=int(math.floor(mass)); fraction=mass-whole
    es=(ordered[:whole].sum()+(fraction*ordered[whole] if fraction else 0))/mass
    return float(np.quantile(losses,confidence,method='linear')),float(es)


def covariance_factor(covariance):
    cov=np.atleast_2d(np.asarray(covariance,float))
    if cov.shape[0]!=cov.shape[1] or not np.isfinite(cov).all() or not np.allclose(cov,cov.T,atol=1e-14):
        raise ValueError('Finite symmetric covariance required')
    if (np.diag(cov)<0).any():raise ValueError('Negative variances are invalid')
    active=np.flatnonzero(np.diag(cov)>0)
    repaired=np.zeros_like(cov); factor=np.zeros_like(cov)
    adjustment=0.
    if len(active):
        std=np.sqrt(np.diag(cov)[active])
        corr=cov[np.ix_(active,active)]/np.outer(std,std)
        eigen,vectors=np.linalg.eigh((corr+corr.T)/2)
        if eigen.min() < -1e-8:raise ValueError('Covariance is not positive semidefinite')
        if eigen.min()<1e-10:
            corr=(vectors*np.maximum(eigen,1e-10))@vectors.T
            scale=np.sqrt(np.diag(corr));corr=corr/np.outer(scale,scale)
        block=corr*np.outer(std,std)
        repaired[np.ix_(active,active)]=block
        factor[np.ix_(active,active)]=np.linalg.cholesky(block)
        adjustment=float(np.max(np.abs(repaired-cov)))
    if not np.allclose(cov[~(np.diag(cov)>0)],0,atol=1e-14):
        raise ValueError('Zero-variance assets must have zero covariance')
    return repaired,factor,adjustment


def simulate_risk(config,history,frame,cancel=lambda:False,progress=lambda *_:None,*,allocation=None):
    assets=history['assets']; prices=frame[assets].to_numpy(float)
    weights=config.weights or {name:1/len(assets) for name in assets}
    if allocation is not None:
        if config.weights:raise ValueError('Choose explicit weights or a saved allocation, not both')
        if allocation['history_id']!=config.history_id or allocation['as_of']!=frame.date.iloc[-1]:
            raise ValueError('Saved allocation must match this history and its final observation date')
        weights=allocation['weights']
    if set(weights)!=set(assets):raise ValueError('Weights must name every selected asset exactly')
    w=np.array([weights[a] for a in assets],float)
    if not np.isfinite(w).all() or np.abs(w).sum()>2+1e-12:
        raise ValueError('Finite weights with gross exposure no greater than 2 required')
    returns=np.diff(np.log(prices),axis=0)
    mean=returns.mean(axis=0)
    cov=np.atleast_2d(np.cov(returns,rowvar=False,ddof=1))
    sd=np.sqrt(np.diag(cov))
    shock=(1-config.correlation_strength)*cov+config.correlation_strength*np.outer(sd,sd)
    scenarios={'Baseline':cov,'Volatility shock':cov*config.volatility_shock**2,
               'Correlation spike':shock,'Correlation breakdown':np.diag(np.diag(cov))}
    results={};charts=[];summary=[];matrices=[]
    for scenario_index,(name,candidate) in enumerate(scenarios.items()):
        repaired,factor,adjustment=covariance_factor(candidate)
        rng=np.random.default_rng(config.seed)  # Common random numbers across stresses.
        growth=np.ones((config.paths,len(assets)))
        equity=np.empty((config.paths,config.horizon+1));equity[:,0]=config.initial_value
        peak=equity[:,0].copy();drawdown=np.zeros(config.paths)
        for step in range(1,config.horizon+1):
            if cancel():raise InterruptedError()
            growth*=np.exp(mean+rng.standard_normal(growth.shape)@factor.T)
            equity[:,step]=config.initial_value*(1-w.sum()+growth@w)
            if not np.isfinite(equity[:,step]).all():raise ValueError('Simulated values exceeded numerical range')
            peak=np.maximum(peak,equity[:,step])
            drawdown=np.minimum(drawdown,equity[:,step]/peak-1)
            if step%10==0 or step==config.horizon:progress(scenario_index*config.horizon+step,4*config.horizon)
        losses=config.initial_value-equity[:,-1]
        var,es=tail_losses(losses,config.confidence)
        fan=np.quantile(equity,[.05,.5,.95],axis=0)
        outcomes=[dict(path=i,terminal_value=float(equity[i,-1]),loss=float(losses[i]),max_drawdown_percent=float(100*drawdown[i])) for i in range(config.paths)]
        distribution=[dict(step=i,p05=float(fan[0,i]),median=float(fan[1,i]),p95=float(fan[2,i])) for i in range(config.horizon+1)]
        metrics=dict(var_loss=var,expected_shortfall_loss=es,mean_terminal_value=float(equity[:,-1].mean()),
                     loss_probability=float(np.mean(losses>0)),insolvency_probability=float(np.mean(equity.min(axis=1)<=0)),
                     worst_drawdown_percent=float(100*drawdown.min()),median_drawdown_percent=float(100*np.median(drawdown)),
                     paths=config.paths,horizon=config.horizon,confidence=config.confidence,covariance_adjustment=adjustment)
        asset_projections=[];asset_histograms=[]
        for j,asset in enumerate(assets):
            terminal_prices=prices[-1,j]*growth[:,j]
            quantiles=np.quantile(terminal_prices,[.05,.5,.95])
            asset_projections.append(dict(asset=asset,starting_price=float(prices[-1,j]),
                mean_terminal_price=float(terminal_prices.mean()),p05=float(quantiles[0]),median=float(quantiles[1]),p95=float(quantiles[2])))
            counts,edges=np.histogram(terminal_prices,bins=40)
            asset_histograms.extend(dict(asset=asset,lower=float(edges[k]),upper=float(edges[k+1]),count=int(count)) for k,count in enumerate(counts))
        results[name]=dict(metrics=metrics,outcomes=outcomes,distribution=distribution,
                           asset_price_projections=asset_projections,asset_price_histograms=asset_histograms)
        summary.append(dict(scenario=name,**metrics))
        matrices.append(dict(scenario=name,assets=assets,covariance=repaired.tolist(),cholesky=factor.tolist()))
        charts.append(dict(section=name,table='distribution',keys=['p05','median','p95'],x='step',label=name+' · portfolio value percentiles'))
    results['Stress comparison']={'summary':summary}
    return dict(name=('SYNTHETIC · ' if history['synthetic'] else '')+'Multi-asset risk and stress simulation',
        synthetic=history['synthetic'],currency=history['currency'],history_id=config.history_id,
        calibration=dict(first=frame.date.iloc[0],last=frame.date.iloc[-1],observations=len(frame),
                         assets=assets,daily_log_mean=mean.tolist(),daily_log_covariance=cov.tolist(),weights=dict(zip(assets,w.tolist())),cash_weight=float(1-w.sum())),
        covariance_scenarios=matrices,results=results,charts=charts,
        limitations=['Monte Carlo extension of quant-research project 04. Historical daily log-return sample means and covariances parameterize independent Gaussian increments; no additional half-variance drift subtraction. Normal tails can understate jumps and clustered volatility.',
            'Static starting exposures, with residual cash 1 minus net asset weight, held throughout each path. This projects marked portfolio value; it does not place or rebalance trades, enforce future margin, or include future financing, borrow or liquidation costs.',
            'VaR and expected shortfall are losses in the selected currency; negative values represent gains. Expected shortfall integrates the worst empirical tail including fractional sample mass. Percentiles are pointwise, not simultaneous confidence bands.',
            'Each stress uses identical random shocks. Volatility shock scales covariance; correlation spike blends toward perfect positive correlation; correlation breakdown removes cross-asset correlation. They need not increase risk for every signed portfolio.',
            'Singular covariance is regularized only among nonconstant assets with an explicit reported adjustment. Constant assets retain zero variance. Historical dates are session labels; simulated horizon counts observations, not a production exchange calendar.'])
