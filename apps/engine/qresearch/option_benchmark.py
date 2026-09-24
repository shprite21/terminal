"""Native C++/Python benchmark on identical seeded inputs, never historic timings."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import time

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from evidence.storage import digest
from .options import values

CPP_SOURCES = {p.name: p.read_text(encoding='utf-8') for p in (Path(__file__).parent/'cpp').iterdir()
               if p.suffix in {'.cpp','.hpp'}}
KEYS = ['price','delta','gamma','vega','theta','rho']


class BenchmarkConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    seed: int = Field(42, ge=0, le=2**32-1)
    count: int = Field(5000, ge=20, le=20000)
    repeats: int = Field(3, ge=1, le=5)


def compile_cpp(folder):
    spec = importlib.util.find_spec('ziglang')
    if spec:
        zig = Path(spec.origin).parent/('zig.exe' if os.name=='nt' else 'zig')
        command, version_command = [str(zig),'c++'], [str(zig),'version']
    else:
        compiler = shutil.which('g++') or shutil.which('clang++')
        if not compiler:
            raise ValueError('C++ compiler unavailable. Install the pinned ziglang compiler from Q requirements, then retry.')
        command, version_command = [compiler], [compiler,'--version']
    compiler_version = subprocess.run(version_command, capture_output=True, text=True, check=True,
                                      stdin=subprocess.DEVNULL, timeout=10).stdout.strip()
    key = digest(dict(sources=CPP_SOURCES, command=command, version=compiler_version))
    build = Path(folder).resolve()/key
    build.mkdir(parents=True, exist_ok=True)
    binary = build/('q-options.exe' if os.name=='nt' else 'q-options')
    if not binary.is_file():
        for name, code in CPP_SOURCES.items():
            (build/name).write_text(code,encoding='utf-8')
        env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(build/'zig-cache'))
        args = command+['-O3','-std=c++17','benchmark.cpp','black_scholes.cpp','greeks.cpp','-o',str(binary)]
        compiled = subprocess.run(args,cwd=build,env=env,capture_output=True,text=True,
                                  stdin=subprocess.DEVNULL,timeout=180)
        if compiled.returncode:
            raise ValueError('C++ compilation failed: '+compiled.stderr[-600:])
    return binary, dict(compiler=compiler_version, flags=['-O3','-std=c++17'],
                        binary_sha256=digest(binary.read_bytes()), source_hash=digest(CPP_SOURCES))


def shared_inputs(config):
    rng = np.random.default_rng(config.seed)
    rows = [[float(rng.uniform(20,200)),float(rng.uniform(20,200)),float(rng.uniform(.001,5)),
             float(rng.uniform(-.05,.15)),float(rng.uniform(.01,1.5)),'call' if i%2==0 else 'put']
            for i in range(config.count)]
    # Deterministic limiting cases in BOTH engines, including the forward kink.
    edges = [(100,100,0,0,.2),(100,102,1,.1,0),(100,100,1,0,0),
             (100,100,1e-10,0,1e-10),(1,100,1,.02,.2),(100,1,1,.02,.2)]
    rows[:12] = [[*map(float,x),kind] for x in edges for kind in ['call','put']]
    return rows


def cpp_values(binary, inputs, repeats=1):
    text = f'{len(inputs)} {repeats}\n' + '\n'.join(' '.join(format(v,'.17g') for v in row[:5])
                + (' 1' if row[5]=='call' else ' -1') for row in inputs)
    native = subprocess.run([str(binary)],input=text,text=True,capture_output=True,timeout=30,check=True)
    return json.loads(native.stdout)


def benchmark(config, cancel=lambda: False, progress=lambda *_: None, *, folder):
    if cancel(): raise InterruptedError()
    binary, metadata = compile_cpp(folder)
    if cancel(): raise InterruptedError()
    inputs = shared_inputs(config)
    timings=[]
    for repeat in range(config.repeats):
        if cancel(): raise InterruptedError()
        start=time.perf_counter()
        python = [[v[k] for k in KEYS] for v in (values(*row) for row in inputs)]
        timings.append(time.perf_counter()-start)
        progress(repeat+1,config.repeats+1)
    native=cpp_values(binary,inputs,config.repeats)
    errors=[]
    for j,key in enumerate(KEYS):
        a=np.array([r[j] if r[j] is not None else np.nan for r in python])
        b=np.array([r[j] if r[j] is not None else np.nan for r in native['outputs']])
        if not np.array_equal(np.isnan(a),np.isnan(b)):
            raise ValueError('C++ and Python disagree about an undefined boundary Greek')
        finite=np.isfinite(a)&np.isfinite(b)
        delta=np.abs(a[finite]-b[finite])
        errors.append(dict(sensitivity=key,max_absolute_error=float(delta.max()),
                           max_relative_error=float((delta/np.maximum(np.abs(a[finite]),1e-12)).max())))
        if not np.allclose(a,b,atol=1e-8,rtol=1e-9,equal_nan=True):
            raise ValueError('C++ and Python numerical parity failed for '+key)
    rows=[]
    for i,(x,a,b) in enumerate(zip(inputs,python,native['outputs'])):
        row=dict(input_index=i,spot=x[0],strike=x[1],maturity_years=x[2],rate=x[3],volatility=x[4],option_type=x[5])
        row.update({'python_'+k:v for k,v in zip(KEYS,a)})
        row.update({'cpp_'+k:v for k,v in zip(KEYS,b)})
        rows.append(row)
    py_seconds,cpp_seconds=statistics.median(timings),statistics.median(native['seconds'])
    progress(config.repeats+1,config.repeats+1)
    return dict(name='Python / C++ option pricing benchmark',synthetic=True,
        benchmark=dict(**metadata,input_sha256=digest(inputs),python_seconds=timings,cpp_seconds=native['seconds']),
        results={'Pricing benchmark':dict(metrics=dict(inputs=config.count,repeats=config.repeats,
            python_median_seconds=py_seconds,cpp_median_seconds=cpp_seconds,
            observed_speed_ratio=py_seconds/cpp_seconds if cpp_seconds>0 else None),
            precision=errors,comparisons=rows)},
        limitations=['Seeded parameter scenarios and limiting cases, not market observations. Both engines consume the same saved inputs and compute price plus all five Greeks.',
            'Timings include calculation loops and result containers, excluding compilation, process startup, input generation and I/O. Python uses dictionaries/lists; C++ uses fixed arrays. This measures these implementations, not a language-wide speed guarantee.',
            'Observed times depend on this machine and its load. Timing values are not deterministic; input hashes and numerical outputs are reproducible. Parity tolerances: absolute 1e-8 and relative 1e-9; relative-error denominator floored at 1e-12.',
            'Compiler setup may finish its current compilation before cancellation. Boundary Greeks use the same documented null and half-delta conventions as the pricing tool.'])
