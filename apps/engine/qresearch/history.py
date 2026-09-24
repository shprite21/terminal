"""Frozen multi-asset closing-price histories shared by Q research models."""
import csv
import io
import re
from datetime import date, datetime, timezone
from typing import Literal
from urllib.parse import urlsplit

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from evidence.storage import digest


class ImportConfig(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    name: str = 'Imported historical price matrix'
    csv: str = Field('',max_length=4_000_000)
    currency: str = 'USD'
    source_url: str = ''
    source_note: str = ''
    calendar_note: str = ''
    price_convention: Literal['adjusted_close','total_return_index'] = 'adjusted_close'


class ScenarioConfig(BaseModel):
    model_config=ConfigDict(extra='forbid')
    seed: int = Field(42,ge=0,le=2**32-1)
    observations: int = Field(600,ge=80,le=3000)
    assets: int = Field(3,ge=1,le=12)


class LabHistoryConfig(BaseModel):
    model_config=ConfigDict(extra='forbid')
    dataset_ids: list[str] = Field(default_factory=list,max_length=12)
    start: str = ''
    end: str = ''


class DownloadConfig(BaseModel):
    model_config=ConfigDict(extra='forbid')
    source: Literal['yahoo','massive','synthetic'] = 'yahoo'
    symbols: list[str] = Field(default_factory=lambda:['AAPL','MSFT','NVDA'],min_length=1,max_length=12)
    period: Literal['6mo','1y','2y','5y','10y'] = '2y'


def download_history(config,cancel=lambda:False,progress=lambda *_:None):
    from data.research_source import load_research_bundle
    if cancel():raise InterruptedError()
    assets=config.symbols
    if len(set(assets))!=len(assets):raise ValueError('Choose distinct asset symbols.')
    bundle=load_research_bundle(assets,assets[0],config.period,source=config.source)
    frame=bundle.close().rename_axis('date').reset_index()
    frame['date']=frame.date.dt.strftime('%Y-%m-%d')
    frame=validate_history(frame.to_dict('records'),assets)
    if cancel():raise InterruptedError()
    progress(1,1)
    return package(bundle.metadata['source']+' · '+ ' / '.join(assets),frame,assets,bundle.metadata['currency'],
        dict(synthetic=config.source=='synthetic',kind=bundle.metadata['source'],metadata=bundle.metadata,
             seed=42 if config.source=='synthetic' else None),
        ['SYNTHETIC: artificial per-symbol seeded observations, fixed end 2025-12-31. No exchange holidays or real liquidity.' if config.source=='synthetic' else
         'Historical daily research data. Yahoo embeds splits/dividends; Massive adjusts splits and excludes cash dividends. No forward filling or provider fallback.',
         'Only common coverage is used. Provider calendars and historical constituents are not independently verified.'])


def validate_history(observations, assets):
    if not 1<=len(assets)<=12 or len(set(assets))!=len(assets) or 'date' in assets:
        raise ValueError('Use 1–12 distinct asset columns plus date')
    if not 40<=len(observations)<=5000:
        raise ValueError('Supply 40–5,000 complete daily observations')
    if any(not re.fullmatch(r'[A-Za-z0-9.^=_-]{1,30}',a) for a in assets):
        raise ValueError('Asset names must be short ticker-style identifiers')
    frame=pd.DataFrame(observations)
    if set(frame.columns)!={'date',*assets}:
        raise ValueError('Every observation must include date and exactly the selected assets')
    days=[date.fromisoformat(str(d)) for d in frame.date]
    if any(str(d)!=str(raw) for d,raw in zip(days,frame.date)) or any(a>=b for a,b in zip(days,days[1:])):
        raise ValueError('Dates must be unique, increasing YYYY-MM-DD values; no implicit sorting or filling')
    numeric=frame[assets].astype(float).to_numpy()
    if not np.isfinite(numeric).all() or (numeric<=0).any():
        raise ValueError('All prices must be finite and positive; missing values are not filled')
    frame[assets]=numeric
    return frame


def package(name, frame, assets, currency, source, limitations):
    rows=frame.to_dict('records')
    return dict(name=name,synthetic=source['synthetic'],assets=assets,currency=currency,source=source,
        observations_sha256=digest(rows),
        results={'History':{'observations':rows}},
        charts=[dict(section='History',table='observations',keys=assets,x='date',label='Frozen closing-price history')],
        limitations=limitations)


def import_history(config,cancel=lambda:False,progress=lambda *_:None):
    if cancel():raise InterruptedError()
    source=urlsplit(config.source_url)
    if source.scheme!='https' or not source.hostname or source.username or source.password or source.query or source.fragment:
        raise ValueError('Supply an attributable HTTPS source URL without credentials, query parameters or fragments')
    if min(len(config.source_note.strip()),len(config.calendar_note.strip()))<20:
        raise ValueError('Document the data source, price adjustment convention and session coverage (20 characters each)')
    if not re.fullmatch('[A-Z]{3}',config.currency):raise ValueError('Use one three-letter currency; convert currencies before import')
    reader=csv.DictReader(io.StringIO(config.csv))
    columns=reader.fieldnames or []
    if len(columns)!=len(set(columns)) or not columns or columns[0]!='date':
        raise ValueError('CSV must start with date, then distinct asset columns')
    assets=columns[1:]
    frame=validate_history(list(reader),assets)
    if date.fromisoformat(frame.date.iloc[-1])>=datetime.now(timezone.utc).date():
        raise ValueError('Only completed historical dates before today UTC may be imported')
    progress(1,1)
    return package(config.name,frame,assets,config.currency,
        dict(synthetic=False,kind='User-supplied history',url=config.source_url,note=config.source_note,
             calendar_note=config.calendar_note,price_convention=config.price_convention,
             original_csv=config.csv,raw_sha256=digest(config.csv.encode())),
        ['User-supplied daily adjusted prices or total-return indices. Source attribution and calendar coverage are user attestations, not independently certified.',
         'Same-currency synchronized observations only. No missing observations are filled; absent exchange sessions cannot be detected without an independent calendar.',
         'Historical research inputs, not executable quotes. Production scheduling and order submission remain disabled.'])


def scenario(config,cancel=lambda:False,progress=lambda *_:None):
    rng=np.random.default_rng(config.seed)
    common=rng.normal(.0002,.01,config.observations)
    base=np.cumsum(common)
    assets=[f'SYNTH{i+1}' for i in range(config.assets)]
    matrix=[]
    for i in range(config.assets):
        noise=np.zeros(config.observations)
        innovations=rng.normal(0,.007,config.observations)
        for t in range(1,config.observations):noise[t]=.8*noise[t-1]+innovations[t]
        matrix.append((80+20*i)*np.exp(base+noise))
    frame=pd.DataFrame(np.array(matrix).T,columns=assets)
    frame.insert(0,'date',pd.bdate_range('2000-01-03',periods=config.observations).strftime('%Y-%m-%d'))
    if cancel():raise InterruptedError()
    progress(1,1)
    return package('SYNTHETIC correlated price matrix',frame,assets,'USD',
        dict(synthetic=True,kind='Seeded common random walk plus stationary AR(1) deviations',configuration=config.model_dump()),
        ['Artificial correlated and cointegrated prices in scenario USD units. Not observed instruments or evidence of trading profitability.',
         'Weekday dates are labels; no exchange holiday calendar, corporate actions or real liquidity.'])


def from_lab(config,cancel=lambda:False,progress=lambda *_:None,*,db):
    from evidence.lab_data import load_bars
    if not config.dataset_ids or len(set(config.dataset_ids))!=len(config.dataset_ids):
        raise ValueError('Select distinct saved daily lab datasets')
    start,end=date.fromisoformat(config.start),date.fromisoformat(config.end)
    if start>end:raise ValueError('Start must precede end')
    snapshots=[]; series=[]; assets=[]
    for i,key in enumerate(config.dataset_ids):
        if cancel():raise InterruptedError()
        body,bars=load_bars(db,key)
        if body['request']['interval']!='1d':raise ValueError('Only daily lab histories are supported')
        name=body['request']['symbol']
        if name in assets:raise ValueError('Choose datasets with distinct symbols')
        days=pd.to_datetime(bars.timestamp,utc=True).dt.strftime('%Y-%m-%d')
        series.append(pd.Series(bars.close.to_numpy(float),index=days,name=name).loc[str(start):str(end)])
        snapshots.append(dict(id=key,artifact=body));assets.append(name);progress(i+1,len(config.dataset_ids))
    if len({s['artifact']['currency'] for s in snapshots})!=1:
        raise ValueError('Convert currencies before combining histories')
    if len({s['artifact']['source']['synthetic'] for s in snapshots})!=1:
        raise ValueError('Real and synthetic histories cannot be mixed')
    frame=pd.concat(series,axis=1).rename_axis('date').reset_index()
    frame=validate_history(frame.to_dict('records'),assets)
    return package(' / '.join(assets)+' · saved daily history',frame,assets,snapshots[0]['artifact']['currency'],
        dict(synthetic=snapshots[0]['artifact']['source']['synthetic'],kind='Q saved daily lab histories',datasets=snapshots),
        ['Dates align by the UTC date of each source observation timestamp. Daily providers may timestamp the session start rather than its close; this is not evidence of simultaneous information or intraday availability.',
         'All selected observations must align exactly in the requested window. Provider adjustment and calendar limitations remain attached to each original dataset.'])


def load_history(db,key):
    body=db.get(key,'quant_dataset')
    rows=body['results']['History']['observations']
    if digest(rows)!=body['observations_sha256']:raise ValueError('Historical observations failed integrity verification')
    return body,validate_history(rows,body['assets'])
