from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_assignment=True)


class Source(Contract):
    provider: Literal["Angel One SmartAPI", "supplemental"]
    url: str = Field(min_length=8)
    retrieved_at: datetime
    description: str = Field(min_length=10)
    raw_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    real_data_attestation: Literal[True]

    @field_validator("url")
    @classmethod
    def attributable(cls, value):
        from urllib.parse import urlsplit
        parsed = urlsplit(value)
        if parsed.username or parsed.password:
            raise ValueError("Source URLs must not contain credentials")
        if not value.startswith("https://"):
            raise ValueError("Source must be an attributable HTTPS URL")
        return value

    @field_validator("retrieved_at")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("Timezone required")
        return value


class Instrument(Contract):
    id: str = Field(min_length=3)
    exchange: Literal["NSE"] = "NSE"
    symbol: str
    token: str
    instrument_type: Literal["cash_equity"] = "cash_equity"
    mapping_version: str
    currency: Literal["INR"] = "INR"


class Calendar(Contract):
    source_url: str = Field(min_length=8)
    description: str = Field(min_length=10)
    coverage_start: date
    coverage_end: date
    # Exact exchange-local ISO datetimes, including special sessions.
    sessions: dict[date, tuple[datetime, datetime]]

    @model_validator(mode="after")
    def valid(self):
        if self.coverage_end < self.coverage_start or not self.sessions:
            raise ValueError("Calendar must have documented coverage and sessions")
        for day, (opening, closing) in self.sessions.items():
            if not (self.coverage_start <= day <= self.coverage_end):
                raise ValueError("Session outside calendar coverage")
            if opening.tzinfo is None or closing.tzinfo is None or opening >= closing:
                raise ValueError("Calendar needs timezone-aware open/close timestamps")
            from zoneinfo import ZoneInfo
            if opening.astimezone(ZoneInfo("Asia/Kolkata")).date() != day or closing.astimezone(ZoneInfo("Asia/Kolkata")).date() != day:
                raise ValueError("Session date disagrees with exchange-local timestamps")
        return self


class Hypothesis(Contract):
    name: str = Field(min_length=3)
    family: str = Field(min_length=3)
    version: int = Field(ge=1, default=1)
    author: str = Field(min_length=1)
    created_at: datetime
    explanation: str = ""
    return_supplier: str = ""
    persistence_reason: str = ""
    universe: str = ""
    liquidity: str = ""
    holding_horizon: str = ""
    information_at_decision: str = ""
    signal_definition: str = ""
    expected_relationship: str = ""
    strengthening_conditions: str = ""
    weakening_conditions: str = ""
    alternatives: str = ""
    benchmark: str = ""
    planned_experiments: str = ""
    bounded_parameters: str = ""
    primary_metric: str = ""
    diagnostics: str = ""
    rejection_criteria: str = ""
    investigation_criteria: str = ""
    limitations: str = ""
    claim_type: Literal["user assumption"] = "user assumption"

    def missing(self):
        return [k for k, v in self.model_dump().items() if isinstance(v, str) and not v.strip()]


class CostSchedule(Contract):
    name: str
    start: date
    end: date
    source_url: str = Field(min_length=8)
    applicability_note: str = Field(min_length=10)
    estimated_historical: bool
    brokerage_rate: float = Field(ge=0)
    brokerage_min: float = Field(ge=0)
    brokerage_cap: float = Field(ge=0)
    stt_buy: float = Field(ge=0)
    stt_sell: float = Field(ge=0)
    exchange_rate: float = Field(ge=0)
    sebi_rate: float = Field(ge=0)
    ipft_rate: float = Field(ge=0)
    gst_rate: float = Field(ge=0)
    stamp_buy: float = Field(ge=0)
    dp_per_debit: float = Field(ge=0)

    @model_validator(mode="after")
    def valid(self):
        if self.end < self.start or self.brokerage_cap < self.brokerage_min:
            raise ValueError("Invalid schedule range or brokerage bounds")
        return self


class Strategy(Contract):
    name: str = Field(min_length=3)
    version: int = Field(ge=1, default=1)
    hypothesis_id: str
    dataset_id: str
    universe: list[str] = Field(min_length=1)
    feature: Literal["momentum", "mean_reversion", "relative_strength", "volume_momentum"] = "momentum"
    lookback: int = Field(ge=1, le=252, default=20)
    threshold: float = 0.0
    volume_ratio: float = Field(gt=0, default=1.0)
    holding_sessions: int = Field(ge=1, le=252, default=5)
    max_positions: int = Field(ge=1, le=100, default=5)
    position_fraction: float = Field(gt=0, le=1, default=0.2)
    max_exposure: float = Field(gt=0, le=1, default=1.0)
    min_daily_turnover: float = Field(ge=0, default=0)
    initial_cash: float = Field(gt=0, default=100000)
    participation: float = Field(gt=0, le=0.1, default=0.01)
    slippage_bps: float = Field(ge=0, le=500, default=5)
    spread_bps: float = Field(ge=0, le=500, default=5)
    execution_delay: int = Field(ge=1, le=20, default=1)
    stop_fraction: float | None = Field(default=None, gt=0, lt=1)
    target_fraction: float | None = Field(default=None, gt=0, lt=10)
    train_start: date
    train_end: date
    validation_start: date
    validation_end: date
    holdout_start: date
    holdout_end: date
    costs: list[CostSchedule] = Field(min_length=1)
    price_convention: Literal["raw_price_return"] = "raw_price_return"
    acknowledge_limitations: bool = False

    @model_validator(mode="after")
    def valid(self):
        if not (self.train_start <= self.train_end < self.validation_start <= self.validation_end < self.holdout_start <= self.holdout_end):
            raise ValueError("Require disjoint chronological training, validation, and holdout")
        if len(set(self.universe)) != len(self.universe):
            raise ValueError("Duplicate instruments")
        ordered = sorted(self.costs, key=lambda s: s.start)
        if any(a.end >= b.start for a, b in zip(ordered, ordered[1:])):
            raise ValueError("Cost schedules overlap")
        return self
