"""Progress emitter — replaces Rich console status with WebSocket events."""

from __future__ import annotations

import time
from typing import Any


class ProgressEmitter:
    """Emit phase progress events to be forwarded via WebSocket."""

    def __init__(self, session_id: str, phase: str):
        self.session_id = session_id
        self.phase = phase
        self._events: list[dict[str, Any]] = []
        self._listeners: list = []  # List of asyncio.Queue

    def add_listener(self, queue) -> None:
        self._listeners.append(queue)

    def remove_listener(self, queue) -> None:
        if queue in self._listeners:
            self._listeners.remove(queue)

    def emit(self, step: str, message: str, progress_pct: int = 0) -> None:
        from web.api.services.session_manager import session_manager
        session_manager.set_phase_progress(self.session_id, self.phase, step, message, progress_pct)

        event = {
            "type": "phase_progress",
            "phase": self.phase,
            "session_id": self.session_id,
            "step": step,
            "message": message,
            "progress_pct": progress_pct,
            "timestamp": time.time(),
        }
        self._events.append(event)
        for q in self._listeners:
            try:
                q.put_nowait(event)
            except Exception:
                pass

    def emit_complete(self, result: dict | None = None) -> None:
        event = {
            "type": "phase_complete",
            "phase": self.phase,
            "session_id": self.session_id,
            "result": result,
            "timestamp": time.time(),
        }
        self._events.append(event)
        for q in self._listeners:
            try:
                q.put_nowait(event)
            except Exception:
                pass

    def emit_error(self, error: str) -> None:
        event = {
            "type": "phase_error",
            "phase": self.phase,
            "session_id": self.session_id,
            "error": error,
            "timestamp": time.time(),
        }
        self._events.append(event)
        for q in self._listeners:
            try:
                q.put_nowait(event)
            except Exception:
                pass
