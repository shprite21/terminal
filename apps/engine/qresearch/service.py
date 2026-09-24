"""Bounded research actions and immutable provenance within Q's existing store."""
from importlib.metadata import version
from pathlib import Path
import json
import platform
from functools import wraps
from threadpoolctl import threadpool_limits

from evidence.storage import digest
from .options import PricingConfig, pricing
from .option_simulation import SimulationConfig, simulate
from .option_benchmark import BenchmarkConfig, benchmark
from .history import ImportConfig,ScenarioConfig,LabHistoryConfig,DownloadConfig,download_history,import_history,scenario,from_lab,load_history
from .risk_simulation import RiskConfig,simulate_risk
from .modeling import FrontierConfig,ForecastConfig,frontier,forecast
from .basket import BasketConfig,basket
from .regimes import RegimeConfig,regimes

ROOT = Path(__file__).parent


def deterministic(compute):
    @wraps(compute)
    def wrapped(*args,**kwargs):
        # The server and standalone replay must use the same BLAS/OpenMP reduction
        # order. A seed alone does not make multithreaded HMM fitting bit-exact.
        with threadpool_limits(limits=1):
            return compute(*args,**kwargs)
    return wrapped


ACTIONS = {'options-pricing': (PricingConfig, pricing), 'options-simulation': (SimulationConfig, simulate),
           'options-benchmark': (BenchmarkConfig, benchmark),
           'history-import': (ImportConfig,import_history), 'history-scenario': (ScenarioConfig,scenario),
           'history-download': (DownloadConfig,download_history),
           'history-from-lab': (LabHistoryConfig,from_lab), 'multi-asset-risk':(RiskConfig,simulate_risk),
           'efficient-frontier':(FrontierConfig,frontier),'arima-forecast':(ForecastConfig,forecast),
           'basket-walk-forward':(BasketConfig,basket),'hmm-multi-strategy':(RegimeConfig,regimes)}
ACTIONS = {name:(schema,deterministic(compute)) for name,(schema,compute) in ACTIONS.items()}
SOURCE_FILES = {str(p.relative_to(ROOT)).replace('\\', '/'): p.read_text(encoding='utf-8')
                for p in sorted(ROOT.rglob('*')) if p.suffix in {'.py','.cpp','.hpp'}}
PROVENANCE = dict(python=platform.python_version(),numeric_threads=1,
                  dependencies={p: version(p) for p in ['numpy','pandas','pydantic','scipy','statsmodels','hmmlearn','scikit-learn','optuna','threadpoolctl']},
                  source_hashes={name: digest(code.encode()) for name, code in SOURCE_FILES.items()},
                  source_repository=json.loads((ROOT/'source-manifest.json').read_text(encoding='utf-8')))


def catalog():
    return {name: dict(schema=schema.model_json_schema(), defaults=schema().model_dump())
            for name, (schema, _) in ACTIONS.items()}


def run(db, action, config, cancel, progress):
    # Capture source once when the service imports its calculation modules.
    # Editing disk files during a job cannot relabel already-loaded code.
    inputs={}
    if action in {'multi-asset-risk','efficient-frontier','arima-forecast','basket-walk-forward','hmm-multi-strategy'}:
        history,frame=load_history(db,config.history_id)
        inputs['history']=history
        allocation=None
        if getattr(config,'source_result_id',''):
            saved=db.get(config.source_result_id,'quant_result')
            if not isinstance(saved.get('allocation'),dict):
                raise ValueError('Selected result does not contain a frozen portfolio allocation')
            allocation=saved['allocation'];inputs['allocation_source']=saved
        kwargs={'allocation':allocation} if action=='multi-asset-risk' else {}
        result=ACTIONS[action][1](config,history,frame,cancel,progress,**kwargs)
    else:
        kwargs = {'folder': db.root/'cpp-build'} if action == 'options-benchmark' else {'db':db} if action=='history-from-lab' else {}
        result = ACTIONS[action][1](config, cancel, progress, **kwargs)
    if cancel():
        raise InterruptedError()
    return db.put('quant_dataset' if action.startswith('history-') else 'quant_result', dict(**result, action=action, configuration=config.model_dump(),inputs=inputs,
                                     code=PROVENANCE, source_files=SOURCE_FILES))
