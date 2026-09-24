import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from evidence.storage import Store,canonical
from qresearch.history import ImportConfig,ScenarioConfig,import_history,scenario,validate_history
from qresearch.risk_simulation import RiskConfig,covariance_factor,simulate_risk,tail_losses
from qresearch.service import run
from qresearch.replay import replay


def test_empirical_tail_integrates_fractional_mass_and_signed_losses():
    losses=np.array([-5.,0.,1.,4.,10.])
    var,es=tail_losses(losses,.7)
    assert var==pytest.approx(3.4)
    assert es==pytest.approx((10+.5*4)/1.5)
    assert es>=var
    assert tail_losses([-4,-4,-4],.95)==pytest.approx((-4,-4))


def test_cholesky_preserves_variances_and_handles_singular_and_constant_assets():
    cov=np.array([[.04,.06,0],[.06,.09,0],[0,0,0]])
    fixed,L,adjustment=covariance_factor(cov)
    assert L@L.T==pytest.approx(fixed,abs=1e-14)
    assert np.diag(fixed)==pytest.approx(np.diag(cov),abs=1e-14)
    assert np.array_equal(L[2],np.zeros(3)) and adjustment<1e-9
    assert covariance_factor(np.zeros((2,2)))[2]==0
    with pytest.raises(ValueError):covariance_factor([[1,2],[2,1]])
    with pytest.raises(ValueError):covariance_factor([[0,.1],[.1,1]])


def test_history_import_retains_bytes_rejects_missing_and_unsorted_data():
    rows=[{'date':d,'AAA':100+i,'BBB':200+i} for i,d in enumerate(pd.bdate_range('2020-01-01',periods=50).strftime('%Y-%m-%d'))]
    csv=pd.DataFrame(rows).to_csv(index=False)
    config=ImportConfig(csv=csv,source_url='https://example.com/historical',
        source_note='Test-only source attestation for imported adjusted prices.',calendar_note='The supplied dates are fixture weekdays, not a certified exchange calendar.')
    result=import_history(config)
    assert result['source']['original_csv']==csv and result['synthetic'] is False
    with pytest.raises(ValueError):validate_history(rows[::-1],['AAA','BBB'])
    invalid=[dict(r) for r in rows];invalid[3]['AAA']=None
    with pytest.raises(ValueError):validate_history(invalid,['AAA','BBB'])
    with pytest.raises(ValueError):import_history(config.model_copy(update={'source_url':'https://example.com/?token=secret'}))


def test_single_asset_risk_matches_lognormal_analytic_tail_within_mc_error():
    increments=np.tile([-.01,.01],100)
    frame=pd.DataFrame({'date':pd.bdate_range('2020-01-01',periods=201).strftime('%Y-%m-%d'),
                        'AAA':100*np.exp(np.r_[0,np.cumsum(increments)])})
    history={'assets':['AAA'],'synthetic':True,'currency':'USD'}
    config=RiskConfig(horizon=5,volatility_shock=1,correlation_strength=0)
    result=simulate_risk(config,history,frame)
    mu=np.diff(np.log(frame.AAA)).mean()*config.horizon
    sigma=np.std(np.diff(np.log(frame.AAA)),ddof=1)*math.sqrt(config.horizon)
    z=norm.ppf(1-config.confidence)
    expected_var=config.initial_value*(1-math.exp(mu+sigma*z))
    expected_es=config.initial_value*(1-math.exp(mu+.5*sigma*sigma)*norm.cdf(z-sigma)/(1-config.confidence))
    metrics=result['results']['Baseline']['metrics']
    assert metrics['var_loss']==pytest.approx(expected_var,rel=.06)
    assert metrics['expected_shortfall_loss']==pytest.approx(expected_es,rel=.06)
    for name in ['Volatility shock','Correlation spike','Correlation breakdown']:
        assert result['results'][name]['outcomes']==result['results']['Baseline']['outcomes']
    losses=[row['loss'] for row in result['results']['Baseline']['outcomes']]
    # Direct order statistics independent of tail_losses implementation.
    assert metrics['var_loss']==pytest.approx(np.quantile(losses,.95))
    assert metrics['expected_shortfall_loss']==pytest.approx(np.sort(losses)[-500:].mean())


def test_constant_assets_and_zero_exposure_do_not_invent_risk():
    frame=pd.DataFrame({'date':pd.bdate_range('2020-01-01',periods=50).strftime('%Y-%m-%d'),'AAA':100.,'BBB':70.})
    history={'assets':['AAA','BBB'],'synthetic':True,'currency':'USD'}
    for weights in [{},{'AAA':0.,'BBB':0.}]:
        result=simulate_risk(RiskConfig(horizon=2,weights=weights),history,frame)
        m=result['results']['Baseline']['metrics']
        assert m['var_loss']==0 and m['expected_shortfall_loss']==0
        assert m['worst_drawdown_percent']==0 and m['mean_terminal_value']==100000


def test_source_allocation_cannot_silently_override_history_or_date():
    history=scenario(ScenarioConfig(observations=80,assets=2))
    frame=pd.DataFrame(history['results']['History']['observations'])
    config=RiskConfig(history_id='abc',horizon=1)
    allocation={'history_id':'abc','as_of':frame.date.iloc[-1],'weights':{'SYNTH1':.3,'SYNTH2':.7}}
    result=simulate_risk(config,history,frame,allocation=allocation)
    assert result['calibration']['weights']==allocation['weights']
    with pytest.raises(ValueError):simulate_risk(config,history,frame,allocation={**allocation,'as_of':'2099-01-01'})
    with pytest.raises(ValueError):simulate_risk(config,history,frame,allocation={**allocation,'history_id':'changed'})
    with pytest.raises(InterruptedError):simulate_risk(config,history,frame,cancel=lambda:True)


def test_risk_result_replays_embedded_history_exactly(tmp_path):
    db=Store(tmp_path/'registry')
    key=run(db,'history-scenario',ScenarioConfig(observations=80,assets=2),lambda:False,lambda *_:None)
    config=RiskConfig(history_id=key,horizon=2)
    report=run(db,'multi-asset-risk',config,lambda:False,lambda *_:None)
    body=db.get(report,'quant_result')
    assert body['inputs']['history']==db.get(key,'quant_dataset')
    path=tmp_path/'risk.json';path.write_text(canonical(body),encoding='utf-8')
    assert replay(path)['verified']
    assert len(body['results']['Baseline']['outcomes'])==10000
    assert len(body['covariance_scenarios'])==4
