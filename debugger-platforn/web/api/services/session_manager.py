"""Session state tracking for pipeline runs."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from web.api.config import OUTPUT_BASE_DIR

logger = logging.getLogger(__name__)

STATE_FILENAME = "session_state.json"


class Session:
    """Tracks the state of a single debugging session."""

    def __init__(self, session_id: str | None = None, created_at: str | None = None):
        self.session_id = session_id or f"session-{uuid.uuid4().hex[:8]}"
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()
        self.output_dir = str(OUTPUT_BASE_DIR / self.session_id)
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        self.phases_completed: list[str] = []
        self.phase_status: dict[str, str] = {"a": "idle", "b": "idle", "c": "idle", "d": "idle", "cert": "idle"}
        self.phase_results: dict[str, Any] = {}
        self.phase_progress: dict[str, dict[str, Any]] = {}  # phase -> {step, message, pct}
        self.artifacts: dict[str, str] = {}  # type -> file path

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "output_dir": self.output_dir,
            "created_at": self.created_at,
            "phases_completed": self.phases_completed,
            "phase_status": self.phase_status,
            "phase_results": self.phase_results,
            "artifacts": self.artifacts,
        }

    def save_to_disk(self) -> None:
        """Persist session state to session_state.json in the output directory."""
        state_path = Path(self.output_dir) / STATE_FILENAME
        try:
            state_path.write_text(json.dumps(self.to_dict(), indent=2, default=str))
        except Exception as e:
            logger.warning("Failed to save session state for %s: %s", self.session_id, e)

    @classmethod
    def from_disk(cls, state_path: Path) -> Session | None:
        """Load a session from a session_state.json file."""
        try:
            data = json.loads(state_path.read_text())
            session = cls(
                session_id=data["session_id"],
                created_at=data.get("created_at", ""),
            )
            session.phases_completed = data.get("phases_completed", [])
            session.phase_status = data.get("phase_status", session.phase_status)
            session.phase_results = data.get("phase_results", {})
            session.artifacts = data.get("artifacts", {})
            return session
        except Exception as e:
            logger.warning("Failed to load session from %s: %s", state_path, e)
            return None


class SessionManager:
    """Session store with automatic disk persistence."""

    def __init__(self):
        self._sessions: dict[str, Session] = {}
        self._recover_sessions()

    def _recover_sessions(self) -> None:
        """Scan pipeline_output for saved sessions and restore them."""
        if not OUTPUT_BASE_DIR.exists():
            return
        for session_dir in OUTPUT_BASE_DIR.iterdir():
            if not session_dir.is_dir() or not session_dir.name.startswith("session-"):
                continue
            state_file = session_dir / STATE_FILENAME
            if state_file.exists():
                session = Session.from_disk(state_file)
                if session and session.session_id not in self._sessions:
                    self._sessions[session.session_id] = session
                    logger.info("Recovered session %s", session.session_id)

    def create_session(self) -> Session:
        session = Session()
        self._sessions[session.session_id] = session
        session.save_to_disk()
        return session

    def get_session(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def list_sessions(self) -> list[Session]:
        return sorted(self._sessions.values(), key=lambda s: s.created_at, reverse=True)

    def save_session(self, session_id: str) -> bool:
        """Explicitly save a session to disk."""
        session = self._sessions.get(session_id)
        if session:
            session.save_to_disk()
            return True
        return False

    def set_phase_status(self, session_id: str, phase: str, status: str) -> None:
        session = self._sessions.get(session_id)
        if session:
            session.phase_status[phase] = status
            if status == "completed" and phase not in session.phases_completed:
                session.phases_completed.append(phase)
            if status in ("completed", "error"):
                session.save_to_disk()

    def set_phase_result(self, session_id: str, phase: str, result: dict) -> None:
        session = self._sessions.get(session_id)
        if session:
            session.phase_results[phase] = result
            session.save_to_disk()

    def set_phase_progress(self, session_id: str, phase: str, step: str, message: str, pct: int) -> None:
        session = self._sessions.get(session_id)
        if session:
            session.phase_progress[phase] = {"step": step, "message": message, "pct": pct}

    def set_artifact(self, session_id: str, artifact_type: str, path: str) -> None:
        session = self._sessions.get(session_id)
        if session:
            session.artifacts[artifact_type] = path
            session.save_to_disk()

    def reset_phase(self, session_id: str, phase: str) -> list[str]:
        """Reset a phase and all downstream phases.

        Returns the list of phases that were reset.
        E.g. reset_phase("c") resets c and d.
        """
        PIPELINE = ["a", "b", "c", "d", "cert"]
        session = self._sessions.get(session_id)
        if not session or phase not in PIPELINE:
            return []

        idx = PIPELINE.index(phase)
        to_reset = PIPELINE[idx:]

        for p in to_reset:
            session.phase_status[p] = "idle"
            session.phase_results.pop(p, None)
            session.phase_progress.pop(p, None)
            if p in session.phases_completed:
                session.phases_completed.remove(p)

        session.save_to_disk()
        return to_reset


# Global singleton
session_manager = SessionManager()
