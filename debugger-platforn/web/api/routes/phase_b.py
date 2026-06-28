"""Phase B: Generate Tests — API routes."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
import time
import traceback
from pathlib import Path

logger = logging.getLogger(__name__)

from fastapi import APIRouter, HTTPException

from web.api.config import PROJECT_ROOT
from web.api.models.requests import PhaseBRequest
from web.api.models.responses import PhaseStatusResponse
from web.api.services.progress_emitter import ProgressEmitter
from web.api.services.session_manager import session_manager
from web.api.ws import ws_manager

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

router = APIRouter(prefix="/api/phase-b", tags=["phase-b"])


def _run_phase_b_sync(req: PhaseBRequest, emitter: ProgressEmitter) -> dict:
    """Run Phase B synchronously (called in a thread)."""
    from generate_tests import _run_phase_b, PhaseBUsageTracker

    session = session_manager.get_session(req.session_id)
    output_dir = Path(session.output_dir) / "generated"

    # Load agent map from Phase A output
    agent_map_path = Path(session.output_dir) / "agent_map.json"
    if not agent_map_path.exists():
        raise ValueError("Agent map not found. Run Phase A first.")

    with open(agent_map_path) as f:
        agent_map = json.load(f)

    emitter.emit("loading_agent_map", "Loading Agent Map from Phase A...", 5)

    # Build LLM config from request (None = use default Anthropic)
    llm_config = None
    if req.llm_provider:
        from src.execution.llm_config import LLMProviderConfig
        llm_config = LLMProviderConfig(
            provider=req.llm_provider,
            model=req.llm_model,
            base_url=req.llm_base_url,
        )
        logger.info("Phase B LLM config: provider=%s model=%s", req.llm_provider, req.llm_model)
    else:
        logger.info("Phase B LLM config: default (Anthropic)")

    if llm_config and not llm_config.needs_api_key:
        has_api_key = True
    elif llm_config:
        has_api_key = bool(llm_config.resolved_api_key)
    else:
        has_api_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    logger.info("Phase B has_api_key=%s skip_ai=%s", has_api_key, req.skip_ai)
    usage_tracker = PhaseBUsageTracker(llm_config=llm_config) if not req.skip_ai and has_api_key else None

    emitter.emit("building_personas", "Generating personas...", 15)

    # Tick progress during the main generation to show activity
    _stop_ticker = threading.Event()

    def _progress_ticker():
        steps = [
            (1.5, "creating_scenarios", "Creating scenarios...", 35),
            (3.0, "generating_variants", "Generating test variants...", 50),
            (5.0, "assembling_suite", "Assembling test suite...", 65),
        ]
        for delay, step, msg, pct in steps:
            if _stop_ticker.wait(delay):
                return
            emitter.emit(step, msg, pct)

    ticker = threading.Thread(target=_progress_ticker, daemon=True)
    ticker.start()

    suite_path = _run_phase_b(
        agent_map=agent_map,
        output_dir=output_dir,
        skip_ai=req.skip_ai,
        count=req.count,
        persona_count=req.persona_count,
        scenario_count=req.scenario_count,
        variants=req.variants,
        seed=req.seed,
        language=req.language,
        use_tlahuac=req.use_tlahuac,
        tlahuac_dir=req.tlahuac_dir,
        usage_tracker=usage_tracker,
        include_templates=req.include_templates,
        llm_config=llm_config,
    )

    _stop_ticker.set()
    ticker.join(timeout=1)

    # Post-processing: read back artifacts with progress updates
    emitter.emit("saving_artifacts", "Saving generated artifacts...", 75)

    # Register artifacts
    session_manager.set_artifact(req.session_id, "test-suite", suite_path)
    for name in ["persona_library.json", "scenario_catalog.json", "test_configuration.json", "test_suite.json"]:
        path = output_dir / name
        if path.exists():
            key = name.replace(".json", "").replace("_", "-")
            session_manager.set_artifact(req.session_id, key, str(path))

    emitter.emit("loading_results", "Loading test suite results...", 85)

    # Build result summary
    result: dict = {"test_suite_path": suite_path}

    # Load test suite summary
    with open(suite_path) as f:
        suite = json.load(f)
    result["total_tests"] = suite.get("summary", {}).get("total_tests", len(suite.get("test_cases", [])))

    # Load persona library
    emitter.emit("loading_personas", "Loading persona library...", 90)
    persona_path = output_dir / "persona_library.json"
    if persona_path.exists():
        with open(persona_path) as f:
            lib = json.load(f)
        personas = lib.get("personas", [])
        result["persona_count"] = len(personas)
        result["personas"] = [
            {"name": p.get("name", ""), "agent_type": p.get("agent_type", ""), "source": p.get("source", "")}
            for p in personas[:20]
        ]

    # Load scenario catalog
    emitter.emit("loading_scenarios", "Loading scenario catalog...", 95)
    scenario_path = output_dir / "scenario_catalog.json"
    if scenario_path.exists():
        with open(scenario_path) as f:
            cat = json.load(f)
        scenarios = cat.get("scenarios", [])
        result["scenario_count"] = len(scenarios)
        result["scenarios"] = [
            {"title": s.get("title", ""), "difficulty": s.get("difficulty", ""), "required_tools": s.get("required_tools", [])}
            for s in scenarios[:20]
        ]

    # Token usage
    if usage_tracker and usage_tracker.total_tokens() > 0:
        result["tokens_used"] = usage_tracker.total_tokens()
        result["cost_usd"] = round(usage_tracker.cost_usd(), 4)

    return result


@router.post("/run")
async def run_phase_b(req: PhaseBRequest):
    session = session_manager.get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.phase_status.get("b") == "running":
        raise HTTPException(status_code=409, detail="Phase B already running")

    if "a" not in session.phases_completed:
        raise HTTPException(status_code=400, detail="Phase A must be completed first")

    session_manager.set_phase_status(req.session_id, "b", "running")
    emitter = ProgressEmitter(req.session_id, "b")
    queue = ws_manager.get_queue(req.session_id)
    emitter.add_listener(queue)

    async def _run():
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, _run_phase_b_sync, req, emitter)
            session_manager.set_phase_status(req.session_id, "b", "completed")
            session_manager.set_phase_result(req.session_id, "b", result)
            emitter.emit_complete(result)
        except Exception as e:
            session_manager.set_phase_status(req.session_id, "b", "error")
            emitter.emit_error(f"{type(e).__name__}: {e}")
            traceback.print_exc()
        finally:
            emitter.remove_listener(queue)

    asyncio.create_task(_run())
    return {"status": "started", "session_id": req.session_id}


@router.get("/status/{session_id}", response_model=PhaseStatusResponse)
async def get_phase_b_status(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    prog = session.phase_progress.get("b", {})
    return PhaseStatusResponse(
        session_id=session_id,
        phase="b",
        status=session.phase_status.get("b", "idle"),
        progress_pct=prog.get("pct", 0),
        message=prog.get("message", ""),
        result=session.phase_results.get("b"),
    )
