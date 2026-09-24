"""Q's local research service. One bounded compute queue, no order endpoints."""
from __future__ import annotations

import io
import json
import os
import secrets
import re
import threading
import zipfile
from datetime import date
from pathlib import Path
from uuid import uuid4
from contextlib import asynccontextmanager

import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field

from apps import research_api
from portfolio.custom import PortfolioRequest, MarketDataError, analyze_portfolio
from evidence.storage import Store, canonical, digest
from evidence.models import Hypothesis, Strategy, Calendar, Instrument
from evidence.bar_lab import BarConfig, compare_periods
from evidence.market_making import MMConfig, run_mm, MM_LIMITATIONS
from evidence.lab_data import synthetic_history, yahoo_history, load_bars
from evidence.workbench import TEMPLATES, template, guidance
from evidence.experiments import save_hypothesis, freeze_strategy, run_experiment, robustness, walk_forward, candidate_review, export_zip
from evidence.provider import ProviderError

ROOT = Path(os.environ.get('Q_FLAGSHIP_DATA', Path(__file__).resolve().parents[2] / '.data/flagship'))
_store = None
_lock = threading.RLock()
_provider = None

def store():
    global _store
    with _lock:
        if _store is None:
            _store = Store(ROOT / 'evidence')
            # Only the Q process owns this copied registry. Original app is untouched.
            for job in _store.list('job'):
                events = _store.events(job['id'])
                if not events or events[-1]['action'] in {'queued', 'running', 'progress', 'cancel_requested'}:
                    _store.event(job['id'], 'interrupted', {'reason': 'Research service restarted; retry from saved inputs.'})
        return _store

def workspace():
    with research_api._workspace_lock:
        if research_api._workspace is None:
            research_api._workspace = research_api.ResearchWorkspace(ROOT / 'experiments')
        return research_api._workspace

# The retained regime endpoints use exactly the same scheduler and storage root.
research_api.workspace = workspace

@asynccontextmanager
async def lifespan(app):
    yield
    if research_api._workspace is not None:
        research_api._workspace.executor.shutdown(wait=True, cancel_futures=False)

app = FastAPI(title='Q flagship research', lifespan=lifespan)
app.include_router(research_api.router)

@app.middleware('http')
async def local_gateway_only(request: Request, call_next):
    token = os.environ.get('Q_ENGINE_TOKEN', '')
    if not token or not secrets.compare_digest(request.headers.get('x-q-engine-token', ''), token):
        return JSONResponse({'detail': 'Use the Q gateway.'}, status_code=403)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Do not echo submitted credentials or request bodies in error payloads.
    return JSONResponse({'detail': [{'loc': e['loc'], 'msg': e['msg']} for e in exc.errors()]}, status_code=422)

@app.exception_handler(ValueError)
async def value_error(request, exc):
    return JSONResponse({'detail': str(exc)[:800]}, status_code=422)

@app.exception_handler(ProviderError)
async def provider_error(request, exc):
    return JSONResponse({'detail': str(exc)}, status_code=422)

@app.get('/api/health')
def health():
    return {'status': 'ok', 'mode': 'research_only', 'liveOrderSubmission': False,
            'compute_workers': 1, 'queued_or_running': research_api._workspace.pending if research_api._workspace else 0}

@app.get('/api/research/market-history')
def market_history(symbol: str, source: str = 'yahoo', period: str = '2y', seed: int = 42):
    from data.provider_history import terminal_history
    return terminal_history(symbol, source, period, seed)

@app.post('/api/portfolio/analyze')
def portfolio(request: PortfolioRequest):
    # Queue behind research work to avoid competing BLAS jobs.
    ws = workspace()
    with ws.lock:
        if ws.pending >= 3:
            raise HTTPException(429, 'Three computations are already queued or running.')
        ws.pending += 1
        future = ws.executor.submit(analyze_portfolio, request)
    try:
        return future.result()
    except MarketDataError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        with ws.lock: ws.pending -= 1

KINDS = {'lab_dataset','lab_report','mm_dataset','mm_report','dataset','hypothesis','strategy','report',
         'job','trial','robustness_result','walk_forward_result','robustness_batch','candidate_review',
         'quality_review','instrument_master','download','regime_archive','regime_suite','quant_result','quant_dataset'}

def archived_experiment(key):
    if not re.fullmatch(r'\d{8}T\d{6}Z-[a-f0-9]{8}', key):
        raise HTTPException(404, 'Archived experiment unavailable')
    directory = ROOT / 'experiments' / key
    file = directory / 'experiment.json'
    if not file.is_file(): raise HTTPException(404, 'Archived experiment unavailable')
    return directory, json.loads(file.read_text(encoding='utf-8'))

