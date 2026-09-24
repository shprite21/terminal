"""Deterministic end-to-end fixture plus independent statistical/accounting invariants."""
import io
import copy
import json
import math
import time
import zipfile
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from apps import research_api
from apps.research_api import ResearchWorkspace, atomic_json
from evidence.storage import Store, digest
from research.workspace import ResearchRequest
from research.survival import pipeline
from research.survival.execution import execution_stress
from research.survival.forward import PaperEvent, monitor, record_event
from research.survival.methods import method
from research.survival.models import Gate, LayerResult, SurvivalConfig, apply_gates, summarize
from research.survival.pipeline import Context, run_pipeline
from research.survival.statistics import (NeedData, block_bootstrap, chronological_splits,
    deflated_sharpe, factor_fit, fdr, hac_mean, metrics, pbo, walk_folds)


def request():
    return ResearchRequest(name='Survival fixture', hypothesis='Seeded daily mechanics, not market performance.',
        data_mode='demo', symbols=['AAA','BBB','CCC','DDD','EEE','FFF'],
        sleeves=[{'strategy':'time_series_momentum','lookback':20,'budget':60},
                 {'strategy':'mean_reversion','lookback':10,'budget':40}],
        train_window=126, test_window=63)


@pytest.fixture
def context(synthetic_bundle):
    synthetic_bundle.benchmark = synthetic_bundle.close().mean(axis=1).to_frame('Close')
    synthetic_bundle.metadata = {'source':'SYNTHETIC deterministic test fixture', 'currency':'USD'}
    return Context(request(), synthetic_bundle, SurvivalConfig(bootstrap_samples=100, max_universe_subsets=2),
                   '20260101T000000Z-1234abcd', {'dataset_hash':'test-fixture'})


def test_splits_and_walk_windows_are_disjoint_and_leave_final_test():
    splits = chronological_splits(1000)
    assert splits == {'train':(0,600),'validation':(600,800),'chronological_test':(800,1000)}
    for mode in ('rolling','expanding'):
        folds = walk_folds(800, 252, 63, mode, 20)
        assert all(start < train_end < test_end <= 800 for start,train_end,test_end in folds)
        assert all(folds[i][2] == folds[i+1][1] for i in range(len(folds)-1))
        assert len({j for _,a,b in folds for j in range(a,b)}) == len(folds)*63
        assert folds[1][0] == (63 if mode == 'rolling' else 0)


def test_bootstrap_seed_and_dependence():
    x = np.random.default_rng(17).normal(.0003,.01,240)
    a = block_bootstrap(x, samples=100, seed=8)
    assert a == block_bootstrap(x, samples=100, seed=8)
    assert a != block_bootstrap(x, samples=100, seed=9)
    assert len(a['distributions']['sharpe']) == 100
    assert all(v['low'] <= v['median'] <= v['high'] for v in a['intervals'].values())
    with pytest.raises(NeedData):
        block_bootstrap(np.zeros(200))
    with pytest.raises(NeedData):
        block_bootstrap([.01]*20)


def test_dsr_against_explicit_moments_and_normal_formula():
    x = np.random.default_rng(52).normal(.001,.01,400)
    trials = [-.08, .01, .03, .08]
    answer = deflated_sharpe(x, trials, 4)
    # Independent moment construction, not the scipy skew/kurtosis implementation.
    centered = x - x.mean()
    variance = np.mean(centered**2)
    skewness = np.mean(centered**3)/variance**1.5
    pearson = np.mean(centered**4)/variance**2
    sr = x.mean()/x.std(ddof=1)
    from scipy.special import ndtri
    benchmark = np.std(trials,ddof=1)*((1-.5772156649015329)*ndtri(.75)+.5772156649015329*ndtri(1-1/(4*math.e)))
    z = (sr-benchmark)*math.sqrt(399)/math.sqrt(1-skewness*sr+(pearson-1)*sr**2/4)
    expected = .5*(1+math.erf(z/math.sqrt(2)))
    assert answer['dsr'] == pytest.approx(expected, abs=1e-12)
    assert answer['expected_max_daily_sharpe'] == pytest.approx(benchmark)
    with pytest.raises(NeedData):
        deflated_sharpe(x,trials,None)
    with pytest.raises(NeedData):
        deflated_sharpe(x,trials,5)


