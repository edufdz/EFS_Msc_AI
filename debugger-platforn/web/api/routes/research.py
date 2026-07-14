"""Research subsystem API: anonymisation, ground truth, RQ1-RQ4 experiments.

Unlike Phases A-D these endpoints are not tied to a debugging session: a
research run is an offline computation over a conversation export and an
agent map.  Runs execute in a background thread and are polled by run_id
(the run registry keeps progress lines, status, and the results payload).
"""

from __future__ import annotations

import asyncio
import json
import threading
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from web.api.config import PROJECT_ROOT

import sys

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

router = APIRouter(prefix="/api/research", tags=["research"])

_EXPERIMENTS_DIR = PROJECT_ROOT / "experiments_output"

# In-memory run registry: run_id -> state dict
_runs: Dict[str, Dict[str, Any]] = {}
_runs_lock = threading.Lock()


class ExperimentRequest(BaseModel):
    export_path: str
    agent_map_path: str
    budget: int = 100
    holdout_fraction: float = 0.3
    min_score: float = 3.0
    per_category_cap: int = 25
    rng_seed: int = 42
    mode: str = "static"                # "static" | "execute"
    connector: str = "mock"
    seed_budget_fraction: float = 0.35
    language: Optional[str] = None
    arms: Optional[List[str]] = None    # default: ["blind", "feedback"]


class AnonymizeRequest(BaseModel):
    input_path: str
    output_path: str
    limit: Optional[int] = None


def _new_run(kind: str) -> Dict[str, Any]:
    run_id = f"{kind}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    state = {
        "run_id": run_id,
        "kind": kind,
        "status": "running",
        "progress": [],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "error": None,
        "output_dir": None,
    }
    with _runs_lock:
        _runs[run_id] = state
    return state


def _resolve(path_str: str) -> Path:
    """Resolve a client-supplied path relative to the platform root."""
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


# ----------------------------------------------------------------------
# Experiments
# ----------------------------------------------------------------------


@router.post("/experiments/run")
async def run_experiments(req: ExperimentRequest):
    export_path = _resolve(req.export_path)
    agent_map_path = _resolve(req.agent_map_path)
    if not export_path.exists():
        raise HTTPException(status_code=400, detail=f"Export not found: {export_path}")
    if not agent_map_path.exists():
        raise HTTPException(status_code=400, detail=f"Agent map not found: {agent_map_path}")

    state = _new_run("experiment")
    output_dir = _EXPERIMENTS_DIR / state["run_id"]
    state["output_dir"] = str(output_dir)

    def _progress(msg: str) -> None:
        state["progress"].append({
            "at": datetime.now(timezone.utc).isoformat(), "message": msg,
        })

    def _work() -> None:
        try:
            from src.experiments import ExperimentConfig, run_experiment

            config = ExperimentConfig(
                export_path=str(export_path),
                agent_map_path=str(agent_map_path),
                output_dir=str(output_dir),
                budget=req.budget,
                holdout_fraction=req.holdout_fraction,
                min_score=req.min_score,
                per_category_cap=req.per_category_cap,
                rng_seed=req.rng_seed,
                mode=req.mode,
                connector=req.connector,
                seed_budget_fraction=req.seed_budget_fraction,
                language=req.language,
                **({"arms": req.arms} if req.arms else {}),
            )
            results = run_experiment(config, on_progress=_progress)
            state["results"] = results
            state["status"] = "completed"
        except Exception as e:
            state["status"] = "error"
            state["error"] = f"{type(e).__name__}: {e}"
            traceback.print_exc()
        finally:
            state["finished_at"] = datetime.now(timezone.utc).isoformat()

    threading.Thread(target=_work, daemon=True).start()
    return {"status": "started", "run_id": state["run_id"]}


