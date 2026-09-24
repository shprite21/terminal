"""Immutable survival runs on Q's existing SQLite Store and shared bounded queue."""
import io
from pathlib import Path
import re
from uuid import uuid4

import pandas as pd
from fastapi import HTTPException

from data.models import MarketDataBundle
from evidence.storage import Store, digest, now
from research.workspace import ResearchRequest, code_provenance
from .forward import monitor, paper_events, record_event
from .models import VERSION
from .pipeline import Context, run_pipeline, strategy_key


def check_id(key):
    if not re.fullmatch(r'[a-f0-9]{64}', key):
        raise HTTPException(404, 'Survival artifact unavailable')


class SurvivalService:
    def __init__(self, workspace):
        self.workspace = workspace
        self.store = Store(workspace.root.parent / 'survival')
        for run in self.store.list('survival_run'):
            events = self.store.events(run['id'])
            if not events or events[-1]['action'] in {'queued', 'running', 'layer'}:
                self.store.event(run['id'], 'failed', {'reason': 'Engine restarted; immutable inputs retained. Submit again to retry.'})

    def get(self, key):
        check_id(key)
        try:
            run = self.store.get(key, 'survival_run')
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        events = self.store.events(key)
        latest = events[-1] if events else {'action': 'queued', 'body': {}}
        result = self.store.get(latest['body']['result_id'], 'survival_result') if latest['action'] == 'completed' else None
        return {'id': key, **run, 'status': latest['action'] if latest['action'] != 'layer' else 'running',
                'layers': [e['body'] for e in events if e['action'] == 'layer'],
                'error': latest['body'].get('reason'), 'result': result,
                'result_id': latest['body'].get('result_id'), 'updated_at': events[-1]['created'] if events else run['created_at']}

    def list(self, experiment_id=None):
        summaries = []
        for row in self.store.list('survival_run'):
            if experiment_id and row['experiment_id'] != experiment_id:
                continue
            run = self.get(row['id'])
            summaries.append({k: run[k] for k in ('id', 'experiment_id', 'created_at', 'status', 'error', 'input_hash')}
                             | {'summary': run['result']['summary'] if run['result'] else None})
        return summaries

    def _snapshot(self, experiment_id):
        job = self.workspace.get(experiment_id)
        if job['status'] != 'completed':
            raise HTTPException(409, 'Survival requires a completed experiment with archived data; failed experiments remain in the book')
        directory = self.workspace.directory(experiment_id)
        prices, benchmark = (directory / 'prices.csv').read_bytes(), (directory / 'benchmark.csv').read_bytes()
        fingerprint = digest(prices + benchmark)
        if fingerprint != job['result']['data']['snapshot_sha256']:
            raise HTTPException(409, 'Archived dataset fingerprint mismatch; refusing altered experiment inputs')
        return job, {'prices_csv': prices.decode('utf-8'), 'benchmark_csv': benchmark.decode('utf-8'),
                     'dataset_hash': fingerprint, 'metadata': job['result']['data']}

    def submit(self, submission):
        ws = self.workspace
        with ws.lock:
            job, snapshot = self._snapshot(submission.experiment_id)
            request = ResearchRequest.model_validate(job['request'])
            peers = {}
            for peer_id in submission.peer_experiment_ids:
                if peer_id == submission.experiment_id:
                    raise HTTPException(422, 'Select another experiment for portfolio interaction')
                peer = ws.get(peer_id)
                if peer['status'] != 'completed':
                    raise HTTPException(422, 'Peer experiment is incomplete')
                if (peer['result']['data'].get('currency') != job['result']['data'].get('currency')
                        or peer['request']['data_mode'] != job['request']['data_mode']):
                    raise HTTPException(422, 'Peer comparison requires matching currency and data mode')
                peers[peer_id] = peer['result']['equity_curve']
            paper = None
            if submission.forward_record_id:
                record = self.store.get(submission.forward_record_id, 'survival_paper')
                if record['experiment_id'] != submission.experiment_id:
                    raise HTTPException(422, 'Forward record belongs to another experiment')
                paper = self.paper(submission.forward_record_id)
                paper.pop('evaluated_at', None)
            # Snapshot executing code as well as the original experiment's code.
            # A new validation uses current code; it does not rewrite old results.
            source_dir = Path(self.store.root) / 'sources' / uuid4().hex
            source_dir.mkdir(parents=True)
            code = code_provenance(source_dir)
            source_bytes = (source_dir / 'source.zip').read_bytes()
            protocol = digest(submission.config.model_dump())
            family = digest({'dataset': snapshot['dataset_hash'], 'code': code['source_sha256'],
                             'annualization': submission.config.annualization,
                             'hac_lags': submission.config.hac_lags, 'confidence': submission.config.confidence,
                             'train_fraction': submission.config.train_fraction, 'validation_fraction': submission.config.validation_fraction})
            prior = [t for t in self.store.list('survival_trial') if t['family'] == family
                     and not (t['experiment_id'] == submission.experiment_id and t['protocol'] == protocol)]
            prior = sorted(prior, key=lambda t: (t['created'], t['id']))
            known_history = [{'experiment_id': row['run_id'], 'status': row['status'],
                              'dataset_hash': row.get('snapshot_sha256'),
                              'name': row['name']} for row in ws.list()]
            material = {'version': VERSION, 'submission': submission.model_dump(), 'snapshot': snapshot,
                        'strategy': request.model_dump(), 'code': code, 'peers': peers, 'paper': paper,
                        'known_research_history': known_history,
                        'prior_trial_ids': [t['id'] for t in prior], 'original_provenance': job['result']['provenance']}
            cache_key = digest(material)
            for existing in self.store.list('survival_run'):
                if existing['input_hash'] == cache_key:
                    found = self.get(existing['id'])
                    if found['status'] in {'queued', 'running', 'completed'}:
                        return {**found, 'cached': True}
            if ws.pending >= 3:
                raise HTTPException(429, 'Three computations are already queued or running')
            # Bytes of raw input and source are themselves content addressed, not
            # pointers into mutable experiment files. Old artifacts never change.
            source_id = self.store.put('survival_source', {'source_sha256': code['source_sha256'], 'zip_hex': source_bytes.hex()})
            input_id = self.store.put('survival_input', material | {'source_id': source_id})
            created = now()
            key = self.store.put('survival_run', {'experiment_id': submission.experiment_id,
                'input_hash': cache_key, 'input_id': input_id, 'source_id': source_id,
                'created_at': created, 'config': submission.config.model_dump(), 'name': job['name'],
                'strategy_version': strategy_key(request), 'dataset_hash': snapshot['dataset_hash']})
            self.store.event(key, 'queued', {})
            ws.pending += 1
            ws.executor.submit(self._execute, key, request, submission.config, material, prior, family, protocol)
            return {**self.get(key), 'cached': False}

    def _execute(self, key, request, config, material, prior, family, protocol):
        try:
            self.store.event(key, 'running', {})
            snapshot = material['snapshot']
            prices = pd.read_csv(io.StringIO(snapshot['prices_csv']), index_col=[0,1], parse_dates=[1], float_precision='round_trip')
            benchmark = pd.read_csv(io.StringIO(snapshot['benchmark_csv']), index_col=0, parse_dates=[0], float_precision='round_trip')
            bundle = MarketDataBundle(ohlcv={str(s): f.droplevel(0) for s,f in prices.groupby(level=0)},
                                      benchmark=benchmark, metadata=snapshot['metadata'])
            peers = {}
            for peer_id, curve in material['peers'].items():
                frame = pd.DataFrame(curve)
                frame.index = pd.to_datetime(frame.date)
                peers[peer_id] = frame.portfolio.pct_change(fill_method=None).dropna()
            def save_trial(trial):
                self.store.put('survival_trial', {'run_id': key, 'experiment_id': material['submission']['experiment_id'],
                    'family': family, 'protocol': protocol, **trial})
            context = Context(request, bundle, config, material['submission']['experiment_id'],
                              {'dataset_hash': snapshot['dataset_hash'], 'code': material['code'],
                               'original_experiment_code': material['original_provenance'],
                               'universe': list(bundle.ohlcv), 'time_range': [str(prices.index.get_level_values(1).min()), str(prices.index.get_level_values(1).max())],
                               'source': snapshot['metadata'], 'trial_family': family,
                               'known_research_history': material['known_research_history'],
                               'prior_trial_ids': material['prior_trial_ids'], 'execution': material['original_provenance'].get('execution')},
                              peers=peers, prior_trials=prior, paper=material['paper'], trial_sink=save_trial)
            result = run_pipeline(context, lambda layer: self.store.event(key, 'layer', layer))
            result['completed_at'] = now()
            result_id = self.store.put('survival_result', result)
            self.store.event(key, 'completed', {'result_id': result_id})
        except Exception as exc:
            self.store.event(key, 'failed', {'reason': f'{type(exc).__name__}: {str(exc)[:700]}'})
        finally:
            with self.workspace.lock:
                self.workspace.pending -= 1

    def register_paper(self, registration):
        with self.workspace.lock:
            job = self.workspace.get(registration.experiment_id)
            if job['status'] != 'completed':
                raise HTTPException(409, 'Forward registration requires frozen completed research')
            request = ResearchRequest.model_validate(job['request'])
            body = {'created_at': now(), 'experiment_id': registration.experiment_id,
                    'strategy_version': strategy_key(request), 'request': request.model_dump(),
                    'initial_nav': registration.initial_nav, 'universe': job['result']['data']['symbols'],
                    'source': 'user_recorded_paper', 'broker_verified': False, 'live_order_submission': False}
            key = self.store.put('survival_paper', body)
            return {'id': key, **body}

    def append_paper(self, record_id, event):
        check_id(record_id)
        with self.workspace.lock:
            return record_event(self.store, record_id, event)

    def paper(self, record_id):
        check_id(record_id)
        record = self.store.get(record_id, 'survival_paper')
        entries = paper_events(self.store, record_id)
        request = record['request']
        result = monitor([e for e in entries if e['kind'] == 'observation'],
                         {e['id']: e for e in entries if e['kind'] == 'signal'},
                         {'initial_nav': record['initial_nav'], 'gross': request['max_gross_exposure'],
                          'net': request['max_net_exposure'], 'asset': request['max_asset_weight']})
        return {'id': record_id, **record, **result, 'events': entries}
