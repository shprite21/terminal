from datetime import datetime, date, timezone
from pathlib import Path
import json
import tempfile
from uuid import uuid4
import pandas as pd
import pytest
from evidence.models import Source, Instrument, Calendar, Strategy, Hypothesis
from evidence.storage import Store, digest
from evidence.data import freeze_dataset
from evidence.experiments import save_hypothesis, freeze_strategy

FIXTURES = Path(__file__).parent / "fixtures"


def pytest_configure(config):
    # Python's private Windows temp directories belong to their creating
    # identity. Codex and the interactive user must not share pytest's default
    # pytest-of-<username> directory. A fresh sibling avoids traversing or
    # changing permissions on another identity's private test artifacts.
    if config.option.basetemp is None:
        config.option.basetemp = str(Path(tempfile.gettempdir()).resolve() / ("evidence-pytest-" + uuid4().hex))


@pytest.fixture
def real_data():
    payload = (FIXTURES / "nse_excerpt.json").read_bytes()
    provenance = json.loads((FIXTURES / "provenance.json").read_text())
    assert digest(payload) == provenance["excerpt_sha256"]
    original = json.loads(payload)
    rows = []
    sessions = {}
    instruments = {}
    for row in original:
        day = datetime.strptime(row["TIMESTAMP"], "%d-%b-%Y").date()
        opening = datetime.fromisoformat(str(day) + "T09:15:00+05:30")
        closing = datetime.fromisoformat(str(day) + "T15:30:00+05:30")
        sessions[day] = (opening, closing)
        identifier = "NSE:" + row["ISIN"]
        instruments[identifier] = Instrument(id=identifier, symbol=row["SYMBOL"] + "-EQ", token="", mapping_version=provenance["excerpt_sha256"])
        rows.append({"instrument": identifier, "date": str(day), "open": float(row["OPEN"]), "high": float(row["HIGH"]),
                     "low": float(row["LOW"]), "close": float(row["CLOSE"]), "volume": int(row["TOTTRDQTY"]), "available_at": closing.isoformat()})
    cal = Calendar(source_url="https://www.nseindia.com/resources/exchange-communication-holidays", description="Jan 1–12 2024 sessions verified from ten official daily NSE archives; regular cash market hours 09:15–15:30 IST.", coverage_start=date(2024,1,1), coverage_end=date(2024,1,12), sessions=sessions)
    source = Source(provider="supplemental", url=provenance["sources"][0]["url"], retrieved_at=provenance["sources"][0]["retrieved_at"],
                    description="Real official NSE daily archive excerpts. All ten source URLs and archive hashes in tests/fixtures/provenance.json. Tests only, not an Angel One demonstration.",
                    raw_sha256=digest(payload), real_data_attestation=True)
    return pd.DataFrame(rows), source, list(instruments.values()), cal, payload


def zero_costs():
    # Explicit zero-friction execution assumption for isolating ledger arithmetic;
    # these are model parameters, never asserted to be actual historical charges.
    return [{"name": "Zero-friction arithmetic test assumption", "start": "2024-01-01", "end": "2024-01-12",
             "source_url": "https://www.angelone.in/exchange-transaction-charges", "applicability_note": "Deliberately zero execution-cost assumption for a numerical unit test; not actual brokerage charges.", "estimated_historical": True,
             **{k:0 for k in ["brokerage_rate", "brokerage_min", "brokerage_cap", "stt_buy", "stt_sell", "exchange_rate", "sebi_rate", "ipft_rate", "gst_rate", "stamp_buy", "dp_per_debit"]}}]


@pytest.fixture
def strategy():
    return Strategy(name="Real excerpt arithmetic", hypothesis_id="test-hypothesis", dataset_id="test-excerpt", universe=["NSE:INE002A01018"], lookback=1,
                    holding_sessions=1, max_positions=1, position_fraction=1, initial_cash=10000, slippage_bps=0, spread_bps=0,
                    train_start="2024-01-02", train_end="2024-01-03", validation_start="2024-01-04", validation_end="2024-01-09",
                    holdout_start="2024-01-10", holdout_end="2024-01-12", costs=zero_costs(), acknowledge_limitations=True)


@pytest.fixture
def registered(tmp_path, real_data, strategy):
    store = Store(tmp_path)
    frame, source, instruments, calendar, payload = real_data
    dataset = freeze_dataset(store, frame, source, instruments, calendar, date(2024,1,1),date(2024,1,12), "NSE cash bhavcopy unadjusted execution observations; dividend exclusion and action coverage explicitly limited.", payload)
    h = Hypothesis(name="Arithmetic and chronology verification", family="real_excerpt_test", author="Test suite", created_at=datetime.now(timezone.utc))
    values = h.model_dump(mode="json")
    for missing in h.missing():
        values[missing] = "Predefined numerical-test assumption; not a market finding"
    hypothesis = save_hypothesis(store, values)
    values = strategy.model_dump(mode="json")
    values.update(dataset_id=dataset, hypothesis_id=hypothesis)
    key = freeze_strategy(store, values)
    return store, key, dataset
