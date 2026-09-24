"""Nested chronological Optuna research, adapted from source project 02.

Training, validation and outer test accounts never share an optimizer objective.
Each fold is an independently funded experiment with a scheduled closing trade.
"""
from typing import Literal
import numpy as np
import optuna
from pydantic import Field,model_validator

from .cointegration import estimate,normalize,residual_stationarity,spread_targets
from .equity_account import AccountConfig,simulate_account,performance,funding_exposure,ACCOUNT_LIMITATIONS


class BasketConfig(AccountConfig):
    history_id: str = ''
    method: Literal['auto','eg','johansen'] = 'auto'
    train_window: int = Field(252,ge=120,le=1000)
    validation_window: int = Field(63,ge=20,le=252)
    test_window: int = Field(63,ge=10,le=252)
    trials: int = Field(30,ge=6,le=100)
    seed: int = Field(42,ge=0,le=2**31-1)
    minimum_rebalances: int = Field(2,ge=1,le=100)

    @model_validator(mode='after')
    def calibration_size(self):
        if self.train_window-self.validation_window<80:
            raise ValueError('Training minus validation must leave at least 80 calibration observations')
        return self


def _weights(base,params):
    return normalize(np.asarray(base)*np.array([1.]+[params[f'weight_{i}'] for i in range(1,len(base))]))


