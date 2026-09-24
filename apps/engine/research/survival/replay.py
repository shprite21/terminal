"""Verify and replay a Survival export with the exact archived engine source.

Usage: python -m research.survival.replay path/to/export.zip
Run from the exported source tree with its recorded dependency versions when
the local source has changed. This command never executes code from an archive.
"""
import hashlib
import io
import json
from importlib.metadata import version
from pathlib import Path
import zipfile

import pandas as pd

from data.models import MarketDataBundle
from evidence.storage import digest
from research.workspace import PROJECT_ROOT, ResearchRequest
from .models import SurvivalConfig
from .pipeline import Context, run_pipeline


def replay(path):
    with zipfile.ZipFile(path) as archive:
        run = json.loads(archive.read('run.json'))
        inputs = json.loads(archive.read('inputs.json'))
        trials = json.loads(archive.read('trials.json'))
        source = archive.read('source.zip')
    if digest({'kind': 'survival_input', 'body': inputs}) != run['input_id']:
        raise ValueError('Exported inputs failed content-hash verification')
    if digest({'kind': 'survival_source', 'body': {'source_sha256': inputs['code']['source_sha256'], 'zip_hex': source.hex()}}) != run['source_id']:
        raise ValueError('Exported source failed content-hash verification')
    material = {k: v for k, v in inputs.items() if k != 'source_id'}
    if digest(material) != run['input_hash']:
        raise ValueError('Experiment/config cache hash mismatch')
    if run['result'] is None:
        raise ValueError('This job has no completed pipeline to replay')
    if digest({'kind': 'survival_result', 'body': run['result']}) != run['result_id']:
        raise ValueError('Exported result failed content-hash verification')
    current_hash = hashlib.sha256()
    with zipfile.ZipFile(io.BytesIO(source)) as archive:
        for name in archive.namelist():
            target = (PROJECT_ROOT / name).resolve()
            if not target.is_relative_to(PROJECT_ROOT.resolve()) or not target.is_file():
                raise ValueError('Archived source is not present locally; use the exported source tree')
            current_hash.update(name.encode())
            current_hash.update(target.read_bytes())
    if current_hash.hexdigest() != inputs['code']['source_sha256']:
        raise ValueError('Engine code changed; replay from the exported source tree')
    for package, expected in inputs['code']['dependencies'].items():
        if version(package) != expected:
            raise ValueError(f'Dependency version differs: {package}; use the recorded environment')
    snapshot = inputs['snapshot']
    if digest((snapshot['prices_csv'] + snapshot['benchmark_csv']).encode()) != snapshot['dataset_hash']:
        raise ValueError('Dataset fingerprint mismatch')
    raw = pd.read_csv(io.StringIO(snapshot['prices_csv']), index_col=[0,1], parse_dates=[1], float_precision='round_trip')
    benchmark = pd.read_csv(io.StringIO(snapshot['benchmark_csv']), index_col=0, parse_dates=[0], float_precision='round_trip')
    bundle = MarketDataBundle({str(s): frame.droplevel(0) for s,frame in raw.groupby(level=0)}, benchmark=benchmark, metadata=snapshot['metadata'])
    prior = []
    for trial in trials:
        if trial['id'] not in inputs['prior_trial_ids']:
            continue
        body = {k: v for k,v in trial.items() if k not in {'id','created'}}
        if digest({'kind': 'survival_trial', 'body': body}) != trial['id']:
            raise ValueError('Trial history fingerprint mismatch')
        prior.append(trial)
    if {t['id'] for t in prior} != set(inputs['prior_trial_ids']):
        raise ValueError('Export is missing prior trial history')
    prior.sort(key=lambda t: (t['created'], t['id']))
    peers = {}
    for key, curve in inputs['peers'].items():
        frame = pd.DataFrame(curve)
        frame.index = pd.to_datetime(frame.date)
        peers[key] = frame.portfolio.pct_change(fill_method=None).dropna()
    context = Context(ResearchRequest.model_validate(inputs['strategy']), bundle,
                      SurvivalConfig.model_validate(inputs['submission']['config']), run['experiment_id'],
                      run['result']['provenance'], peers=peers, prior_trials=prior, paper=inputs['paper'])
    output = run_pipeline(context)
    expected = {k: v for k, v in run['result'].items() if k != 'completed_at'}
    if digest(output) != digest(expected):
        raise ValueError('Replay result differs; inspect platform/BLAS numerical differences and archived dependencies')
    return {'verified': True, 'run_id': run['id'], 'layers': len(output['layers']), 'summary': output['summary']}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('export', type=Path)
    print(json.dumps(replay(parser.parse_args().export), indent=2))
