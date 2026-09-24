"""Local research jobs, persisted evidence and explicit PM decisions."""

from __future__ import annotations

import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import Field, field_validator

from data.models import MarketDataBundle
from portfolio.custom import MarketDataError
from research.experiment_tracker import ExperimentTracker
from research.workspace import (
    PROJECT_ROOT,
    ResearchRequest,
    StrictModel,
    run_research,
    strategy_catalog,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/research", tags=["research"])
ARTIFACTS = {
    "result": ("result.json", "application/json"),
    "prices": ("prices.csv", "text/csv"),
    "benchmark": ("benchmark.csv", "text/csv"),
    "targets": ("targets.csv", "text/csv"),
    "holdings": ("executed_weights.csv", "text/csv"),
    "returns": ("returns.csv", "text/csv"),
    "memo": ("memo.md", "text/markdown"),
    "source": ("source.zip", "application/zip"),
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


class Decision(StrictModel):
    status: Literal["watchlist", "paper_candidate", "rejected"]
    rationale: str = Field(min_length=10, max_length=3000)

    @field_validator("rationale")
    @classmethod
    def require_rationale(cls, value: str) -> str:
        if len(value.strip()) < 10:
            raise ValueError("Record at least 10 characters explaining the decision")
        return value.strip()


class ResearchWorkspace:
    """Single-process local job queue; all completed evidence survives restarts."""

    def __init__(self, root: Path, runner=run_research):
        self.tracker = ExperimentTracker(root)
        self.root = root
        self.runner = runner
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="research")
        self.pending = 0
        self.survival_service = None
        # Work cannot survive a process restart. Never leave phantom running jobs.
        for path in self.root.glob("*/job.json"):
            job = json.loads(path.read_text(encoding="utf-8"))
            if job["status"] in {"queued", "running"}:
                job.update(
                    status="failed",
                    stage="Interrupted",
                    updated_at=now(),
                    error="The API restarted before this run completed. Clone the configuration to retry.",
                )
                atomic_json(path, job)

    def directory(self, run_id: str) -> Path:
        if not re.fullmatch(r"\d{8}T\d{6}Z-[a-f0-9]{8}", run_id):
            raise HTTPException(404, "Research run not found")
        directory = self.root / run_id
        if not (directory / "job.json").is_file():
            raise HTTPException(404, "Research run not found")
        return directory

    def get(self, run_id: str) -> dict:
        with self.lock:
            directory = self.directory(run_id)
            job = json.loads((directory / "job.json").read_text(encoding="utf-8"))
            if job["status"] == "completed":
                job["result"] = json.loads((directory / "result.json").read_text(encoding="utf-8"))
            return job

    def list(self) -> list[dict]:
        with self.lock:
            jobs = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in self.root.glob("*/job.json")
            ]
        return sorted(jobs, key=lambda job: job["created_at"], reverse=True)

    def submit(self, request: ResearchRequest) -> dict:
        with self.lock:
            if self.pending >= 3:
                raise HTTPException(
                    429, "Three runs are already queued or running. Wait for one to finish."
                )
            record = self.tracker.start_run(
                request.name, config=request.model_dump(), notes=request.hypothesis
            )
            job = {
                "run_id": record.experiment_id,
                "name": request.name,
                "created_at": record.created_at,
                "updated_at": record.created_at,
                "status": "queued",
                "stage": "Queued",
                "request": request.model_dump(),
                "decision": None,
                "decisions": [],
                "metrics": None,
                "error": None,
            }
            atomic_json(self.root / record.experiment_id / "job.json", job)
            self.pending += 1
            self.executor.submit(self._execute, record.experiment_id, request)
            return job

    def _update(self, run_id: str, **fields) -> None:
        with self.lock:
            path = self.directory(run_id) / "job.json"
            job = json.loads(path.read_text(encoding="utf-8"))
            job.update(**fields, updated_at=now())
            atomic_json(path, job)

    def _execute(self, run_id: str, request: ResearchRequest) -> None:
        directory = self.directory(run_id)
        try:
            self._update(run_id, status="running", stage="Starting research")
            kwargs = {}
            if request.snapshot_run_id:
                parent = self.get(request.snapshot_run_id)
                if parent["status"] != "completed":
                    raise ValueError("Snapshot source must be a completed experiment")
                previous = parent["request"]
                if any(
                    previous[key] != request.model_dump()[key]
                    for key in ("data_mode", "symbols", "benchmark", "period")
                ):
                    raise ValueError(
                        "Archived data needs the same universe, source, history and benchmark. Clear snapshot reuse to change market inputs."
                    )
                source_dir = self.directory(request.snapshot_run_id)
                prices = pd.read_csv(
                    source_dir / "prices.csv",
                    index_col=[0, 1],
                    parse_dates=[1],
                    float_precision="round_trip",
                )
                benchmark = pd.read_csv(
                    source_dir / "benchmark.csv",
                    index_col=0,
                    parse_dates=[0],
                    float_precision="round_trip",
                )
                kwargs["bundle"] = MarketDataBundle(
                    ohlcv={
                        str(symbol): frame.droplevel(0) for symbol, frame in prices.groupby(level=0)
                    },
                    benchmark=benchmark,
                    metadata=parent["result"]["data"].copy(),
                )
            result = self.runner(
                request,
                directory,
                progress=lambda stage: self._update(run_id, stage=stage),
                **kwargs,
            )
            record = self.tracker.load(run_id)
            record.metrics = result["metrics"]
            record.artifacts = {key: str(directory / file) for key, (file, _) in ARTIFACTS.items()}
            self.tracker.save(record)
            self._write_memo(run_id, result, [])
            self._update(
                run_id,
                status="completed",
                stage="Evidence ready",
                metrics=result["metrics"],
                validation_metrics=result["validation"]["metrics"],
                snapshot_sha256=result["data"]["snapshot_sha256"],
                evaluation_start=result["data"]["evaluation_start"],
                end_date=result["data"]["end_date"],
                paper_candidate_eligible=result["paper_candidate_eligible"],
            )
        except (MarketDataError, ValueError) as exc:
            self._update(run_id, status="failed", stage="Research failed", error=str(exc))
        except Exception:
            logger.exception("Research job %s failed", run_id)
            self._update(
                run_id,
                status="failed",
                stage="Research failed",
                error="Research could not complete. Check the API log for details, then retry the configuration.",
            )
        finally:
            with self.lock:
                self.pending -= 1

    def decide(self, run_id: str, decision: Decision) -> dict:
        with self.lock:
            job = self.get(run_id)
            if job["status"] != "completed":
                raise HTTPException(409, "A decision needs a completed evidence pack")
            result = job.pop("result")
            if decision.status == "paper_candidate" and not result["paper_candidate_eligible"]:
                raise HTTPException(
                    409, "Resolve blocked research gates before marking a paper candidate"
                )
            if decision.status == "paper_candidate":
                survival = survival_service().list(run_id)
                if survival:
                    latest = survival[0]
                    if latest['status'] != 'completed' or not latest['summary']['research_gates_satisfied']:
                        raise HTTPException(409, "Resolve the latest Strategy Survival failures or required unavailable layers before marking a paper candidate")
            entry = {**decision.model_dump(), "recorded_at": now(), "actor": "local PM"}
            job["decisions"].append(entry)
            job["decision"] = entry
            job["updated_at"] = now()
            atomic_json(self.directory(run_id) / "job.json", job)
            self._write_memo(run_id, result, job["decisions"])
            return self.get(run_id)

    def _write_memo(self, run_id: str, result: dict, decisions: list) -> None:
        request, data = result["request"], result["data"]
        content = [
            f"# {request['name']}",
            "",
            request["hypothesis"],
            "",
            f"Run: {run_id}",
            f"Source: {data['source']}",
            f"Sample: {data['start_date']} to {data['end_date']}",
            f"Evaluation starts: {data['evaluation_start']}",
            f"Snapshot SHA-256: {data['snapshot_sha256']}",
            f"Source SHA-256: {result['provenance']['source_sha256']}",
            "",
            "## Mandate and configuration",
            "",
            "```json",
            json.dumps(request, indent=2),
            "```",
            "",
            "## Validation",
            "",
            result["validation"]["method"],
            "",
        ]
        for gate in result["gates"]:
            content.append(f"- {gate['name']}: {gate['status']} — {gate['detail']}")
        content += [
            "",
            "## Metrics",
            "",
            "```json",
            json.dumps(
                {"research": result["metrics"], "walk_forward": result["validation"]["metrics"]},
                indent=2,
            ),
            "```",
            "",
            "## Decisions",
            "",
        ]
        content += [
            f"- {d['recorded_at']} · {d['status']} · {d['rationale']}" for d in decisions
        ] or ["No PM decision recorded."]
        content += ["", "## Limitations", "", *[f"- {note}" for note in result["limitations"]]]
        path = self.directory(run_id) / "memo.md"
        temporary = path.with_suffix(".tmp")
        temporary.write_text("\n".join(content), encoding="utf-8")
        temporary.replace(path)