def test_cscv_known_rank_reversal_and_missing_data():
    noise = np.tile([-.01,.01],40)
    advantage = np.repeat([.004,.002,-.004,-.002],20)
    result = pbo(np.column_stack([noise+advantage, noise-advantage]),4,20)
    assert result['partitions'] == 6
    assert result['pbo'] >= 4/6  # Every non-tied training winner loses in its complement.
    with pytest.raises(NeedData):
        pbo(np.ones((100,3))*.01,4,20)
    with pytest.raises(NeedData):
        pbo(np.column_stack([noise,noise]),4,20)


def test_fdr_hac_and_factor_attribution():
    assert fdr([.01,.02,.9]) == pytest.approx([.055,.055,1])
    market = np.random.default_rng(9).normal(0,.01,300)
    x = .001+1.5*market
    answer = factor_fit(x, market[:,None])
    assert answer['daily_alpha'] == pytest.approx(.001, abs=1e-12)
    assert answer['coefficients'][0] == pytest.approx(1.5, abs=1e-12)
    assert hac_mean(market)['ci_low'] <= hac_mean(market)['daily_mean'] <= hac_mean(market)['ci_high']
    assert metrics([-.1,0])['max_drawdown'] == pytest.approx(-.1)


def test_gate_logic_hard_failures_and_missing_metrics():
    config = SurvivalConfig(gates=[Gate(layer=8,metric='p_one_sided',operator='<=',threshold=.05,severity='FAIL')], required_layers=[1,8])
    failed = apply_gates(LayerResult(**method(8),status='PASS',metrics={'p_one_sided':.3}),config)
    assert failed.status == 'FAIL'
    missing = apply_gates(LayerResult(**method(8),status='N-A'),config)
    summary = summarize([LayerResult(**method(1),status='PASS'),missing],config)
    assert summary['unresolved_required_layers'] == [8]
    assert not summary['research_gates_satisfied']
    optional = summarize([missing],SurvivalConfig(gates=config.gates))
    assert not optional['research_gates_satisfied']
    assert optional['unresolved_failure_gates'] == [{'layer':8,'metric':'p_one_sided'}]
    hard = LayerResult(**method(1),status='FAIL',hard_failure=True)
    assert apply_gates(hard,SurvivalConfig()).hard_failure
    for value in ({'seed':-1},{'train_fraction':.8,'validation_fraction':.2},{'cscv_blocks':5},{'layers':[2]}, {'effective_trials':3}):
        with pytest.raises(ValidationError):
            SurvivalConfig(**value)


def test_raw_duplicates_and_missing_prices_are_hard_failures(context):
    frame = context.bundle.ohlcv['AAA']
    context.bundle.ohlcv['AAA'] = pd.concat([frame,frame.iloc[-1:]])
    output = run_pipeline(context)
    assert output['layers'][0]['hard_failure']
    assert output['summary']['status'] == 'FAIL'
    assert output['layers'][6]['status'] == 'N-A'
    assert len(output['layers']) == 18


def test_prefix_audit_detects_future_signal_leakage(context,monkeypatch):
    original = pipeline.pipeline_for
    def leaky(request):
        engine = original(request)
        run = engine.run
        def corrupted(bundle):
            result = run(bundle)
            result.weights = result.weights + len(bundle.close())/100000
            return result
        engine.run = corrupted
        return engine
    monkeypatch.setattr(pipeline,'pipeline_for',leaky)
    result = pipeline.integrity(context)
    assert result.hard_failure
    assert any('future bars' in reason for reason in result.reasons)


def test_final_test_prices_cannot_change_development_variants_or_folds(context):
    altered = copy.deepcopy(context)
    start = context.evaluation[context.splits['chronological_test'][0]]
    for frame in altered.bundle.ohlcv.values():
        columns = ['Open','High','Low','Close','Adj Close']
        frame.loc[start:,columns] *= 1.5
    assert pipeline.stability(context).model_dump() == pipeline.stability(altered).model_dump()
    assert pipeline.walkforward(context).model_dump() == pipeline.walkforward(altered).model_dump()


def test_missing_volume_is_not_reported_as_execution_capacity(context):
    context.bundle.ohlcv['AAA'].loc[context.prices.index[-1],'Volume'] = np.nan
    with pytest.raises(NeedData,match='complete nonnegative'):
        pipeline.liquidity(context)


