"""Versioned contracts. Defaults are research choices, never institutional standards."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

VERSION = "1.0.0"
Status = Literal["PASS", "WARN", "FAIL", "N-A"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_default=True)


class Gate(Strict):
    layer: int = Field(ge=1, le=18)
    metric: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_.]+$")
    operator: Literal[">=", "<="]
    threshold: float
    severity: Literal["WARN", "FAIL"] = "WARN"


class SurvivalConfig(Strict):
    seed: int = Field(42, ge=0, le=2**32 - 1)
    train_fraction: float = Field(.6, ge=.3, le=.8)
    validation_fraction: float = Field(.2, ge=.1, le=.4)
    min_observations: int = Field(60, ge=20, le=1000)
    annualization: int = Field(252, ge=1, le=366)
    confidence: float = Field(.95, ge=.8, le=.999)
    bootstrap_samples: int = Field(300, ge=100, le=5000)
    block_length: int = Field(10, ge=2, le=126)
    hac_lags: int = Field(5, ge=0, le=63)
    walk_mode: Literal["rolling", "expanding"] = "expanding"
    train_window: int = Field(126, ge=60, le=1000)
    test_window: int = Field(63, ge=20, le=252)
    max_folds: int = Field(8, ge=1, le=30)
    parameter_scales: list[float] = Field(default_factory=lambda: [.8, 1., 1.2], min_length=1, max_length=9)
    cscv_blocks: int = Field(8, ge=4, le=12)
    max_cscv_trials: int = Field(64, ge=2, le=256)
    effective_trials: float | None = Field(None, ge=2, le=100000)
    dsr_assumptions: str = Field("", max_length=1000)
    spread_bps: float = Field(0, ge=0, le=100)
    participation_rate: float = Field(.01, gt=0, le=1)
    execution_delay: int = Field(1, ge=1, le=10)
    slippage_shock: float = Field(2, ge=1, le=10)
    max_universe_subsets: int = Field(4, ge=1, le=12)
    stale_bars: int = Field(5, ge=2, le=60)
    gap_warning: float = Field(.35, gt=0, le=1)
    shock_return: float = Field(-.1, ge=-.9, lt=0)
    portfolio_mix: float = Field(.2, gt=0, lt=1)
    layers: list[int] = Field(default_factory=lambda: list(range(1, 19)), min_length=1, max_length=18)
    required_layers: list[int] = Field(default_factory=lambda: [1])
    gates: list[Gate] = Field(default_factory=list, max_length=60)

    @model_validator(mode="after")
    def valid_protocol(self):
        if self.train_fraction + self.validation_fraction > .9:
            raise ValueError("Reserve at least 10% for the chronological test segment")
        if self.cscv_blocks % 2:
            raise ValueError("CSCV requires an even number of blocks")
        if any(not .5 <= p <= 1.5 for p in self.parameter_scales):
            raise ValueError("Local lookback scales must be between 0.5 and 1.5")
        if len(set(self.parameter_scales)) != len(self.parameter_scales) or 1. not in self.parameter_scales:
            raise ValueError("Include baseline 1.0 and unique parameter scales")
        if any(i not in range(1, 19) for i in self.layers + self.required_layers):
            raise ValueError("Layer IDs must be 1 through 18")
        if len(set(self.layers)) != len(self.layers) or 1 not in self.layers:
            raise ValueError("Select unique layers including mandatory integrity audit")
        if self.effective_trials is not None and len(self.dsr_assumptions.strip()) < 20:
            raise ValueError("Document effective independent trial count and IID-return assumptions for DSR")
        return self


class SurvivalSubmission(Strict):
    experiment_id: str = Field(pattern=r"^\d{8}T\d{6}Z-[a-f0-9]{8}$")
    config: SurvivalConfig = Field(default_factory=SurvivalConfig)
    peer_experiment_ids: list[str] = Field(default_factory=list, max_length=8)
    forward_record_id: str | None = Field(None, pattern=r"^[a-f0-9]{64}$")


class LayerResult(Strict):
    id: int
    name: str
    status: Status
    metrics: dict = Field(default_factory=dict)
    diagnostics: dict = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    methodology: str
    assumptions: str
    minimum_data: str
    hard_failure: bool = False
    gate_results: list[dict] = Field(default_factory=list)


def apply_gates(layer: LayerResult, config: SurvivalConfig) -> LayerResult:
    """Missing gate metrics are unresolved, never silently passed; integrity cannot be waived."""
    for gate in (g for g in config.gates if g.layer == layer.id):
        value = layer.metrics
        for key in gate.metric.split("."):
            value = value.get(key) if isinstance(value, dict) else None
        known = isinstance(value, (int, float)) and not isinstance(value, bool)
        passed = known and (value >= gate.threshold if gate.operator == ">=" else value <= gate.threshold)
        state = "PASS" if passed else gate.severity if known else "N-A"
        layer.gate_results.append({**gate.model_dump(), "value": value, "status": state})
        if not passed:
            layer.reasons.append(f"Gate {gate.metric} {gate.operator} {gate.threshold}: {value if known else 'unavailable'}")
            if layer.status != "FAIL" and state == "FAIL":
                layer.status = "FAIL"
            elif layer.status == "PASS":
                layer.status = "WARN"
    return layer


def summarize(layers: list[LayerResult], config: SurvivalConfig) -> dict:
    counts = {s: sum(layer.status == s for layer in layers) for s in ("PASS", "WARN", "FAIL", "N-A")}
    unresolved = [r.id for r in layers if r.id in config.required_layers and (r.status == "N-A" or any(g['status'] == 'N-A' for g in r.gate_results))]
    unresolved_gates = [{"layer": r.id, "metric": g['metric']} for r in layers for g in r.gate_results
                        if g['status'] == 'N-A' and g['severity'] == 'FAIL']
    return {"status": "FAIL" if counts["FAIL"] else "WARN" if counts["WARN"] or counts["N-A"] else "PASS",
            "counts": counts, "hard_failures": [r.id for r in layers if r.hard_failure],
            "unresolved_required_layers": unresolved,
            "unresolved_failure_gates": unresolved_gates,
            "research_gates_satisfied": not counts["FAIL"] and not unresolved and not unresolved_gates,
            "live_eligible": False,
            "interpretation": "Diagnostic coverage and configured gates, not a score or investment approval. WARN requires review; N-A is not evidence of survival."}
