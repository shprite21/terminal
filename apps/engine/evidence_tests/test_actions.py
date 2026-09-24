from datetime import date, datetime
import json
from pathlib import Path
import pandas as pd
import pytest
from evidence.actions import CorporateAction, apply_actions
from evidence.engine import features, simulate
from evidence.models import Strategy, Instrument, Calendar
from evidence.data import validate_bars
from evidence.storage import digest

ROOT=Path(__file__).parent/'fixtures'


def test_real_nestle_split_preserves_cost_basis(real_data,strategy):
    payload=(ROOT/'nestle_split_prices.json').read_bytes()
    provenance=json.loads((ROOT/'nestle_split_provenance.json').read_text())
    assert digest(payload)==provenance['excerpt_sha256']
    original=json.loads(payload)
    action=json.loads((ROOT/'corporate_actions.json').read_text())[0]
    _,_,_,calendar,_=real_data
    rows=[]
    for r in original:
        day=datetime.strptime(r['TIMESTAMP'],'%d-%b-%Y').date()
        rows.append({'instrument':'NSE:NESTLEIND','date':str(day),'open':float(r['OPEN']),'high':float(r['HIGH']),
                     'low':float(r['LOW']),'close':float(r['CLOSE']),'volume':int(r['TOTTRDQTY']),
                     'available_at':calendar.sessions[day][1].isoformat()})
    frame=pd.DataFrame(rows)
    instrument=Instrument(id='NSE:NESTLEIND',symbol='NESTLEIND-EQ',token='',mapping_version=provenance['excerpt_sha256'])
    _,without=validate_bars(frame,[instrument],calendar,date(2024,1,1),date(2024,1,8))
    assert without['unexplained_discontinuities']
    _,with_action=validate_bars(frame,[instrument],calendar,date(2024,1,1),date(2024,1,8),actions=[action])
    assert with_action['status']=='ready_with_limitations'
    s=Strategy.model_validate({**strategy.model_dump(mode='json'),'universe':['NSE:NESTLEIND'],'initial_cash':100000,
                              'threshold':-1,'holding_sessions':20})
    result=simulate(frame,s,calendar,date(2024,1,2),date(2024,1,8),actions=[action])
    # Jan2 order: floor(100000 / 27223.15)=3. Jan3 actual open=27345.
    # Original cost 82035; Jan5 split turns 3 into30 shares at basis2734.5.
    assert result['fills'][0]['price']==27345
    assert result['open_positions']['NSE:NESTLEIND']['quantity']==30
    assert result['open_positions']['NSE:NESTLEIND']['entry_price']==2734.5
    assert result['equity'][-1]['cash']==pytest.approx(17965)
    assert result['equity'][-1]['equity']==pytest.approx(17965+30*2619.3)
    score=features(frame,s,calendar,[action]).query("date == '2024-01-05'").score.iloc[0]
    assert score==pytest.approx(2666.4*10/27116.4-1)
    assert len(result['cash_movements'])==1


def test_actual_tcs_dividend_entitlement_once(real_data):
    frame,*_=real_data
    action=CorporateAction.model_validate(json.loads((ROOT/'corporate_actions.json').read_text())[1])
    # Two simulated shares priced from a preserved real TCS opening observation.
    price=float(frame[(frame.instrument==action.instrument)&(frame.date=='2024-01-03')].open.iloc[0])
    positions={action.instrument:{'quantity':2,'entry_price':price,'entry_cost_per_share':0}}
    receivables=[]
    before=apply_actions(positions,[action],date(2024,1,18),receivables,[])
    on_ex=apply_actions(positions,[action],date(2024,1,19),receivables,[])
    after=apply_actions(positions,[action],date(2024,1,20),receivables,[])
    assert not before and not after
    assert on_ex[0]['amount']==54
    assert receivables==[{'instrument':action.instrument,'pay_date':'2024-02-05','amount':54,'source':action.source_url}]
    assert positions[action.instrument]['entry_price']==price  # No adjusted-price double count.