_workspace: ResearchWorkspace | None = None
_workspace_lock = threading.Lock()


def workspace() -> ResearchWorkspace:
    global _workspace
    with _workspace_lock:
        if _workspace is None:
            _workspace = ResearchWorkspace(PROJECT_ROOT / "outputs" / "experiments")
        return _workspace


@router.get("/catalog")
def catalog():
    return strategy_catalog()


@router.get("/runs")
def list_runs():
    return {"runs": workspace().list()}


@router.post("/runs", status_code=202)
def create_run(request: ResearchRequest):
    return workspace().submit(request)


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    return workspace().get(run_id)


@router.post("/runs/{run_id}/decision")
def record_decision(run_id: str, decision: Decision):
    return workspace().decide(run_id, decision)


@router.get("/runs/{run_id}/artifacts/{artifact}")
def download_artifact(run_id: str, artifact: str):
    job = workspace().get(run_id)
    if job["status"] != "completed" or artifact not in ARTIFACTS:
        raise HTTPException(404, "Artifact not available")
    filename, media_type = ARTIFACTS[artifact]
    path = workspace().directory(run_id) / filename
    if not path.is_file():
        raise HTTPException(404, "Artifact not available")
    return FileResponse(path, media_type=media_type, filename=f"{run_id}-{filename}")


