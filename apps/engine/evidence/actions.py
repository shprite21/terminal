"""Sourced cash dividends and integer share splits; no invented action records."""
from datetime import date, datetime
from typing import Literal
from pydantic import Field, model_validator
from .models import Contract


class CorporateAction(Contract):
    instrument: str
    kind: Literal["split", "cash_dividend"]
    ex_date: date
    available_at: datetime
    source_url: str = Field(min_length=8)
    source_note: str = Field(min_length=20)
    real_data_attestation: Literal[True]
    quantity_multiplier: int | None = Field(default=None, ge=2)
    cash_per_share: float | None = Field(default=None, gt=0)
    pay_date: date | None = None

    @model_validator(mode="after")
    def valid(self):
        if not self.source_url.startswith("https://") or self.available_at.tzinfo is None:
            raise ValueError("Action requires a source and timezone-aware availability")
        if self.kind == "split" and (self.quantity_multiplier is None or self.cash_per_share is not None or self.pay_date is not None):
            raise ValueError("Integer split requires only quantity multiplier")
        if self.kind == "cash_dividend" and (self.cash_per_share is None or self.pay_date is None or self.pay_date < self.ex_date or self.quantity_multiplier is not None):
            raise ValueError("Cash dividend requires amount and payment date on/after ex-date")
        return self


def validated_actions(values, calendar, ids):
    actions = [CorporateAction.model_validate(v) for v in values]
    seen = set()
    for action in actions:
        identity = (action.instrument, action.ex_date, action.kind)
        if identity in seen:
            raise ValueError("Duplicate action; consolidate sourced same-day cash distributions explicitly")
        seen.add(identity)
        if action.instrument not in ids or action.ex_date not in calendar.sessions:
            raise ValueError("Action instrument or ex-date absent from dataset calendar")
        if action.available_at > calendar.sessions[action.ex_date][0]:
            raise ValueError("Action information not available before effective session; accounting blocked")
    return sorted(actions, key=lambda a: (a.ex_date, a.instrument, a.kind))


def split_factor(actions, instrument, first, last):
    factor = 1
    for action in actions:
        if action.instrument == instrument and action.kind == "split" and first < action.ex_date <= last:
            factor *= action.quantity_multiplier
    return factor


def apply_actions(positions, actions, day, receivables, queue):
    ledger = []
    for action in actions:
        if action.ex_date != day:
            continue
        position = positions.get(action.instrument)
        if action.kind == "split":
            factor = action.quantity_multiplier
            if position:
                before = position["quantity"] * position["entry_price"]
                position["quantity"] *= factor
                position["entry_price"] /= factor
                position["entry_cost_per_share"] /= factor
                assert abs(position["quantity"] * position["entry_price"] - before) < 1e-6
                ledger.append({"date": str(day), "instrument": action.instrument, "kind": "split", "multiplier": factor, "source": action.source_url})
            for order in queue:
                if order["instrument"] == action.instrument:
                    order["quantity"] *= factor
                    order["split_adjusted"] = True
        elif position:
            amount = position["quantity"] * action.cash_per_share
            receivables.append({"instrument": action.instrument, "pay_date": str(action.pay_date), "amount": amount, "source": action.source_url})
            ledger.append({"date": str(day), "instrument": action.instrument, "kind": "dividend_entitlement", "amount": amount, "source": action.source_url})
    return ledger
