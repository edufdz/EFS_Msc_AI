"""WebSocket manager and endpoint for streaming progress events."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect


class ConnectionManager:
    """Manages WebSocket connections per session."""

    def __init__(self):
        # session_id -> set of WebSocket connections
        self._connections: dict[str, set[WebSocket]] = {}
        # session_id -> asyncio.Queue for events
        self._queues: dict[str, asyncio.Queue] = {}

    async def connect(self, websocket: WebSocket, session_id: str) -> None:
        await websocket.accept()
        if session_id not in self._connections:
            self._connections[session_id] = set()
        self._connections[session_id].add(websocket)

    def disconnect(self, websocket: WebSocket, session_id: str) -> None:
        conns = self._connections.get(session_id)
        if conns:
            conns.discard(websocket)
            if not conns:
                del self._connections[session_id]

    async def broadcast(self, session_id: str, event: dict[str, Any]) -> None:
        """Broadcast an event to all clients connected to a session."""
        conns = self._connections.get(session_id, set())
        msg = json.dumps(event, default=str)
        disconnected = set()
        for ws in conns:
            try:
                await ws.send_text(msg)
            except Exception:
                disconnected.add(ws)
        for ws in disconnected:
            conns.discard(ws)

    def get_queue(self, session_id: str) -> asyncio.Queue:
        """Get or create an event queue for a session."""
        if session_id not in self._queues:
            self._queues[session_id] = asyncio.Queue()
        return self._queues[session_id]

    def remove_queue(self, session_id: str) -> None:
        self._queues.pop(session_id, None)


# Global singleton
ws_manager = ConnectionManager()


async def ws_endpoint(websocket: WebSocket, session_id: str) -> None:
    """WebSocket endpoint handler — connect client and stream events."""
    await ws_manager.connect(websocket, session_id)
    try:
        while True:
            # Keep alive; also handle client messages if needed
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except asyncio.TimeoutError:
                # Send keepalive ping
                await websocket.send_text(json.dumps({"type": "ping"}))
            except (json.JSONDecodeError, TypeError):
                pass
    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(websocket, session_id)
