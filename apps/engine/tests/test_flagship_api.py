import io
import threading
import time
import zipfile
import json
import pytest
from fastapi.testclient import TestClient
import flagship_api as api
from evidence.replay_lab import replay

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('Q_ENGINE_TOKEN','test-local-gateway-token')
    monkeypatch.setattr(api,'ROOT',tmp_path)
    monkeypatch.setattr(api,'_store',None)
    monkeypatch.setattr(api.research_api,'_workspace',None)
    with TestClient(api.app,headers={'x-q-engine-token':'test-local-gateway-token'}) as client:
        yield client

def completed(client,key):
    for _ in range(200):
        result=client.get('/api/evidence/artifacts/job/'+key).json()
        event=result['events'][-1]
        if event['action'] in {'completed','failed','cancelled'}:
            assert event['action']=='completed',event
            return event['body']['artifact_id']
        time.sleep(.02)
    raise AssertionError('Research job did not complete')

def test_private_engine_requires_token_and_has_no_orders(client):
    assert client.get('/api/health',headers={'x-q-engine-token':'wrong'}).status_code==403
    assert client.get('/api/health').json()['liveOrderSubmission'] is False
    assert client.post('/api/orders',json={}).status_code==404
    response=client.post('/api/evidence/actions/run',json={'payload':{},'secret':'do-not-echo'})
    assert response.status_code==422
    assert 'do-not-echo' not in response.text

def test_mm_job_export_replays_exactly(client,tmp_path):
    response=client.post('/api/evidence/actions/market-making',json={'payload':{'events':120,'seed':13}})
    assert response.status_code==200,response.text
    key=completed(client,response.json()['id'])
    record=client.get('/api/evidence/artifacts/mm_report/'+key).json()['artifact']
    assert record['synthetic'] is True
    response=client.get('/api/evidence/artifacts/mm_report/'+key+'/export')
    path=tmp_path/'export.zip';path.write_bytes(response.content)
    assert replay(path)['verified']
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert 'evidence/market_making.py' in archive.namelist()

def test_bars_comparison_keeps_assumptions_and_periods(client):
    payload={'source':'synthetic','start':'2025-01-01','end':'2025-06-30','seed':9,'interval':'1d'}
    dataset=completed(client,client.post('/api/evidence/actions/load-bars',json={'payload':payload}).json()['id'])
    request={'dataset_id':dataset,'config':{'lookback':2},'a_start':'2025-01-01','a_end':'2025-03-31','b_start':'2025-04-01','b_end':'2025-06-30','acknowledge':False}
    assert client.post('/api/evidence/actions/compare',json={'payload':request}).status_code==422
    request['acknowledge']=True
    report=completed(client,client.post('/api/evidence/actions/compare',json={'payload':request}).json()['id'])
    result=client.get('/api/evidence/artifacts/lab_report/'+report).json()['artifact']
    assert result['source']['synthetic'] is True
    assert set(result['results'])=={'Period A','Period B'}

def test_shared_queue_bounds_and_cancel_before_execution(client):
    gate=threading.Event(); called=[]
    try:
        one=api.submit('blocking fixture',lambda c,p: (gate.wait(3), 'fixture')[1])
        two=api.submit('cancel fixture',lambda c,p: called.append('unexpected'))
        api.submit('third fixture',lambda c,p:'fixture')
        with pytest.raises(api.HTTPException) as error: api.submit('overflow',lambda c,p:None)
        assert error.value.status_code==429
        assert api.workspace().pending==3
        client.post('/api/evidence/actions/cancel',json={'payload':{'id':two['id']}})
    finally: gate.set()
    for _ in range(100):
        if api.workspace().pending==0: break
        time.sleep(.02)
    assert not called
    assert api.store().events(two['id'])[-1]['action']=='cancelled'

def test_holdout_cannot_be_consumed_without_explicit_acknowledgement(client):
    response=client.post('/api/evidence/actions/run',json={'payload':{'strategy_id':'absent','partition':'holdout'}})
    assert response.status_code==422
    assert 'holdout' in response.text

