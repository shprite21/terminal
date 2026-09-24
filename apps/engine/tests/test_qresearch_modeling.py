import numpy as np
import pandas as pd
import pytest

from evidence.storage import Store,canonical
from qresearch.history import ScenarioConfig,scenario
from qresearch.modeling import FrontierConfig,ForecastConfig,efficient_weights,frontier,forecast,stationarity
from qresearch.risk_simulation import RiskConfig
from qresearch.service import run
from qresearch.replay import replay


def test_minimum_variance_matches_independent_two_asset_solution():
    mu=np.array([.06,.12]);cov=np.diag([.04,.09])
    curve=efficient_weights(mu,cov,1,15)
    w,ret,vol=curve[0]
    expected=np.array([.09/(.04+.09),.04/(.04+.09)])
    assert w==pytest.approx(expected,abs=1e-8)
    assert vol**2==pytest.approx(1/(1/.04+1/.09))
    assert curve[-1][0]==pytest.approx([0,1],abs=1e-8)
    for weights,ret,vol in curve:
        assert weights.sum()==pytest.approx(1,abs=1e-8)
        assert weights.min()>=-1e-9 and weights.max()<=1+1e-9
        assert ret==pytest.approx(weights@mu)
        assert vol**2==pytest.approx(weights@cov@weights)
    assert np.diff([r[1] for r in curve]).min()>=-1e-9
    assert np.diff([r[2] for r in curve]).min()>=-1e-9


def test_weight_caps_singular_and_one_asset_cases():
    with pytest.raises(ValueError):efficient_weights([.05,.1],np.eye(2),.4,5)
    curve=efficient_weights([.05,.1],np.eye(2),.5,5)
    assert len(curve)==1 and curve[0][0]==pytest.approx([.5,.5])
    one=efficient_weights([.07],np.array([[.04]]),1,5)
    assert len(one)==1 and one[0][0]==pytest.approx([1])
    constant=efficient_weights([0,0],np.zeros((2,2)),1,5)
    assert constant[0][2]==0


def test_forecast_same_dates_first_naive_and_future_perturbation():
    h=scenario(ScenarioConfig(observations=120,assets=1))
    frame=pd.DataFrame(h['results']['History']['observations'])
    config=ForecastConfig(test_observations=12,p=1,d=0,q=0,refit_every=4)
    original=forecast(config,h,frame)
    changed=frame.copy();changed.loc[changed.index[-3:], 'SYNTH1']*=1.2
    altered=forecast(config,h,changed)
    rows=original['results']['Forecast validation']['forecasts']
    assert rows[:-3]==altered['results']['Forecast validation']['forecasts'][:-3]
    assert len(rows)==config.test_observations
    assert rows[0]['naive']==frame.SYNTH1.iloc[-13]
    assert all(r['information_through']<r['date'] for r in rows)
    assert all(f['fit_last_date']<f['forecast_date'] and f['converged'] for f in original['results']['Forecast validation']['fits'])
    for model in ['arima','naive']:
        errors=np.array([r['actual']-r[model] for r in rows])
        metrics=original['results']['Forecast validation']['metrics']
        assert metrics[model+'_rmse']==pytest.approx(np.linalg.norm(errors)/np.sqrt(len(errors)))
        assert metrics[model+'_mae']==pytest.approx(np.abs(errors).sum()/len(errors))
    assert original['calibration']==altered['calibration']


def test_training_stationarity_and_constant_series_behavior():
    diagnostics=stationarity(np.ones(60))
    assert diagnostics['p_value'] is None
    assert all(r['acf'] is None for r in diagnostics['autocorrelation'])
    frame=pd.DataFrame({'date':pd.bdate_range('2020-01-01',periods=70).strftime('%Y-%m-%d'),'AAA':100.})
    with pytest.raises(ValueError,match='constant'):
        forecast(ForecastConfig(test_observations=10),{'assets':['AAA']},frame)


def test_frozen_frontier_allocation_feeds_risk_and_both_replay(tmp_path):
    db=Store(tmp_path/'registry')
    history=run(db,'history-scenario',ScenarioConfig(observations=100,assets=3),lambda:False,lambda *_:None)
    allocation=run(db,'efficient-frontier',FrontierConfig(history_id=history,points=8),lambda:False,lambda *_:None)
    source=db.get(allocation,'quant_result')
    sample=np.array(source['calibration']['sample_covariance'])
    used=np.array(source['calibration']['used_covariance'])
    assert np.diag(sample)==pytest.approx(np.diag(used))
    risk=run(db,'multi-asset-risk',RiskConfig(history_id=history,source_result_id=allocation,horizon=1),lambda:False,lambda *_:None)
    result=db.get(risk,'quant_result')
    assert result['calibration']['weights']==source['allocation']['weights']
    assert result['inputs']['allocation_source']==source
    for name,record in [('frontier',source),('risk',result)]:
        path=tmp_path/(name+'.json');path.write_text(canonical(record),encoding='utf-8')
        assert replay(path)['verified']