def test_execution_conserves_cash_has_whole_shares_and_delays(context):
    px = pd.DataFrame({'A':[100.]*40}, index=pd.bdate_range('2024-01-01', periods=40))
    volume = pd.DataFrame(100, index=px.index, columns=px.columns)
    targets = pd.DataFrame(.9,index=px.index,columns=px.columns)
    req = request().model_copy(update={'initial_capital':1000,'rebalance':'daily'})
    config = SurvivalConfig(participation_rate=.01)
    run = execution_stress(px,volume,targets,req,config,delay=2)
    assert run['metrics']['minimum_cash'] >= 0
    assert all(isinstance(f['quantity'],int) and abs(f['quantity']) <= 1 for f in run['fills'])
    assert all(pd.Timestamp(f['date']) > pd.Timestamp(f['signal_date']) for f in run['fills'])
    assert all(px.index.get_loc(pd.Timestamp(f['date']))-px.index.get_loc(pd.Timestamp(f['signal_date'])) == 2 for f in run['fills'])
    # Flat prices: NAV change must exactly equal all fees and slippage.
    drag = sum(f['commission']+f['slippage'] for f in run['fills'])
    assert run['metrics']['total_return'] == pytest.approx(-drag/1000)


def test_complete_survival_fixture_is_deterministic_and_truthful(context):
    attempts = []
    context.trial_sink = attempts.append
    output = run_pipeline(context)
    assert len(output['layers']) == 18
    assert output['synthetic']
    errors = [layer for layer in output['layers'] if any(r.startswith('Calculation failed') for r in layer['reasons'])]
    assert not errors, errors
    assert output['layers'][1]['metrics']['true_oos_sharpe'] is None
    assert output['layers'][16]['status'] == 'N-A'
    assert output['layers'][17]['status'] == 'N-A'
    assert output['summary']['live_eligible'] is False
    assert len(attempts) >= 3
    cost = output['layers'][4]['diagnostics']['scenarios']
    assert cost[0]['total_return'] >= cost[1]['total_return'] >= cost[2]['total_return']
    assert output['layers'][6] == pipeline.bootstrap(context).model_dump()
    json.dumps(output,allow_nan=False)


def seed_experiment(workspace,context):
    record = workspace.tracker.start_run(context.request.name,context.request.model_dump())
    path = workspace.root/record.experiment_id
    pd.concat(context.bundle.ohlcv,names=['symbol','date']).to_csv(path/'prices.csv',float_format='%.17g')
    context.bundle.benchmark.to_csv(path/'benchmark.csv',float_format='%.17g')
    sha = digest((path/'prices.csv').read_bytes()+(path/'benchmark.csv').read_bytes())
    result = {'data':{**context.bundle.metadata,'symbols':context.request.symbols,'snapshot_sha256':sha},
              'provenance':{'source_sha256':'original-fixture-code','execution':{'execution_lag':1}},
              'paper_candidate_eligible':True,'request':context.request.model_dump()}
    atomic_json(path/'result.json',result)
    atomic_json(path/'job.json',{'run_id':record.experiment_id,'name':context.request.name,'created_at':record.created_at,
        'status':'completed','request':context.request.model_dump(),'decisions':[]})
    return record.experiment_id,path


def wait_completed(client,key):
    for _ in range(600):
        run = client.get('/api/research/survival/runs/'+key).json()
        if run['status'] in {'completed','failed'}:
            assert run['status'] == 'completed',run
            return run
        time.sleep(.02)
    raise AssertionError('Survival job timed out')


