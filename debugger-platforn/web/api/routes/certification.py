"""Certification — API routes."""

from __future__ import annotations

import asyncio
import json
import sys
import traceback
from pathlib import Path

from fastapi import APIRouter, HTTPException

from web.api.config import PROJECT_ROOT
from web.api.models.requests import CertificationRequest
from web.api.models.responses import PhaseStatusResponse
from web.api.services.progress_emitter import ProgressEmitter
from web.api.services.session_manager import session_manager
from web.api.ws import ws_manager

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

router = APIRouter(prefix="/api/certification", tags=["certification"])


async def _run_certification_async(req: CertificationRequest, emitter: ProgressEmitter) -> dict:
    """Run certification asynchronously."""
    from src.certification.engine import CertificationEngine

    session = session_manager.get_session(req.session_id)
    output_dir = Path(session.output_dir) / "results"
    output_dir.mkdir(parents=True, exist_ok=True)

    emitter.emit("loading_data", "Loading test and diagnosis data...", 5)

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

    if not test_report_path or not Path(test_report_path).exists():
        raise ValueError("Test run report not found — Phase C must complete first")

    with open(test_report_path) as f:
        test_run_report = json.load(f)

    # Load diagnosis report (optional — may be empty if no failures)
    diagnosis_report = None
    diag_path = session.artifacts.get("diagnosis-report")
    if not diag_path:
        candidates = [
            Path(session.output_dir) / "results" / "diagnosis_report.json",
            Path(session.output_dir) / "diagnosis_report.json",
        ]
        for c in candidates:
            if c.exists():
                diag_path = str(c)
                break
    if diag_path and Path(diag_path).exists():
        with open(diag_path) as f:
            diagnosis_report = json.load(f)

    # Load agent map
    agent_map_path = session.artifacts.get("agent-map")
    if not agent_map_path:
        agent_map_path = str(Path(session.output_dir) / "agent_map.json")
    agent_map = {}
    if Path(agent_map_path).exists():
        with open(agent_map_path) as f:
            agent_map = json.load(f)

    # Progress mapping
    progress_steps = {
        "Step 1": ("loading_data", "Loading data...", 15),
        "Step 2": ("scoring", "Scoring categories...", 50),
        "Step 3": ("saving", "Saving certification report...", 90),
        "Certification complete": ("complete", "Certification complete", 95),
    }

    def on_progress(msg: str):
        for key, (step, label, pct) in progress_steps.items():
            if msg.startswith(key):
                emitter.emit(step, label, pct)
                return

    engine = CertificationEngine(on_progress=on_progress)

    loop = asyncio.get_event_loop()
    report_dict = await loop.run_in_executor(
        None,
        engine.run,
        output_dir,
        test_run_report,
        diagnosis_report,
        agent_map,
    )

    session_manager.set_artifact(
        req.session_id, "certification-report",
        str(output_dir / "certification_report.json"),
    )

    return report_dict


@router.post("/run")
async def run_certification(req: CertificationRequest):
    session = session_manager.get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.phase_status.get("cert") == "running":
        raise HTTPException(status_code=409, detail="Certification already running")

    if "d" not in session.phases_completed and "c" not in session.phases_completed:
        raise HTTPException(status_code=400, detail="Phase C or D must be completed first")

    session_manager.set_phase_status(req.session_id, "cert", "running")
    emitter = ProgressEmitter(req.session_id, "cert")
    queue = ws_manager.get_queue(req.session_id)
    emitter.add_listener(queue)

    async def _run():
        try:
            result = await _run_certification_async(req, emitter)
            session_manager.set_phase_status(req.session_id, "cert", "completed")
            session_manager.set_phase_result(req.session_id, "cert", result)
            emitter.emit_complete(result)
        except Exception as e:
            session_manager.set_phase_status(req.session_id, "cert", "error")
            emitter.emit_error(f"{type(e).__name__}: {e}")
            traceback.print_exc()
        finally:
            emitter.remove_listener(queue)

    asyncio.create_task(_run())
    return {"status": "started", "session_id": req.session_id}


@router.get("/status/{session_id}", response_model=PhaseStatusResponse)
async def get_certification_status(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    prog = session.phase_progress.get("cert", {})
    return PhaseStatusResponse(
        session_id=session_id,
        phase="cert",
        status=session.phase_status.get("cert", "idle"),
        progress_pct=prog.get("pct", 0),
        message=prog.get("message", ""),
        result=session.phase_results.get("cert"),
    )
