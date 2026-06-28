"""Artifact retrieval routes."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from web.api.services.session_manager import session_manager

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])

# Maps artifact type to possible file names within the session output dir
ARTIFACT_FILES = {
    "agent-map": "agent_map.json",
    "test-suite": "test_suite.json",
    "test-report": "test_run_report.json",
    "failure-inbox": "failure_inbox.json",
    "persona-library": "persona_library.json",
    "scenario-catalog": "scenario_catalog.json",
    "conversation-log": "conversations.log",
    "test-configuration": "test_configuration.json",
    "graph-png": "agent_map_graph.png",
    "certification-report": "certification_report.json",
}


@router.get("/{session_id}/{artifact_type}")
async def get_artifact(session_id: str, artifact_type: str):
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Check session artifacts map first
    if artifact_type in session.artifacts:
        file_path = Path(session.artifacts[artifact_type])
        if file_path.exists():
            if file_path.suffix == ".png":
                return FileResponse(str(file_path), media_type="image/png")
            if file_path.suffix == ".log":
                return FileResponse(str(file_path), media_type="text/plain")
            with open(file_path) as f:
                return JSONResponse(json.load(f))

    # Fall back to standard file names
    filename = ARTIFACT_FILES.get(artifact_type)
    if not filename:
        raise HTTPException(status_code=400, detail=f"Unknown artifact type: {artifact_type}")

    # Search in output dir and subdirectories
    output_dir = Path(session.output_dir)
    candidates = [
        output_dir / filename,
        output_dir / "results" / filename,
        output_dir / "generated" / filename,
    ]

    for candidate in candidates:
        if candidate.exists():
            if candidate.suffix == ".png":
                return FileResponse(str(candidate), media_type="image/png")
            if candidate.suffix == ".log":
                return FileResponse(str(candidate), media_type="text/plain")
            with open(candidate) as f:
                return JSONResponse(json.load(f))

    raise HTTPException(status_code=404, detail=f"Artifact '{artifact_type}' not found")
