"""Session management routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from web.api.models.responses import SessionListResponse, SessionResponse
from web.api.services.session_manager import session_manager

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _session_response(session, include_results: bool = False) -> SessionResponse:
    return SessionResponse(
        session_id=session.session_id,
        output_dir=session.output_dir,
        created_at=session.created_at,
        phases_completed=session.phases_completed,
        phase_status=session.phase_status,
        phase_results=session.phase_results if include_results else None,
    )


@router.post("", response_model=SessionResponse)
async def create_session():
    session = session_manager.create_session()
    return _session_response(session)


@router.get("", response_model=SessionListResponse)
async def list_sessions():
    sessions = session_manager.list_sessions()
    return SessionListResponse(
        sessions=[_session_response(s) for s in sessions]
    )


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return _session_response(session, include_results=True)


@router.post("/{session_id}/save")
async def save_session(session_id: str):
    """Explicitly save a session's state to disk."""
    if not session_manager.save_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"saved": True, "session_id": session_id}


@router.post("/{session_id}/reset-phase/{phase}")
async def reset_phase(session_id: str, phase: str):
    """Reset a phase and all downstream phases so it can be re-run.

    E.g. resetting 'c' also resets 'd', but keeps 'a' and 'b' intact.
    """
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if phase not in ("a", "b", "c", "d", "cert"):
        raise HTTPException(status_code=400, detail="Invalid phase")

    # Don't allow reset if the phase is currently running
    if session.phase_status.get(phase) == "running":
        raise HTTPException(status_code=409, detail=f"Phase {phase} is currently running")

    reset_phases = session_manager.reset_phase(session_id, phase)
    return {"reset_phases": reset_phases, "session_id": session_id}