@router.post("/anonymize/run")
async def run_anonymization(req: AnonymizeRequest):
    input_path = _resolve(req.input_path)
    if not input_path.exists():
        raise HTTPException(status_code=400, detail=f"Input not found: {input_path}")
    output_path = _resolve(req.output_path)

    state = _new_run("anonymize")
    state["output_dir"] = str(output_path)

    def _work() -> None:
        try:
            from src.production.anonymize import get_anonymiser

            anonymise_fn, level = get_anonymiser()
            state["progress"].append({
                "at": datetime.now(timezone.utc).isoformat(),
                "message": f"Anonymisation pipeline: {level}",
            })

            # Reuse the CLI's field policy by importing its worker directly.
            from anonymize_export import (
                _BLOB_CONV_FIELDS,
                _DROP_CONV_FIELDS,
                _DROP_MSG_FIELDS,
                _TEXT_CONV_FIELDS,
                _TEXT_MSG_FIELDS,
            )
            from functools import lru_cache

            @lru_cache(maxsize=200_000)
            def anonymise(text: str) -> str:
                return anonymise_fn(text)

            with open(input_path) as f:
                data = json.load(f)
            conversations = data.get("conversations", [])
            if req.limit:
                conversations = conversations[: req.limit]

            for i, conv in enumerate(conversations, 1):
                for field_name in _DROP_CONV_FIELDS + _BLOB_CONV_FIELDS:
                    conv.pop(field_name, None)
                for field_name in _TEXT_CONV_FIELDS:
                    if conv.get(field_name):
                        conv[field_name] = anonymise(conv[field_name])
                for msg in conv.get("messages") or []:
                    for field_name in _DROP_MSG_FIELDS:
                        msg.pop(field_name, None)
                    for field_name in _TEXT_MSG_FIELDS:
                        if msg.get(field_name):
                            msg[field_name] = anonymise(msg[field_name])
                if i % 100 == 0:
                    state["progress"].append({
                        "at": datetime.now(timezone.utc).isoformat(),
                        "message": f"Anonymised {i}/{len(conversations)} conversations",
                    })

            data["conversations"] = conversations
            data["total_conversations"] = len(conversations)
            data["anonymisation"] = {"pipeline": level, "tool": "api"}
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w") as f:
                json.dump(data, f, ensure_ascii=False)

            state["results"] = {
                "output_path": str(output_path),
                "n_conversations": len(conversations),
                "pipeline": level,
            }
            state["status"] = "completed"
        except Exception as e:
            state["status"] = "error"
            state["error"] = f"{type(e).__name__}: {e}"
            traceback.print_exc()
        finally:
            state["finished_at"] = datetime.now(timezone.utc).isoformat()

    threading.Thread(target=_work, daemon=True).start()
    return {"status": "started", "run_id": state["run_id"]}


@router.get("/runs")
async def list_runs():
    """All in-memory runs plus persisted experiment result dirs on disk."""
    with _runs_lock:
        live = [
            {k: v for k, v in state.items() if k != "results"}
            for state in _runs.values()
        ]
    live_dirs = {state.get("output_dir") for state in _runs.values()}

    persisted: List[Dict[str, Any]] = []
    if _EXPERIMENTS_DIR.exists():
        for results_file in sorted(_EXPERIMENTS_DIR.glob("*/results.json")):
            run_dir = results_file.parent
            if str(run_dir) in live_dirs:
                continue
            try:
                data = json.loads(results_file.read_text())
                persisted.append({
                    "run_id": run_dir.name,
                    "kind": "experiment",
                    "status": "completed",
                    "started_at": data.get("generated_at"),
                    "finished_at": data.get("generated_at"),
                    "output_dir": str(run_dir),
                    "progress": [],
                    "error": None,
                })
            except (json.JSONDecodeError, OSError):
                continue

    ordered = sorted(live + persisted, key=lambda r: r.get("started_at") or "", reverse=True)
    return {"runs": ordered}


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    with _runs_lock:
        state = _runs.get(run_id)
    if state:
        return state
    # Fall back to a persisted run directory
    results_file = _EXPERIMENTS_DIR / run_id / "results.json"
    if results_file.exists():
        return {
            "run_id": run_id,
            "kind": "experiment",
            "status": "completed",
            "progress": [],
            "error": None,
            "output_dir": str(results_file.parent),
            "results": json.loads(results_file.read_text()),
        }
    raise HTTPException(status_code=404, detail="Run not found")


@router.get("/runs/{run_id}/chart/{chart_name}")
async def get_chart(run_id: str, chart_name: str):
    """Serve a rendered chart PNG for a run."""
    from fastapi.responses import FileResponse

    if not chart_name.replace("_", "").replace("-", "").removesuffix(".png").isalnum():
        raise HTTPException(status_code=400, detail="Invalid chart name")
    with _runs_lock:
        state = _runs.get(run_id)
    output_dir = Path(state["output_dir"]) if state and state.get("output_dir") else _EXPERIMENTS_DIR / run_id
    chart_path = output_dir / "charts" / chart_name
    if not chart_path.exists():
        raise HTTPException(status_code=404, detail="Chart not found")
    return FileResponse(chart_path, media_type="image/png")


@router.get("/projection")
async def get_projection():
    """The frozen shared taxonomy + both projection tables."""
    from src.evaluation.projection import projection_table
    from src.evaluation.taxonomy import CATEGORY_SEVERITY, FailureCategory

    table = projection_table()
    table["categories"] = [
        {"category": c.value, "severity": CATEGORY_SEVERITY[c]}
        for c in FailureCategory
    ]
    return table


@router.get("/ground-truth/preview")
async def ground_truth_preview(export_path: str, min_score: float = 3.0):
    """Quick ground-truth summary of an export (no experiment run)."""
    path = _resolve(export_path)
    if not path.exists():
        raise HTTPException(status_code=400, detail=f"Export not found: {path}")

    from src.production import build_ground_truth, load_export

    loop = asyncio.get_event_loop()

    def _compute():
        conversations = load_export(path)
        gt = build_ground_truth(conversations, min_score=min_score)
        return {
            "n_conversations_analysed": gt.n_conversations_analysed,
            "n_failures": len(gt.failures),
            "min_score": min_score,
            "by_category": gt.by_category,
            "by_shared_category": gt.by_shared_category,
            "worst": [f.to_dict() for f in sorted(
                gt.failures, key=lambda x: -x.failure_score
            )[:10]],
        }

    return await loop.run_in_executor(None, _compute)