def test_inventory_paginates_without_loading_price_rows(client):
    for i in range(7):api.store().put('lab_dataset',{'name':str(i),'rows':[{'close':123456789}]})
    first=client.get('/api/evidence/artifacts/lab_dataset?offset=0&limit=3').json()
    second=client.get('/api/evidence/artifacts/lab_dataset?offset=3&limit=3').json()
    assert first['total']==7
    assert len(first['items'])==3
    assert not ({r['id'] for r in first['items']} & {r['id'] for r in second['items']})
    assert '123456789' not in json.dumps(first)
    assert client.get('/api/evidence/artifacts/lab_dataset?limit=10000').status_code==422


def test_legacy_record_without_dashboard_job_is_readable_and_exports_only_saved_files(client,tmp_path):
    key='20260101T000000Z-1234abcd'
    folder=tmp_path/'experiments'/key;folder.mkdir(parents=True)
    record={'experiment_id':key,'name':'Original record','created_at':'2026-01-01','artifacts':{'html_report':'C:/unrelated/private.html'}}
    (folder/'experiment.json').write_text(json.dumps(record))
    listing=client.get('/api/evidence/artifacts/regime_archive').json()
    assert listing['total']==1
    fetched=client.get('/api/evidence/artifacts/regime_archive/'+key).json()
    assert fetched['record_only'] and fetched['artifact']==record
    exported=client.get('/api/evidence/artifacts/regime_archive/'+key+'/export')
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        assert set(archive.namelist())=={'experiment.json','ARCHIVE-NOTES.txt'}
    assert client.get('/api/evidence/artifacts/regime_archive/not-a-run').status_code==404


def test_regime_suite_requires_synthetic_acknowledgement(client):
    response=client.post('/api/evidence/actions/regime-suite',json={'payload':{}})
    assert response.status_code==422


def test_quant_pricing_and_simulation_save_export_and_replay(client,tmp_path):
    from qresearch.replay import replay as replay_quant
    catalog=client.get('/api/evidence/catalog').json()
    assert {'options-pricing','options-simulation','options-benchmark','multi-asset-risk'}.issubset(catalog['quant'])
    assert 'quant_result' in catalog['kinds']
    for action,payload in [('options-pricing',{'spot':110}),('options-simulation',{'steps':30})]:
        response=client.post('/api/evidence/actions/'+action,json={'payload':payload})
        assert response.status_code==200,response.text
        key=completed(client,response.json()['id'])
        record=client.get('/api/evidence/artifacts/quant_result/'+key).json()['artifact']
        assert record['action']==action
        assert 'option_simulation.py' in record['source_files']
        assert record['code']['source_hashes']
        path=tmp_path/(action+'.json')
        path.write_bytes(client.get('/api/evidence/artifacts/quant_result/'+key+'/export').content)
        assert replay_quant(path)['verified']
    invalid=client.post('/api/evidence/actions/options-simulation',json={'payload':{'steps':1000000}})
    assert invalid.status_code==422


def test_shared_legacy_reports_export_checks_hashes_and_never_follows_paths(client,tmp_path):
    folder=tmp_path/'legacy-reports';folder.mkdir()
    content=b'<html>Saved diagnostic</html>';sha=api.digest(content);name=sha[:12]+'-research_report.html'
    (folder/name).write_bytes(content)
    manifest=folder/'manifest.json';manifest.write_text(json.dumps([{'file':name,'sha256':sha}]))
    response=client.get('/api/evidence/legacy-reports/export')
    assert response.status_code==200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive: assert archive.read(name)==content
    (folder/name).write_bytes(b'changed')
    assert client.get('/api/evidence/legacy-reports/export').status_code==422
    manifest.write_text(json.dumps([{'file':'../private.txt','sha256':sha}]))
    assert client.get('/api/evidence/legacy-reports/export').status_code==422
