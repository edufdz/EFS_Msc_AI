"""Phase A: Analyze — API routes."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import traceback
from pathlib import Path

from fastapi import APIRouter, HTTPException

from web.api.config import PROJECT_ROOT
from web.api.models.requests import PhaseARequest
from web.api.models.responses import PhaseStatusResponse
from web.api.services.progress_emitter import ProgressEmitter
from web.api.services.session_manager import session_manager
from web.api.ws import ws_manager

# Ensure project root is on path so src.* imports work
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

router = APIRouter(prefix="/api/phase-a", tags=["phase-a"])


def _run_phase_a_sync(req: PhaseARequest, emitter: ProgressEmitter) -> dict:
    """Run Phase A analysis synchronously (called in a thread)."""
    from src.ingestion.ingestor import ingest_directory
    from src.analysis.static_analyzer import analyze_files
    from src.patterns.detector import detect_patterns
    from src.risk.analyzer import analyze_risks
    from src.graph.builder import generate_agent_map

    session = session_manager.get_session(req.session_id)
    output_dir = Path(session.output_dir)

    # Step 1: Ingest
    emitter.emit("scanning_codebase", "Scanning codebase...", 10)
    ingestion = ingest_directory(req.repo_path, language_filter=req.language)

    if not ingestion.files:
        raise ValueError("No relevant files found. Check path and language filter.")

    # Step 2: Static analysis
    emitter.emit("parsing_treesitter", "Parsing with Tree-sitter...", 25)
    file_paths = [f.path for f in ingestion.files]
    all_symbols = analyze_files(file_paths)

    # Step 3: Pattern detection
    emitter.emit("detecting_patterns", "Detecting agent patterns...", 45)
    pattern_result = detect_patterns(
        all_symbols, ingestion.prompt_files, prompt_encoding=req.prompt_encoding
    )

    # Step 4: Risk analysis
    emitter.emit("analyzing_risks", "Analyzing risks...", 60)
    risks = analyze_risks(pattern_result.tools, pattern_result.prompts)

    # Step 5: AI semantic analysis (optional)
    ai_result = None
    if not req.skip_ai:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if api_key:
            emitter.emit("ai_analysis", "Running AI semantic analysis...", 70)
            from src.ai_analyzer.analyzer import run_semantic_analysis
            ai_result = run_semantic_analysis(
                all_symbols=all_symbols,
                tools=pattern_result.tools,
                prompts=pattern_result.prompts,
                entry_points=ingestion.entry_points,
                framework=pattern_result.framework,
            )

    # Step 6: Build agent map
    emitter.emit("building_map", "Building Agent Map...", 90)
    agent_map = generate_agent_map(
        all_symbols=all_symbols,
        pattern_result=pattern_result,
        ai_result=ai_result,
        risks=risks,
        entry_points=ingestion.entry_points,
        root_path=ingestion.root_path,
    )

    # Save output
    output_path = output_dir / "agent_map.json"
    with open(output_path, "w") as f:
        json.dump(agent_map, f, indent=2, default=str)
    session_manager.set_artifact(req.session_id, "agent-map", str(output_path))

    # Try generating graph visualization
    graph_path = None
    try:
        from src.graph.visualizer import visualize_agent_map
        png_path, _mmd_path = visualize_agent_map(agent_map, str(output_dir))
        session_manager.set_artifact(req.session_id, "graph-png", str(png_path))
        graph_path = str(png_path)
    except Exception:
        pass

    # Build result summary
    result = {
        "framework": agent_map["metadata"].get("framework", "unknown"),
        "framework_confidence": pattern_result.framework_confidence,
        "tools_count": len(agent_map["components"]["tools"]),
        "prompts_count": len(agent_map["components"]["prompts"]),
        "risks_count": len(agent_map["risk_flags"]["all_risks"]),
        "files_scanned": len(ingestion.files),
        "language": agent_map["metadata"].get("conversation_language", "English"),
        "agent_map_path": str(output_path),
        "graph_path": graph_path,
        "tools": [
            {"name": t["name"], "description": t.get("description", ""), "risk_level": t.get("risk_level", "low")}
            for t in agent_map["components"]["tools"]
        ],
        "risks": [
            {"tool": r.get("tool", "-"), "risk_type": r.get("risk_type", ""), "severity": r.get("severity", ""), "description": r.get("description", "")}
            for r in agent_map["risk_flags"]["all_risks"]
        ],
    }
    return result


@router.post("/run")
async def run_phase_a(req: PhaseARequest):
    session = session_manager.get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.phase_status.get("a") == "running":
        raise HTTPException(status_code=409, detail="Phase A already running")

    session_manager.set_phase_status(req.session_id, "a", "running")
    emitter = ProgressEmitter(req.session_id, "a")

    # Register emitter with WS manager queue
    queue = ws_manager.get_queue(req.session_id)
    emitter.add_listener(queue)

    async def _run():
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, _run_phase_a_sync, req, emitter)
            session_manager.set_phase_status(req.session_id, "a", "completed")
            session_manager.set_phase_result(req.session_id, "a", result)
            emitter.emit_complete(result)
        except Exception as e:
            session_manager.set_phase_status(req.session_id, "a", "error")
            emitter.emit_error(f"{type(e).__name__}: {e}")
            traceback.print_exc()
        finally:
            emitter.remove_listener(queue)

    asyncio.create_task(_run())
    return {"status": "started", "session_id": req.session_id}


@router.get("/status/{session_id}", response_model=PhaseStatusResponse)
async def get_phase_a_status(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    prog = session.phase_progress.get("a", {})
    return PhaseStatusResponse(
        session_id=session_id,
        phase="a",
        status=session.phase_status.get("a", "idle"),
        progress_pct=prog.get("pct", 0),
        message=prog.get("message", ""),
        result=session.phase_results.get("a"),
    )
