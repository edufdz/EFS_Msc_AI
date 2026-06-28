"""Phase D: Diagnosis — API routes."""

from __future__ import annotations

import asyncio
import json
import re
import sys
import traceback
from pathlib import Path

from fastapi import APIRouter, HTTPException

from web.api.config import PROJECT_ROOT
from web.api.models.requests import PhaseDRequest
from web.api.models.responses import PhaseStatusResponse
from web.api.services.progress_emitter import ProgressEmitter
from web.api.services.session_manager import session_manager
from web.api.ws import ws_manager

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

router = APIRouter(prefix="/api/phase-d", tags=["phase-d"])


async def _run_phase_d_async(req: PhaseDRequest, emitter: ProgressEmitter) -> dict:
    """Run Phase D diagnosis asynchronously."""
    from src.diagnosis.engine import DiagnosisEngine

    session = session_manager.get_session(req.session_id)
    output_dir = Path(session.output_dir) / "results"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load failure inbox
    emitter.emit("loading_data", "Loading failure data...", 5)

    failure_inbox_path = session.artifacts.get("failure-inbox")
    if not failure_inbox_path:
        candidates = [
            Path(session.output_dir) / "results" / "failure_inbox.json",
            Path(session.output_dir) / "failure_inbox.json",
        ]
        for c in candidates:
            if c.exists():
                failure_inbox_path = str(c)
                break

    if not failure_inbox_path or not Path(failure_inbox_path).exists():
        # No failures — return empty report
        return {
            "report_id": "empty",
            "run_id": "unknown",
            "total_failures": 0,
            "clusters_found": 0,
            "clusters": [],
            "fix_proposals": [],
            "priority_ranking": [],
            "summary": {
                "total_failures_analyzed": 0,
                "total_tests": 0,
                "failure_rate": 0,
                "by_root_cause": {},
                "by_severity": {},
                "fix_proposals_by_type": {},
                "clusters_count": 0,
                "fixes_count": 0,
            },
            "generated_at": None,
        }

    with open(failure_inbox_path) as f:
        failure_inbox = json.load(f)

    # Check for zero failures
    if not failure_inbox.get("failures"):
        return {
            "report_id": "empty",
            "run_id": "unknown",
            "total_failures": 0,
            "clusters_found": 0,
            "clusters": [],
            "fix_proposals": [],
            "priority_ranking": [],
            "summary": {
                "total_failures_analyzed": 0,
                "total_tests": 0,
                "failure_rate": 0,
                "by_root_cause": {},
                "by_severity": {},
                "fix_proposals_by_type": {},
                "clusters_count": 0,
                "fixes_count": 0,
            },
            "generated_at": None,
        }

    # Load test run report
    test_report_path = session.artifacts.get("test-report")
    if not test_report_path:
        candidates = [
            Path(session.output_dir) / "results" / "test_run_report.json",
            Path(session.output_dir) / "test_run_report.json",
        ]
        for c in candidates:
            if c.exists():
                test_report_path = str(c)
                break

    test_run_report = {}
    if test_report_path and Path(test_report_path).exists():
        with open(test_report_path) as f:
            test_run_report = json.load(f)

    # Load agent map
    agent_map_path = Path(session.output_dir) / "agent_map.json"
    agent_map = {}
    if agent_map_path.exists():
        with open(agent_map_path) as f:
            agent_map = json.load(f)

    # Progress mapping for diagnosis steps
    progress_steps = {
        "Step 1": ("clustering", "Clustering failures...", 15),
        "Step 2": ("root_cause_analysis", "Analyzing root causes...", 35),
        "Step 3": ("minimal_reproduction", "Generating reproductions...", 55),
        "Step 4": ("fix_generation", "Generating fix proposals...", 75),
        "Step 5": ("priority_ranking", "Ranking by priority...", 90),
        "Diagnosis complete": ("saving_report", "Saving report...", 95),
    }

    def on_progress(msg: str):
        for key, (step, label, pct) in progress_steps.items():
            if msg.startswith(key):
                emitter.emit(step, label, pct)
                return

    # Run diagnosis in executor (synchronous engine)
    engine = DiagnosisEngine(
        use_ai=not req.skip_ai,
        use_embeddings=req.use_embeddings,
        on_progress=on_progress,
        max_retries=req.max_retries,
        backoff_base=req.backoff_base,
        backoff_max=req.backoff_max,
    )

    loop = asyncio.get_event_loop()
    report = await loop.run_in_executor(
        None, engine.diagnose, failure_inbox, test_run_report, agent_map
    )

    emitter.emit("saving_report", "Saving report...", 95)

    # Save report
    report_path = output_dir / "diagnosis_report.json"
    report_dict = report.model_dump(mode="json")
    with open(report_path, "w") as f:
        json.dump(report_dict, f, indent=2, default=str)

    session_manager.set_artifact(req.session_id, "diagnosis-report", str(report_path))

    return report_dict


@router.post("/run")
async def run_phase_d(req: PhaseDRequest):
    session = session_manager.get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.phase_status.get("d") == "running":
        raise HTTPException(status_code=409, detail="Phase D already running")

    if "c" not in session.phases_completed:
        raise HTTPException(status_code=400, detail="Phase C must be completed first")

    session_manager.set_phase_status(req.session_id, "d", "running")
    emitter = ProgressEmitter(req.session_id, "d")
    queue = ws_manager.get_queue(req.session_id)
    emitter.add_listener(queue)

    async def _run():
        try:
            result = await _run_phase_d_async(req, emitter)
            session_manager.set_phase_status(req.session_id, "d", "completed")
            session_manager.set_phase_result(req.session_id, "d", result)
            emitter.emit_complete(result)
        except Exception as e:
            session_manager.set_phase_status(req.session_id, "d", "error")
            emitter.emit_error(f"{type(e).__name__}: {e}")
            traceback.print_exc()
        finally:
            emitter.remove_listener(queue)

    asyncio.create_task(_run())
    return {"status": "started", "session_id": req.session_id}


TRACE_FILENAME_RE = re.compile(r"^trace_\d{4}_[a-f0-9]+\.json$")


@router.get("/trace/{session_id}/{trace_filename}")
async def get_trace(session_id: str, trace_filename: str):
    """Return the full conversation trace JSON for a single test."""
    if not TRACE_FILENAME_RE.match(trace_filename):
        raise HTTPException(status_code=400, detail="Invalid trace filename")

    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    trace_path = Path(session.output_dir) / "results" / "traces" / trace_filename
    if not trace_path.exists():
        raise HTTPException(status_code=404, detail="Trace file not found")

    with open(trace_path) as f:
        return json.load(f)


@router.get("/status/{session_id}", response_model=PhaseStatusResponse)
async def get_phase_d_status(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    prog = session.phase_progress.get("d", {})
    return PhaseStatusResponse(
        session_id=session_id,
        phase="d",
        status=session.phase_status.get("d", "idle"),
        progress_pct=prog.get("pct", 0),
        message=prog.get("message", ""),
        result=session.phase_results.get("d"),
    )
