"""Verify and replay an exported Q quant result without executing embedded code.

Usage: python -m qresearch.replay result.json
"""
import json
from pathlib import Path
import sys
import tempfile
import math

from evidence.storage import Store,canonical,digest
from .service import ACTIONS, PROVENANCE
from .history import load_history


def verify_result(actual, expected, action):
    """Keep ledgers/decisions exact; permit bounded HMM fitting roundoff only.

    Single-threaded native reductions can still differ across process memory
    layouts. Tolerances apply to fitted diagnostics and filtered probabilities,
    never account values, trades, dates, labels, convergence or eligibility.
    """
    differences = []
    def compare(a, b, path=()):
        if isinstance(a, dict) and isinstance(b, dict) and a.keys() == b.keys():
            for key in a: compare(a[key], b[key], path + (key,))
            return
        if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
            for i, (left, right) in enumerate(zip(a, b)): compare(left, right, path + (i,))
            return
        if canonical(a) == canonical(b): return
        fitted = path[:1] == ('fits',)
        filtered = path[:3] == ('results', 'HMM allocation', 'regimes')
        if (action == 'hmm-multi-strategy' and (fitted or filtered)
                and type(a) is float and type(b) is float
                and math.isfinite(a) and math.isfinite(b)
                and math.isclose(a, b, abs_tol=1e-10, rel_tol=1e-12)):
            differences.append(abs(a-b))
            return
        raise ValueError('Recomputed result differs from saved evidence at ' + '/'.join(map(str,path)))
    compare(actual, expected)
    return dict(exact=not differences, tolerated_fitted_values=len(differences),
                maximum_fitted_absolute_difference=max(differences,default=0.0),
                fitted_absolute_tolerance=1e-10, fitted_relative_tolerance=1e-12)


def replay(path):
    record = json.loads(Path(path).read_text(encoding='utf-8'))
    if record['code'] != PROVENANCE:
        raise ValueError('Source or dependency fingerprints differ; use the recorded environment')
    if {name: digest(code.encode()) for name, code in record['source_files'].items()} != record['code']['source_hashes']:
        raise ValueError('Embedded source integrity failure')
    schema, compute = ACTIONS[record['action']]
    with tempfile.TemporaryDirectory(prefix='q-replay-') as folder:
        config=schema.model_validate(record['configuration'])
        if record['action'] in {'multi-asset-risk','efficient-frontier','arima-forecast','basket-walk-forward','hmm-multi-strategy'}:
            db=Store(Path(folder)/'store')
            key=db.put('quant_dataset',record['inputs']['history'])
            if key!=config.history_id:raise ValueError('Historical source artifact hash mismatch')
            history,frame=load_history(db,key)
            saved=record['inputs'].get('allocation_source')
            if saved and digest({'kind':'quant_result','body':saved})!=config.source_result_id:
                raise ValueError('Allocation source artifact hash mismatch')
            kwargs={'allocation':saved['allocation'] if saved else None} if record['action']=='multi-asset-risk' else {}
            actual=compute(config,history,frame,**kwargs)
        elif record['action']=='history-from-lab':
            db=Store(Path(folder)/'store')
            for source in record['source']['datasets']:
                if db.put('lab_dataset',source['artifact'])!=source['id']:raise ValueError('Lab source artifact hash mismatch')
            actual=compute(config,db=db)
        else:
            kwargs={'folder':folder} if record['action']=='options-benchmark' else {}
            actual = compute(config, **kwargs)
    if record['action']=='options-benchmark':
        for key in ['precision','comparisons']:
            if canonical(actual['results']['Pricing benchmark'][key]) != canonical(record['results']['Pricing benchmark'][key]):
                raise ValueError('Recomputed numerical benchmark differs from saved evidence')
        return {'verified':True, 'action':record['action'], 'timings_reproduced':False}
    expected = {key: record[key] for key in actual}
    comparison = verify_result(actual, expected, record['action'])
    return {'verified': True, 'action': record['action'], **comparison}


if __name__ == '__main__':
    print(json.dumps(replay(sys.argv[1])))
