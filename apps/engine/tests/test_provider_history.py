"""Offline provider contracts; generated observations are test/scenario data."""
import json

import numpy as np
import pandas as pd
import pytest

from data.provider_history import load_provider_ohlcv, terminal_history
from portfolio.custom import MarketDataError, PortfolioRequest, analyze_portfolio
from data.research_source import load_research_bundle
from qresearch.history import DownloadConfig, download_history


def test_synthetic_is_reproducible_bounded_and_distinct_per_symbol():
    a=load_provider_ohlcv('AAPL','2y','synthetic')
    pd.testing.assert_frame_equal(a.frame,load_provider_ohlcv('AAPL','2y','synthetic').frame)
    assert not a.frame.equals(load_provider_ohlcv('MSFT','2y','synthetic').frame)
    assert not a.frame.equals(load_provider_ohlcv('AAPL','2y','synthetic',43).frame)
    assert a.frame.index[-1]==pd.Timestamp('2025-12-31')
    assert a.frame.index.is_unique and a.frame.index.is_monotonic_increasing
    assert np.isfinite(a.frame.to_numpy()).all()
    assert (a.frame.High>=a.frame[['Open','Close','Low']].max(axis=1)).all()
    assert (a.frame.Low<=a.frame[['Open','Close','High']].min(axis=1)).all()
    assert (a.frame[['Open','High','Low','Close']]>0).all().all()
    snapshot=terminal_history('AAPL','synthetic')
    assert snapshot['synthetic'] and 'SYNTHETIC' in snapshot['source']
    assert snapshot['seed']==42
    json.dumps(snapshot,allow_nan=False)


def test_synthetic_runs_through_portfolio_and_multi_asset_models():
    request=PortfolioRequest(source='synthetic',holdings=[{'ticker':'AAPL','weight':100}],benchmark='AAPL')
    result=analyze_portfolio(request)
    assert result['synthetic'] and result['seed']==42
    assert result['metrics']['excess_return']==pytest.approx(0,abs=1e-12)
    assert result['equity_curve'][0]['portfolio']==request.initial_capital
    assert result['request']['source']=='synthetic'
    bundle=load_research_bundle(['AAPL','MSFT'],'SPY','2y',source='synthetic')
    assert bundle.metadata['data_mode']=='synthetic'
    assert not bundle.close().isna().any().any()
    artifact=download_history(DownloadConfig(source='synthetic'))
    assert artifact['synthetic'] and artifact['source']['seed']==42
    assert artifact['assets']==['AAPL','MSFT','NVDA']


def test_provider_failures_never_fall_back(monkeypatch):
    monkeypatch.delenv('Q_MARKET_GATEWAY_URL',raising=False)
    with pytest.raises(MarketDataError,match='gateway'):
        load_provider_ohlcv('AAPL','1y','massive')
    with pytest.raises(MarketDataError,match='two years'):
        load_provider_ohlcv('AAPL','5y','massive')
    with pytest.raises(MarketDataError,match='Choose'):
        load_provider_ohlcv('AAPL','1y','unknown')
    import data.research_source as research
    def fail(*args):raise MarketDataError('offline fixture')
    monkeypatch.setattr(research,'load_yahoo_ohlcv',fail)
    with pytest.raises(MarketDataError,match='offline fixture'):
        terminal_history('AAPL','yahoo')


def test_synthetic_mixed_currency_portfolio_stays_blocked():
    with pytest.raises(MarketDataError,match='same quote currency'):
        analyze_portfolio(PortfolioRequest(source='synthetic',holdings=[{'ticker':'AAPL','weight':100}],benchmark='RELIANCE.NS'))
