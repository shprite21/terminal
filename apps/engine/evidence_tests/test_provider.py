from datetime import date
import pytest
from evidence.provider import AngelOneDataProvider, ProviderError, SharedThrottle, chunks, download
from evidence.storage import Store
from evidence.provider import search_master, validate_mappings
import json
from pathlib import Path


class FaultTransport:
    """Transport-level faults only. No fabricated responses or market observations."""
    def __init__(self, exception):
        self.exception,self.calls=exception,0
    def getCandleData(self,params):
        self.calls+=1
        raise self.exception


def test_bounded_transport_retries(tmp_path):
    sdk=FaultTransport(TimeoutError())
    provider=AngelOneDataProvider(Store(tmp_path),sdk=sdk,account="transport-test",sleeper=lambda x:None)
    with pytest.raises(ProviderError,match="connection unavailable"):
        provider.candles({})
    assert sdk.calls==4


@pytest.mark.parametrize("kind",["auth","invalid","malformed"])
def test_non_retryable_transport_faults(tmp_path,kind):
    sdk=FaultTransport(ProviderError(kind))
    provider=AngelOneDataProvider(Store(tmp_path),sdk=sdk,account="transport-test")
    with pytest.raises(ProviderError):
        provider.candles({})
    assert sdk.calls==1


def test_missing_credentials_never_calls_sdk(tmp_path):
    provider=AngelOneDataProvider(Store(tmp_path))
    with pytest.raises(ProviderError,match="Configure"):
        provider.candles({})


@pytest.mark.parametrize("exception, category", [
    (AttributeError("private payload"), "attribute access"),
    (TypeError("private payload"), "type handling"),
    (RuntimeError("private payload"), "internal SDK processing"),
])
def test_sdk_fault_diagnostics_do_not_expose_exception_text(tmp_path, exception, category):
    sdk = FaultTransport(exception)
    provider = AngelOneDataProvider(Store(tmp_path), sdk=sdk, account="transport-test")
    with pytest.raises(ProviderError) as caught:
        provider.candles({})
    assert category in str(caught.value)
    assert "private payload" not in str(caught.value)
    assert sdk.calls == 1


def test_candle_shape_diagnostic_preserves_strict_validation(tmp_path, real_data):
    # Real fixture observation, with a transport mutation adding a non-market
    # field. No malformed observation may reach the dataset checkpoint.
    frame, _, _, _, _ = real_data
    r = frame.iloc[0]
    observation = [r.date + "T09:15:00+05:30", r.open, r.high, r.low, r.close, r.volume]
    class RecordedHistoryTransport:
        def getCandleData(self, params):
            return {"status": True, "data": [observation + [None]]}
    provider = AngelOneDataProvider(Store(tmp_path), sdk=RecordedHistoryTransport(), account="transport-test")
    with pytest.raises(ProviderError, match="row 1 has 7 fields"):
        provider.candles({})
    assert provider.store.list("download") == []


def test_interval_windows_and_full_coverage():
    result=list(chunks(date(2010,1,1),date(2024,1,12)))
    assert result[0][0]==date(2010,1,1) and result[-1][1]==date(2024,1,12)
    assert all((b-a).days < 2000 for a,b in result)
    assert all((second[0]-first[1]).days==1 for first,second in zip(result,result[1:]))


def test_resumption_preserves_real_chunks(tmp_path,real_data):
    frame,_,instruments,_,_=real_data
    class RecordedRealHistory:
        calls=0
        def candles(self,params,cancelled=lambda:False):
            self.calls+=1
            instrument=next(i for i in instruments if i.token==params['symboltoken'])
            subset=frame[frame.instrument==instrument.id]
            return [[r.date+'T09:15:00+05:30',r.open,r.high,r.low,r.close,r.volume] for r in subset.itertuples()]
    # Supplemental identifiers are not real SmartAPI tokens; this transport fixture
    # tests checkpoint behavior only, never claims authenticated Angel provenance.
    provider=RecordedRealHistory()
    store=Store(tmp_path)
    first=download(provider,store,instruments[:1],date(2024,1,1),date(2024,1,12))
    second=download(provider,store,instruments[:1],date(2024,1,1),date(2024,1,12))
    assert first==second and provider.calls==1
    assert len(next(iter(first['chunks'].values()))['rows'])==10


def test_cancelled_transport_never_called(tmp_path):
    sdk=FaultTransport(TimeoutError())
    provider=AngelOneDataProvider(Store(tmp_path),sdk=sdk,account="transport-test")
    with pytest.raises(ProviderError,match="cancelled"):
        provider.candles({},cancelled=lambda:True)
    assert sdk.calls==0


def test_minute_throttle_shared_between_workers(tmp_path):
    store=Store(tmp_path)
    timestamp=[10000.0]
    def sleep(seconds): timestamp[0]+=seconds
    first=SharedThrottle(store,"same-client",clock=lambda:timestamp[0],sleeper=sleep)
    second=SharedThrottle(store,"same-client",clock=lambda:timestamp[0],sleeper=sleep)
    for _ in range(151):
        (first if _%2 else second).acquire()
    assert timestamp[0] >= 10060


def test_real_instrument_discovery(tmp_path):
    root=Path(__file__).parent/'fixtures'
    store=Store(tmp_path)
    provenance=json.loads((root/'instrument_master_provenance.json').read_text())
    key=store.put('instrument_master',{**provenance,'rows':json.loads((root/'instrument_master_excerpt.json').read_text())})
    matches=search_master(store,key,'RELIANCE')
    assert len(matches)==1 and matches[0].symbol=='RELIANCE-EQ'
    validate_mappings(store,matches)
    assert matches[0].mapping_version==key