# Survival reuses the shared workspace executor and immutable evidence Store;
# existing research routes and archived result documents remain unchanged.
from research.survival.models import SurvivalSubmission, SurvivalConfig  # noqa: E402
from research.survival.forward import PaperRegistration, PaperEvent  # noqa: E402


def survival_service():
    from research.survival.service import SurvivalService
    ws = workspace()
    with ws.lock:
        if ws.survival_service is None:
            ws.survival_service = SurvivalService(ws)
        return ws.survival_service


@router.get('/survival/catalog')
def survival_catalog():
    from research.survival.methods import method
    return {'layers': [method(i) for i in range(1, 19)],
            'defaults': SurvivalConfig().model_dump(), 'schema': SurvivalConfig.model_json_schema(),
            'live_order_submission': False}


@router.post('/survival/runs', status_code=202)
def create_survival(request: SurvivalSubmission):
    return survival_service().submit(request)


@router.get('/survival/runs')
def list_survival(experiment_id: str | None = None):
    return {'runs': survival_service().list(experiment_id)}


@router.get('/survival/runs/{key}')
def get_survival(key: str):
    return survival_service().get(key)


@router.get('/survival/runs/{key}/export')
def export_survival(key: str):
    import io
    import zipfile
    from fastapi.responses import Response
    service = survival_service()
    run = service.get(key)
    inputs = service.store.get(run['input_id'], 'survival_input')
    source = service.store.get(run['source_id'], 'survival_source')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('run.json', json.dumps(run, indent=2, allow_nan=False))
        archive.writestr('inputs.json', json.dumps(inputs, indent=2, allow_nan=False))
        archive.writestr('source.zip', bytes.fromhex(source['zip_hex']))
        trials = [t for t in service.store.list('survival_trial') if t['run_id'] == key or t['id'] in inputs['prior_trial_ids']]
        archive.writestr('trials.json', json.dumps(trials, indent=2, allow_nan=False))
        archive.writestr('events.json', json.dumps(service.store.events(key), indent=2, allow_nan=False))
    return Response(buffer.getvalue(), media_type='application/zip',
                    headers={'Content-Disposition': f'attachment; filename="q-survival-{key[:12]}.zip"'})


@router.get('/survival/paper')
def list_paper(experiment_id: str | None = None):
    return {'records': [r for r in survival_service().store.list('survival_paper')
                        if experiment_id is None or r['experiment_id'] == experiment_id]}


@router.post('/survival/paper', status_code=201)
def register_survival_paper(request: PaperRegistration):
    return survival_service().register_paper(request)


@router.get('/survival/paper/{key}')
def get_survival_paper(key: str):
    return survival_service().paper(key)


@router.post('/survival/paper/{key}/events', status_code=201)
def append_survival_paper(key: str, event: PaperEvent):
    return survival_service().append_paper(key, event)