def check_kind(kind):
    if kind not in KINDS: raise HTTPException(404, 'Unknown artifact type')

def submit(label, function):
    ws, db = workspace(), store()
    with ws.lock:
        if ws.pending >= 3: raise HTTPException(429, 'Three computations are already queued or running.')
        key = db.put('job', {'nonce': uuid4().hex, 'label': label})
        db.event(key, 'queued', {})
        ws.pending += 1
        def cancelled():
            return any(e['action'] == 'cancel_requested' for e in db.events(key))
        def progress(done, total):
            db.event(key, 'progress', {'done': done, 'total': total})
        def work():
            try:
                if cancelled(): raise InterruptedError()
                db.event(key, 'running', {})
                result = function(cancelled, progress)
                with db.db() as con:
                    row = con.execute('SELECT kind FROM artifacts WHERE id=?', (result,)).fetchone()
                db.event(key, 'completed', {'artifact_id': result, 'artifact_kind': row[0] if row else None})
            except InterruptedError:
                db.event(key, 'cancelled', {})
            except Exception as exc:
                status = 'cancelled' if isinstance(exc, ProviderError) and exc.kind == 'cancelled' else 'failed'
                db.event(key, status, {'reason': str(exc)[:800] if isinstance(exc,(ValueError,ProviderError)) else 'Computation failed; no completed result.'})
            finally:
                with ws.lock: ws.pending -= 1
        ws.executor.submit(work)
    return {'id': key, 'kind': 'job', 'status': 'queued'}

@app.get('/api/evidence/catalog')
def catalog():
    from qresearch.service import catalog as quant_catalog
    return {'bar': BarConfig.model_json_schema(), 'mm': MMConfig.model_json_schema(),
            'strategy': Strategy.model_json_schema(), 'hypothesis': Hypothesis.model_json_schema(),
            'calendar': Calendar.model_json_schema(),
            'templates': {name: template(name) for name in TEMPLATES},
            'mm_limitations': MM_LIMITATIONS,
            'bar_defaults': BarConfig().model_dump(), 'mm_defaults': MMConfig().model_dump(),
            'quant': quant_catalog(), 'kinds': sorted(KINDS)}

@app.get('/api/evidence/artifacts/{kind}')
def list_artifacts(kind: str, offset: int = 0, limit: int = 50):
    check_kind(kind)
    if offset < 0 or not 1 <= limit <= 100: raise HTTPException(422, 'Invalid page')
    if kind == 'regime_archive':
        records = [archived_experiment(file.parent.name)[1] for file in (ROOT / 'experiments').glob('*/experiment.json')]
        records.sort(key=lambda row: (row['created_at'],row['experiment_id']), reverse=True)
        return {'total':len(records),'items':[{'id':r['experiment_id'],'created':r['created_at'],'name':r['name']} for r in records[offset:offset+limit]]}
    # Select summaries in SQLite, never materialize every saved market event on polling.
    with store().db() as db:
        count = db.execute('SELECT COUNT(*) FROM artifacts WHERE kind=?', (kind,)).fetchone()[0]
        rows = db.execute("SELECT id, created, COALESCE(json_extract(body,'$.name'),json_extract(body,'$.label'),?) FROM artifacts WHERE kind=? ORDER BY created DESC,id LIMIT ? OFFSET ?",(kind,kind,limit,offset)).fetchall()
    return {'total': count, 'items': [{'id': r[0], 'created':r[1], 'name':r[2]} for r in rows]}

@app.get('/api/evidence/artifacts/{kind}/{key}')
def get_artifact(kind: str, key: str):
    check_kind(kind)
    if kind == 'regime_archive':
        directory, record = archived_experiment(key)
        return {'id':key,'kind':kind,'artifact':record,'events':[], 'record_only':not (directory/'job.json').exists()}
    return {'id':key,'kind':kind,'artifact':store().get(key,kind),'events':store().events(key)}