def basket(config,history,frame,cancel=lambda:False,progress=lambda *_:None):
    assets=history['assets'];prices=frame[assets].to_numpy(float);dates=frame.date.tolist()
    n=len(prices);fold_starts=list(range(config.train_window,n,config.test_window))
    if len(assets)<2 or not fold_starts or n-config.train_window<10:
        raise ValueError('Basket research needs at least two assets and ten observations after training')
    if len(fold_starts)*config.trials>300 or n>2000:
        raise ValueError('Limit research to 2,000 observations and at most 300 total trials across folds')
    # Explicit headroom for next-close costs, price changes and short collateral.
    exposure=funding_exposure(config)
    folds=[];comparison=[];trial_rows=[];equity_rows=[];drawdown=[]
    chain={'baseline':config.initial_cash,'optimized':config.initial_cash}
    chains={k:[v] for k,v in chain.items()};final_targets=np.zeros(len(assets))
    for fold,start in enumerate(fold_starts):
        if cancel():raise InterruptedError()
        lo=start-config.train_window;split=start-config.validation_window;end=min(start+config.test_window,n)-1
        inner=estimate(prices[lo:split],config.method)
        baseline_params=dict(lookback=20,entry=2.,exit=.5,**{f'weight_{j}':1. for j in range(1,len(assets))})
        selected=None;trials=[]
        if inner['eligible']:
            sampler=optuna.samplers.TPESampler(seed=(config.seed+fold)%(2**31),n_startup_trials=5)
            study=optuna.create_study(direction='maximize',sampler=sampler)
            study.enqueue_trial(baseline_params)
            def objective(trial):
                if cancel():raise InterruptedError()
                params=dict(lookback=trial.suggest_int('lookback',10,60),
                            entry=trial.suggest_float('entry',1.,3.),exit=trial.suggest_float('exit',.1,.9))
                for j in range(1,len(assets)):params[f'weight_{j}']=trial.suggest_float(f'weight_{j}',.5,1.5)
                weights=_weights(inner['weights'],params)
                p=residual_stationarity(prices[lo:split],weights)
                trial.set_user_attr('calibration_residual_adf_p',p)
                if p>=.1:
                    trial.set_user_attr('reason','Perturbed calibration spread failed exploratory ADF gate')
                    raise optuna.TrialPruned()
                targets,_=spread_targets(prices[:start],assets,weights,split-1,start-1,
                    params['lookback'],params['entry'],params['exit'],exposure)
                account=simulate_account(prices[:start],dates[:start],targets,['basket'],assets,config,
                    split-1,start-1,liquidate=True,cancel=cancel)
                metrics=account['metrics'];trial.set_user_attr('validation_metrics',metrics)
                if metrics['sharpe'] is None or metrics['insolvent'] or metrics['accepted_rebalances']<config.minimum_rebalances:
                    trial.set_user_attr('reason','Insufficient funded validation rebalances or undefined Sharpe')
                    raise optuna.TrialPruned()
                return metrics['sharpe']
            study.optimize(objective,n_trials=config.trials,n_jobs=1,show_progress_bar=False)
            trials=[dict(number=t.number,status=t.state.name,value=t.value,params=t.params,**t.user_attrs) for t in study.trials]
            complete=[t for t in study.trials if t.state==optuna.trial.TrialState.COMPLETE]
            if complete:selected=study.best_trial.params.copy()
        outer=estimate(prices[lo:start],config.method)
        accounts={};signals={};outer_weights={};outer_gates={};evaluation_status={}
        for label,params in [('baseline',baseline_params),('optimized',selected)]:
            targets=np.zeros((end+1,1,len(assets)));diagnostics=[];weights=None;p=None
            if outer['eligible'] and params is not None:
                weights=_weights(outer['weights'],params)
                p=residual_stationarity(prices[lo:start],weights)
                if label=='baseline' or p<.1:
                    targets,diagnostics=spread_targets(prices[:end+1],assets,weights,start-1,end,
                        params['lookback'],params['entry'],params['exit'],exposure)
            outer_weights[label]=weights.tolist() if weights is not None else None
            outer_gates[label]=p
            evaluation_status[label]=('active signal policy' if diagnostics else
                'cash: no eligible outer cointegration' if not outer['eligible'] else
                'cash: no eligible validation selection' if params is None else 'cash: refitted perturbed spread failed exploratory ADF gate')
            accounts[label]=simulate_account(prices[:end+1],dates[:end+1],targets,['basket'],assets,config,
                start-1,end,liquidate=True,cancel=cancel)
            signals[label]=[dict(date=dates[r.pop('index')],**r) for r in diagnostics]
            if label=='optimized':final_targets=targets[-1,0].copy()
        for offset,date in enumerate(dates[start:end+1],1):
            row=dict(date=date,fold=fold)
            for label in accounts:
                eq=accounts[label]['equity'];previous=eq[offset-1]['equity'];current=eq[offset]['equity']
                if previous<=0:raise ValueError('Fold account became insolvent; cannot chain returns')
                chain[label]*=current/previous;row[label]=float(chain[label]);chains[label].append(chain[label])
            equity_rows.append(row)
        for label,account in accounts.items():comparison.append(dict(fold=fold,strategy=label,**account['metrics']))
        trial_rows.extend(dict(fold=fold,**r) for r in trials)
        folds.append(dict(fold=fold,calibration_first=dates[lo],calibration_last=dates[split-1],
            validation_first=dates[split],validation_last=dates[start-1],
            refit_first=dates[lo],refit_last=dates[start-1],test_first=dates[start],test_last=dates[end],
            inner_cointegration=inner,outer_cointegration=outer,selected=selected,
            status='selected on validation' if selected else 'no eligible validation selection; optimized holds cash',
            baseline_parameters=baseline_params,outer_weights=outer_weights,outer_residual_adf=outer_gates,
            evaluation_status=evaluation_status,accounts=accounts,signals=signals))
        progress(fold+1,len(fold_starts))
    aggregate={key:performance(values,config.annualization) for key,values in chains.items()}
    peaks={k:config.initial_cash for k in chains}
    for row in equity_rows:
        dd=dict(date=row['date'])
        for key in chains:peaks[key]=max(peaks[key],row[key]);dd[key]=100*(row[key]/peaks[key]-1)
        drawdown.append(dd)
    b,o=aggregate['baseline'],aggregate['optimized']
    delta=o['sharpe']-b['sharpe'] if b['sharpe'] is not None and o['sharpe'] is not None else None
    improvement=bool(delta is not None and delta>0 and o['max_drawdown_percent']>b['max_drawdown_percent'])
    return dict(name=('SYNTHETIC · ' if history['synthetic'] else '')+'Bayesian basket walk-forward',
        synthetic=history['synthetic'],currency=history['currency'],history_id=config.history_id,
        folds=folds,allocation=dict(history_id=config.history_id,as_of=dates[-1],
            weights=dict(zip(assets,final_targets.tolist())),
            selection='Unexecuted final-close optimized signal; fold accounts liquidated separately'),
        results={'Basket comparison':{'metrics':dict(folds=len(folds),selected_folds=sum(f['selected'] is not None for f in folds),
            sharpe_difference=delta,drawdown_percentage_point_difference=o['max_drawdown_percent']-b['max_drawdown_percent'],
            higher_sharpe_and_smaller_drawdown_observed=improvement),
            'aggregate':[dict(strategy=k,**v) for k,v in aggregate.items()],
            'equity':equity_rows,'drawdown':drawdown,'fold_metrics':comparison,'trials':trial_rows,
            'fold_plan':[dict(fold=f['fold'],calibration_first=f['calibration_first'],calibration_last=f['calibration_last'],
                validation_first=f['validation_first'],validation_last=f['validation_last'],
                test_first=f['test_first'],test_last=f['test_last'],
                baseline_status=f['evaluation_status']['baseline'],optimized_status=f['evaluation_status']['optimized'],
                selected=f['selected']) for f in folds]}},
        charts=[dict(section='Basket comparison',table='equity',keys=['baseline','optimized'],label='Nested out-of-sample equity · independent folds chained'),
                dict(section='Basket comparison',table='drawdown',keys=['baseline','optimized'],label='Out-of-sample drawdown (%)')],
        limitations=ACCOUNT_LIMITATIONS+[
            'Each outer fold fits a cointegration model on its inner calibration window. Seeded sequential Optuna TPE tunes relative basket weights, lookback and entry/exit thresholds on the following inner validation account. No outer test observation enters that objective.',
            'The selected parameters are frozen before refitting base cointegration weights on the full outer training window. EG uses a 5% residual cointegration test; Johansen uses sequential 5% trace rank with one lag and a constant. Perturbed-weight ADF is an exploratory calibration gate, not a post-selection significance claim.',
            'Baseline uses fixed lookback 20, entry 2 and exit 0.5 with unperturbed refitted weights. Both models use identical test dates, funding, execution and costs. Invalid training cointegration holds cash; no eligible optimized trial also holds cash. Every diagnostic is retained.',
            'Each fold starts with fresh initial cash and pre-schedules liquidation on its last test close, charging exit costs. Displayed equity chains independent fold returns; it is not a continuously financed deployment. The final saved risk allocation is a hypothetical unexecuted signal, not the liquidated account.',
            f'Target gross exposure is {exposure:.6g}, reserving headroom under the account cap; whole-share sizing can still reject a next-close basket. Historical selection and multiple trials do not establish future profitability. Improvement is reported only when measured on these test observations.'])