def test_api_persistence_cache_export_and_experiment_immutability(context,tmp_path,monkeypatch):
    workspace = ResearchWorkspace(tmp_path/'experiments')
    monkeypatch.setattr(research_api,'workspace',lambda: workspace)
    app = FastAPI()
    app.include_router(research_api.router)
    key,path = seed_experiment(workspace,context)
    original = (path/'result.json').read_bytes()
    payload = {'experiment_id':key,'config':{'layers':[1,2,7,8,17,18], 'bootstrap_samples':100,
        'gates':[{'layer':8,'metric':'p_one_sided','operator':'<=','threshold':-1,'severity':'FAIL'}]}}
    try:
        with TestClient(app) as client:
            assert len(client.get('/api/research/survival/catalog').json()['layers']) == 18
            assert client.post('/api/research/survival/runs',json={'experiment_id':'../../secret'}).status_code == 422
            submitted = client.post('/api/research/survival/runs',json=payload)
            assert submitted.status_code == 202,submitted.text
            run = wait_completed(client,submitted.json()['id'])
            assert run['result']['summary']['status'] == 'FAIL'
            again = client.post('/api/research/survival/runs',json=payload).json()
            assert again['cached'] and again['id'] == run['id']
            assert (path/'result.json').read_bytes() == original
            book = client.get('/api/research/survival/runs?experiment_id='+key).json()['runs']
            assert book[0]['summary']['counts']['FAIL'] == 1
            response = client.post(f'/api/research/runs/{key}/decision',json={'status':'paper_candidate','rationale':'Review all negative outcomes first'})
            assert response.status_code == 409
            export = client.get('/api/research/survival/runs/'+run['id']+'/export')
            with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
                assert {'source.zip','inputs.json','run.json','trials.json','events.json'} <= set(archive.namelist())
            from research.survival.replay import replay
            exported = tmp_path/'export.zip'
            exported.write_bytes(export.content)
            assert replay(exported)['verified']
            with workspace.survival_service.store.db() as connection:
                with pytest.raises(Exception,match='immutable'):
                    connection.execute('DELETE FROM artifacts WHERE id=?',(run['result_id'],))
            # A new service can read all completed evidence; no historical mutations.
            from research.survival.service import SurvivalService
            restarted = SurvivalService(workspace)
            assert restarted.get(run['id'])['result'] == run['result']
    finally:
        workspace.executor.shutdown(wait=True)


def test_forward_only_paper_events_and_monitor(tmp_path):
    store = Store(tmp_path)
    start = datetime.now(timezone.utc)-timedelta(seconds=10)
    key = store.put('survival_paper',{'created_at':start.isoformat(),'universe':['A']})
    with pytest.raises(ValueError,match='advance strictly'):
        record_event(store,key,PaperEvent(kind='signal',observed_at=start))
    signal = record_event(store,key,PaperEvent(kind='signal',observed_at=start+timedelta(seconds=1),weights={'A':.3},cost_bps=2))
    with pytest.raises(ValueError,match='after the signal'):
        record_event(store,key,PaperEvent(kind='observation',observed_at=start+timedelta(seconds=2),signal_id=signal['id'],nav=1000))
    timestamp = datetime.now(timezone.utc)
    observation = record_event(store,key,PaperEvent(kind='observation',observed_at=timestamp,signal_id=signal['id'],nav=999,weights={'A':.4},cost_bps=3))
    result = monitor([observation],{signal['id']:signal},{'initial_nav':1000,'gross':1,'net':1,'asset':.2})
    assert result['mean_cost_drift_bps'] == 1
    assert result['breaches'][0]['limit'] == 'asset'
    assert result['returns'][0] == pytest.approx(-.001)
    with pytest.raises(ValidationError):
        PaperEvent(kind='signal',observed_at=datetime.now())


def test_monitor_exposes_drift_without_annualizing_irregular_marks():
    signals = {'a':{'weights':{'A':.2},'cost_bps':1,'expected_return':.001},
               'b':{'weights':{'A':.2},'cost_bps':1,'expected_return':.001}}
    observations = [{'signal_id': key, 'observed_at':f'2026-09-22T12:0{i}:00Z', 'weights':{'A':.4},
                     'cost_bps':3,'nav':1000-i*10,'fills':[],'regime':str(i)} for i,key in enumerate(('a','b'))]
    result = monitor(observations,signals,{'initial_nav':1000,'gross':1,'net':1,'asset':.3,
                     'max_cost_drift_bps':1,'min_return_drift':0})
    assert result['performance']['cagr'] is None
    assert result['performance']['sharpe'] is None
    assert result['performance']['total_return'] == pytest.approx(-.01)
    assert result['mean_absolute_weight_deviation'] == pytest.approx(.2)
    assert {r['kind'] for r in result['alerts']} == {'execution_cost_drift','performance_decay'}
    assert result['regime_changes'] == 1