@app.get('/api/evidence/artifacts/{kind}/{key}/export')
def export_artifact(kind: str, key: str):
    check_kind(kind)
    if kind == 'regime_archive':
        directory, record = archived_experiment(key)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
            for name in ['experiment.json','job.json',*[entry[0] for entry in research_api.ARTIFACTS.values()]]:
                file=directory/name
                if file.is_file(): archive.write(file,name)
            archive.writestr('ARCHIVE-NOTES.txt','Original experiment record retained unchanged. Absolute paths in old records are historical references, not verified snapshots. Shared legacy reports may have been overwritten by later original runs. No missing observations or results have been reconstructed.')
        return Response(buffer.getvalue(),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="regime-{key}.zip"'})
    db=store(); record=db.get(key,kind)
    if kind=='report':
        content=export_zip(record); extension='zip'
    elif kind in {'lab_report','mm_report'}:
        buffer=io.BytesIO()
        dataset=db.get(record['dataset_id'], 'lab_dataset' if kind=='lab_report' else 'mm_dataset')
        with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('report.json',canonical(record)); archive.writestr('dataset.json',canonical(dataset))
            archive.writestr('observations.csv',pd.DataFrame(dataset['rows']).to_csv(index=False))
            for name,expected in record.get('code',{}).get('source_hashes',{}).items():
                path=Path(__file__).parent/'evidence'/Path(name).name
                if path.is_file() and digest(path.read_bytes())==expected: archive.writestr('evidence/'+path.name,path.read_bytes())
            archive.writestr('environment.json',canonical(record.get('code',{})))
            archive.writestr('README.txt','Replay with: python -m evidence.replay_lab PATH_TO_ZIP\nOriginal code and dependency fingerprints must match.\n')
        content=buffer.getvalue(); extension='zip'
    elif kind == 'regime_suite':
        folder=ROOT/'suites'/record['run_key']
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('report.json',canonical(record))
            for file in folder.rglob('*'):
                if file.is_file(): archive.write(file,str(file.relative_to(folder)))
        content=buffer.getvalue(); extension='zip'
    else:
        content=canonical(record).encode(); extension='json'
    return Response(content,media_type='application/zip' if extension=='zip' else 'application/json',headers={'Content-Disposition': f'attachment; filename="{kind}-{key[:12]}.{extension}"'})

@app.get('/api/evidence/legacy-reports/export')
def export_shared_legacy_reports():
    folder=ROOT/'legacy-reports'; manifest=folder/'manifest.json'
    if not manifest.is_file(): raise HTTPException(404,'No shared legacy reports were migrated')
    records=json.loads(manifest.read_text(encoding='utf-8')); buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json',canonical(records))
        for record in records:
            name=record['file']
            if not re.fullmatch(r'[a-f0-9]{12}-(research_report\.html|workflow_check\.md)',name):
                raise ValueError('Invalid legacy report manifest')
            content=(folder/name).read_bytes()
            if digest(content)!=record['sha256']: raise ValueError('Legacy report integrity failure')
            archive.writestr(name,content)
    return Response(buffer.getvalue(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="shared-legacy-reports.zip"'})

class Command(BaseModel):
    model_config=ConfigDict(extra='forbid')
    payload: dict = Field(default_factory=dict)

@app.post('/api/evidence/actions/{action}')
def action(action: str, command: Command):
    global _provider
    db=store(); p=command.payload
    from qresearch.service import ACTIONS, run as run_quant
    if action in ACTIONS:
        config = ACTIONS[action][0].model_validate(p)
        return submit(action, lambda c,t: run_quant(db,action,config,c,t))
    if action == 'regime-suite':
        if p.get('acknowledge') is not True: raise ValueError('Acknowledge the synthetic full-library scenario')
        def run_suite(cancel, progress):
            from scripts.run_research import main
            from research.workspace import code_provenance
            key=uuid4().hex; folder=ROOT/'suites'/key; folder.mkdir(parents=True)
            result=main(output_dir=folder)
            return db.put('regime_suite',{'name':'SYNTHETIC full-library regime suite','synthetic':True,'run_key':key,**result,'code':code_provenance(folder),
                'limitations':['Legacy diagnostic suite: pair selection uses the complete synthetic sample. Headline performance is not causal out-of-sample validation. The PM workflow keeps pairs unavailable until a train-only selection and calibration contract exists.'],
                'assumptions':'Retained 900-session seeded scenario, generated earnings inputs and fractional portfolio weights. Legacy diagnostic model; not broker execution or evidence of live trading performance.'})
        return submit('SYNTHETIC full-library regime suite',run_suite)
    if action=='load-bars':
        start,end=date.fromisoformat(p['start']),date.fromisoformat(p['end'])
        if p['source']=='yahoo':
            return submit('Yahoo historical data',lambda c,t: yahoo_history(db,p['symbol'],start,end,p.get('interval','1d')))
        if p['source']=='massive':
            from evidence.lab_data import massive_history
            return submit('Massive historical data',lambda c,t: massive_history(db,p['symbol'],start,end,p.get('interval','1d')))
        if p['source']=='synthetic':
            return submit('SYNTHETIC historical scenario',lambda c,t: synthetic_history(db,start,end,p.get('interval','1d'),int(p.get('seed',42)),float(p.get('volatility',.02)),float(p.get('drift',.0002))))
        raise ValueError('Select Yahoo, Massive or an explicitly synthetic scenario')
    if action=='compare':
        config=BarConfig.model_validate(p['config']).model_dump()
        dates=[date.fromisoformat(p[k]) for k in ['a_start','a_end','b_start','b_end']]
        if p.get('acknowledge') is not True: raise ValueError('Review and acknowledge the data and execution assumptions')
        return submit('Day / swing comparison',lambda c,t: compare_periods(db,p['dataset_id'],config,*dates,True))
    if action=='market-making':
        config=MMConfig.model_validate(p).model_dump()
        return submit('SYNTHETIC market making',lambda c,t: run_mm(db,config))
    if action=='cancel':
        db.get(p['id'],'job'); events=db.events(p['id'])
        if events and events[-1]['action'] in {'queued','running','progress','cancel_requested'}: db.event(p['id'],'cancel_requested',{})
        return {'id':p['id'],'kind':'job'}
    if action=='guidance': return {'guidance':guidance(p)}
    if action=='save-hypothesis': return {'id':save_hypothesis(db,p),'kind':'hypothesis'}
    if action=='transition':
        db.transition(p['id'],p['state'],p['reason']); return {'id':p['id'],'kind':'hypothesis'}
    if action=='freeze-strategy': return {'id':freeze_strategy(db,p),'kind':'strategy'}
    if action=='run':
        if p.get('partition')=='holdout' and p.get('consume_holdout') is not True: raise ValueError('Explicit holdout acknowledgement is required')
        return submit('Daily research',lambda c,t: run_experiment(db,p['strategy_id'],p.get('partition','validation'),c,t))
    if action=='robustness': return submit('Bounded robustness',lambda c,t: robustness(db,p['strategy_id'],p['variants'],c,t,p.get('planned',False)))
    if action=='walk-forward': return submit('Walk-forward',lambda c,t: walk_forward(db,p['strategy_id'],p['lookbacks'],int(p['train_sessions']),int(p['validation_sessions']),int(p['test_sessions']),c,t))
    if action=='review': return {'id':candidate_review(db,p['report_id'],p['notes']),'kind':'candidate_review'}
    if action=='import-csv':
        from evidence.data import freeze_dataset
        m=p['metadata']; raw=p['csv'].encode()
        key=freeze_dataset(db,pd.read_csv(io.BytesIO(raw)),m['source'],m['instruments'],m['calendar'],date.fromisoformat(m['start']),date.fromisoformat(m['end']),m['price_note'],raw,m.get('corporate_actions',[]))
        return {'id':key,'kind':'dataset'}
    if action=='freeze-download':
        from evidence.cli import freeze_download
        return {'id':freeze_download(db,p['download_id'],p['calendar'],p['price_note'],p.get('corporate_actions',[])),'kind':'dataset'}
    if action=='angel-connect':
        from evidence.provider import AngelOneDataProvider
        provider=AngelOneDataProvider(db); provider.connect(p.get('totp') or None)
        _provider=provider
        return {'connected':True}
    if action=='angel-disconnect':
        _provider=None; return {'connected':False}
    if action=='fetch-master':
        from evidence.provider import fetch_master
        return submit('Official instrument master',lambda c,t: fetch_master(db))
    if action=='search-master':
        from evidence.provider import search_master
        return {'matches':[i.model_dump(mode='json') for i in search_master(db,p['version'],p['query'])]}
    if action=='download':
        from evidence.provider import download,validate_mappings
        if _provider is None: raise ValueError('Connect the historical-data session first')
        provider=_provider
        instruments=[Instrument.model_validate(i) for i in p['instruments']]; validate_mappings(db,instruments)
        start,end=date.fromisoformat(p['start']),date.fromisoformat(p['end'])
        return submit('Angel One history',lambda c,t: db.put('download',download(provider,db,instruments,start,end,c,t,p.get('refresh',False))))
    raise HTTPException(404,'Unknown research action')

@app.exception_handler(KeyError)
async def missing_field(request, exc):
    return JSONResponse({'detail':f'Missing required field: {str(exc)[:80]}'},status_code=422)
