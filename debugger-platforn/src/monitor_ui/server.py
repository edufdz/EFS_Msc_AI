"""
MonitorUIServer — WebSocket + HTTP server for the Phase C live dashboard.

Two usage modes:
  1. Integrated: started from execute_tests.py with --ui flag,
     subscribes directly to engine.event_queue.
  2. Standalone: tails conversations.log + watches for report files,
     translating log lines into WebSocket events.

Dependencies: websockets (pip install websockets)
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

try:
    import websockets
    from websockets.server import serve as ws_serve
except ImportError:
    raise ImportError(
        "websockets is required for the monitor UI. Install with: pip install websockets"
    )


class MonitorUIServer:
    """Broadcasts engine events to browser clients over WebSocket."""

    def __init__(
        self,
        port: int = 8080,
        host: str = "0.0.0.0",
        log_file: Optional[str] = None,
        report_file: Optional[str] = None,
        results_dir: Optional[str] = None,
    ):
        self.port = port
        self.host = host
        self.log_file = log_file
        self.report_file = report_file
        self.results_dir = results_dir

        # Connected WebSocket clients
        self._clients: Set[websockets.WebSocketServerProtocol] = set()

        # In-memory state snapshot (for reconnection)
        self._state: Dict[str, Any] = {
            "run_id": None,
            "total_tests": 0,
            "agent_name": "",
            "tools": [],
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "timeouts": 0,
            "completed": 0,
            "total_cost_usd": 0.0,
            "total_duration_sec": 0.0,
            "tools_called": set(),
            "active_tests": {},   # test_id -> test state dict
            "event_log": [],      # last 200 events for the feed
            "failures": [],       # failure inbox entries
            "started_at": None,
            "run_completed": False,
            "validation": None,
        }

        # Internal event queue (fed by engine or log tailer)
        self._event_queue: asyncio.Queue = asyncio.Queue()

        # Dashboard HTML path
        self._dashboard_path = Path(__file__).parent / "dashboard.html"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start_integrated(
        self,
        engine_queue: asyncio.Queue,
        agent_name: str = "",
        tools: Optional[List[str]] = None,
    ) -> None:
        """Start server in integrated mode, forwarding from engine_queue."""
        self._state["agent_name"] = agent_name
        self._state["tools"] = tools or []

        # Start all tasks
        await asyncio.gather(
            self._run_websocket_server(),
            self._forward_engine_events(engine_queue),
            self._process_events(),
        )

    async def start_standalone(self) -> None:
        """Start server in standalone mode, tailing a log file."""
        if not self.log_file:
            raise ValueError("log_file is required for standalone mode")

        await asyncio.gather(
            self._run_websocket_server(),
            self._tail_log_file(),
            self._process_events(),
        )

    async def push_event(self, event: Dict[str, Any]) -> None:
        """Push an external event into the server (e.g. validation results)."""
        await self._event_queue.put(event)

    # ------------------------------------------------------------------
    # WebSocket server
    # ------------------------------------------------------------------

    async def _run_websocket_server(self) -> None:
        """Serve WebSocket connections and HTTP requests."""
        async def handler(websocket, path=None):
            # Handle HTTP-like paths for REST endpoints
            request_path = getattr(websocket, 'path', path) or "/"

            if request_path == "/api/state":
                await self._handle_state_request(websocket)
                return
            if request_path == "/api/report":
                await self._handle_report_request(websocket)
                return
            if request_path == "/dashboard" or request_path == "/":
                # Serve dashboard HTML over WebSocket upgrade path
                # (actual HTTP serving handled by process_request)
                pass

            # WebSocket connection
            self._clients.add(websocket)
            try:
                # Send current state snapshot on connect
                await self._send_state_snapshot(websocket)
                # Keep connection alive, handle incoming messages
                async for message in websocket:
                    # Client can request state refresh
                    try:
                        msg = json.loads(message)
                        if msg.get("type") == "request_state":
                            await self._send_state_snapshot(websocket)
                    except (json.JSONDecodeError, TypeError):
                        pass
            except websockets.exceptions.ConnectionClosed:
                pass
            finally:
                self._clients.discard(websocket)

        async def process_request(path, request_headers):
            """Handle HTTP requests (serve dashboard.html and REST API)."""
            if path == "/" or path == "/dashboard":
                if self._dashboard_path.exists():
                    body = self._dashboard_path.read_bytes()
                    return (
                        200,
                        [("Content-Type", "text/html; charset=utf-8")],
                        body,
                    )
                return (404, [], b"dashboard.html not found")

            if path == "/api/state":
                body = json.dumps(self._get_state_snapshot()).encode()
                return (
                    200,
                    [
                        ("Content-Type", "application/json"),
                        ("Access-Control-Allow-Origin", "*"),
                    ],
                    body,
                )

            if path == "/api/report":
                report = self._load_report()
                body = json.dumps(report).encode()
                return (
                    200,
                    [
                        ("Content-Type", "application/json"),
                        ("Access-Control-Allow-Origin", "*"),
                    ],
                    body,
                )

            # Let WebSocket handler take over for /ws path
            if path == "/ws":
                return None

            # Default: serve dashboard for any other path
            return None

        server = await ws_serve(
            handler,
            self.host,
            self.port,
            process_request=process_request,
            ping_interval=20,
            ping_timeout=20,
        )

        await server.wait_closed()

    async def _handle_state_request(self, websocket) -> None:
        """Send state snapshot over WebSocket."""
        await websocket.send(json.dumps({
            "type": "state_snapshot",
            **self._get_state_snapshot(),
        }))

    async def _handle_report_request(self, websocket) -> None:
        """Send report over WebSocket."""
        report = self._load_report()
        await websocket.send(json.dumps({
            "type": "report",
            "data": report,
        }))

    # ------------------------------------------------------------------
    # Event forwarding
    # ------------------------------------------------------------------

    async def _forward_engine_events(self, engine_queue: asyncio.Queue) -> None:
        """Forward events from the engine queue to our internal queue."""
        while True:
            try:
                event = await asyncio.wait_for(engine_queue.get(), timeout=0.2)
                await self._event_queue.put(event)
                if event.get("type") == "run_completed":
                    # Give time for final processing then stop
                    await asyncio.sleep(1)
                    return
            except asyncio.TimeoutError:
                continue

    async def _tail_log_file(self) -> None:
        """Tail conversations.log and translate lines into events."""
        log_path = Path(self.log_file)

        # Wait for file to exist
        while not log_path.exists():
            await asyncio.sleep(0.5)

        last_pos = 0
        while True:
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    f.seek(last_pos)
                    new_lines = f.readlines()
                    last_pos = f.tell()

                for line in new_lines:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        event = self._translate_log_entry(entry)
                        if event:
                            await self._event_queue.put(event)
                    except json.JSONDecodeError:
                        continue

            except (OSError, IOError):
                pass

            await asyncio.sleep(0.2)

    def _translate_log_entry(self, entry: Dict) -> Optional[Dict]:
        """Translate a conversations.log JSON-line into a WebSocket event."""
        entry_type = entry.get("type")

        if entry_type == "conversation_start":
            return {
                "type": "test_started",
                "test_id": f"TC-{entry.get('test_number', 0):03d}",
                "test_number": entry.get("test_number", 0),
                "scenario": entry.get("scenario", ""),
                "persona": entry.get("persona", ""),
                "difficulty": "medium",
                "coverage_goal": "",
            }

        if entry_type == "turn":
            tool_calls = entry.get("tool_calls", [])
            # Emit tool_called events for each tool call
            events = []
            events.append({
                "type": "turn_completed",
                "test_id": f"TC-{entry.get('test_number', 0):03d}",
                "turn": entry.get("turn", 0),
                "role": entry.get("role", ""),
                "message": entry.get("message", ""),
                "tool_calls": tool_calls,
                "duration_ms": entry.get("duration_ms", 0),
            })
            for tc in tool_calls:
                if isinstance(tc, dict):
                    result = tc.get("result", {})
                    status = "success"
                    if isinstance(result, dict) and result.get("status") != "ok":
                        status = "error"
                    events.append({
                        "type": "tool_called",
                        "test_id": f"TC-{entry.get('test_number', 0):03d}",
                        "tool_name": tc.get("tool_name", "unknown"),
                        "status": status,
                        "input": tc.get("arguments", {}),
                        "output": result,
                    })
            # Return first event; queue the rest
            if len(events) > 1:
                for e in events[1:]:
                    asyncio.get_event_loop().call_soon(
                        lambda ev=e: self._event_queue.put_nowait(ev)
                    )
            return events[0] if events else None

        return None

    # ------------------------------------------------------------------
    # Event processing + state management
    # ------------------------------------------------------------------

    async def _process_events(self) -> None:
        """Process internal events: update state, broadcast to clients."""
        check_counter = 0
        while True:
            try:
                event = await asyncio.wait_for(self._event_queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                # Periodically check for validation report on disk
                check_counter += 1
                if check_counter % 10 == 0:  # Every ~5 seconds
                    self._check_validation_report()
                continue

            self._update_state(event)

            # Enrich event with computed fields
            enriched = self._enrich_event(event)

            # Broadcast to all connected clients
            await self._broadcast(enriched)

            if event.get("type") == "run_completed":
                # Send final enriched run_completed
                await asyncio.sleep(0.5)
                return

    def _update_state(self, event: Dict) -> None:
        """Update in-memory state from an event."""
        etype = event.get("type")
        s = self._state

        if etype == "run_started":
            s["run_id"] = event.get("run_id", f"run-{int(time.time())}")
            s["total_tests"] = event.get("total_tests", 0)
            s["agent_name"] = event.get("agent_name", s["agent_name"])
            if event.get("tools"):
                s["tools"] = event["tools"]
            s["started_at"] = event.get("timestamp", datetime.now(timezone.utc).isoformat())

        elif etype == "test_started":
            test_id = event.get("test_id", "")
            s["active_tests"][test_id] = {
                "test_id": test_id,
                "test_number": event.get("test_number", 0),
                "scenario": event.get("scenario", ""),
                "persona": event.get("persona", ""),
                "difficulty": event.get("difficulty", "medium"),
                "coverage_goal": event.get("coverage_goal", ""),
                "status": "running",
                "turns": [],
                "tool_calls": [],
                "started_at": time.time(),
            }

        elif etype == "turn_completed":
            test_id = event.get("test_id", "")
            test = s["active_tests"].get(test_id)
            if test:
                test["turns"].append({
                    "turn": event.get("turn", 0),
                    "role": event.get("role", ""),
                    "message": event.get("message", ""),
                    "duration_ms": event.get("duration_ms", 0),
                    "timestamp": time.time(),
                })

        elif etype == "tool_called":
            test_id = event.get("test_id", "")
            tool_name = event.get("tool_name", "")
            test = s["active_tests"].get(test_id)
            if test:
                tc_entry = {
                    "tool_name": tool_name,
                    "status": event.get("status", "success"),
                }
                if event.get("input"):
                    tc_entry["input"] = event["input"]
                if event.get("output"):
                    tc_entry["output"] = event["output"]
                test["tool_calls"].append(tc_entry)
            s["tools_called"].add(tool_name)

        elif etype == "chaos_injected":
            test_id = event.get("test_id", "")
            test = s["active_tests"].get(test_id)
            if test:
                test["tool_calls"].append({
                    "tool_name": f"[chaos:{event.get('chaos_type', '')}]",
                    "status": "chaos",
                })

        elif etype == "test_completed":
            test_id = event.get("test_id", "")
            status = event.get("status", "failed")
            s["completed"] += 1
            s["total_cost_usd"] += event.get("cost_usd", 0)
            s["total_duration_sec"] += event.get("duration_sec", 0)

            if status == "passed":
                s["passed"] += 1
            elif status == "failed":
                s["failed"] += 1
            elif status == "error":
                s["errors"] += 1
            elif status == "timeout":
                s["timeouts"] += 1

            # Track tools called
            for t in event.get("tools_called", []):
                s["tools_called"].add(t)

            # Update active test state
            test = s["active_tests"].get(test_id)
            if test:
                test["status"] = status
                test["failure_reason"] = event.get("failure_reason")
                test["tools_called_list"] = event.get("tools_called", [])

            # Add to failure inbox if not passed
            if status != "passed":
                s["failures"].append({
                    "test_id": test_id,
                    "test_number": event.get("test_number", 0),
                    "scenario": event.get("scenario", ""),
                    "persona": event.get("persona", ""),
                    "status": status,
                    "failure_reason": event.get("failure_reason", ""),
                    "tools_called": event.get("tools_called", []),
                    "turns": test["turns"] if test else [],
                    "tool_calls": test["tool_calls"] if test else [],
                })

        elif etype == "validation_completed":
            s["validation"] = event.get("summary", {})

        elif etype == "run_completed":
            s["run_completed"] = True

        # Add to event log (keep last 200)
        log_entry = self._make_log_entry(event)
        if log_entry:
            s["event_log"].append(log_entry)
            if len(s["event_log"]) > 200:
                s["event_log"] = s["event_log"][-200:]

    def _make_log_entry(self, event: Dict) -> Optional[Dict]:
        """Create a compact event feed entry."""
        etype = event.get("type")
        ts = time.time()

        if etype == "run_started":
            return {"ts": ts, "icon": "rocket", "text": f"Run started \u2014 {event.get('total_tests', 0)} tests", "color": "blue"}
        if etype == "test_started":
            return {"ts": ts, "icon": "rocket", "text": f"{event.get('test_id', '')[:10]} started: {event.get('scenario', '')[:40]}", "color": "blue"}
        if etype == "turn_completed":
            role = event.get("role", "")
            return {"ts": ts, "icon": "chat", "text": f"{event.get('test_id', '')[:10]} turn {event.get('turn', 0)} ({role})", "color": "dim"}
        if etype == "tool_called":
            status = event.get("status", "success")
            color = "green" if status == "success" else "red" if status == "error" else "orange"
            return {"ts": ts, "icon": "tool", "text": f"{event.get('test_id', '')[:10]}: {event.get('tool_name', '')} \u2192 {status}", "color": color}
        if etype == "chaos_injected":
            return {"ts": ts, "icon": "chaos", "text": f"{event.get('test_id', '')[:10]}: chaos {event.get('chaos_type', '')}", "color": "orange"}
        if etype == "test_completed":
            status = event.get("status", "")
            color = "green" if status == "passed" else "red"
            reason = f" \u2014 {event.get('failure_reason', '')[:40]}" if status != "passed" else ""
            return {"ts": ts, "icon": "pass" if status == "passed" else "fail", "text": f"{event.get('test_id', '')[:10]} {status}{reason}", "color": color}
        if etype == "validation_completed":
            s = event.get("summary", {})
            genuine = s.get("genuine_failures", 0)
            filtered = s.get("persona_incompetence_filtered", 0) + s.get("chaos_induced_filtered", 0)
            false_suc = s.get("false_successes_caught", 0)
            return {"ts": ts, "icon": "finish", "text": f"Validation: {genuine} genuine, {filtered} filtered, {false_suc} false successes", "color": "blue"}
        if etype == "run_completed":
            return {"ts": ts, "icon": "finish", "text": "Run completed", "color": "green"}

        return None

    def _enrich_event(self, event: Dict) -> Dict:
        """Add computed fields to an event before broadcasting."""
        enriched = dict(event)
        s = self._state

        if event.get("type") == "test_completed":
            # Add running totals
            enriched["_totals"] = {
                "passed": s["passed"],
                "failed": s["failed"],
                "errors": s["errors"],
                "timeouts": s["timeouts"],
                "completed": s["completed"],
                "total_tests": s["total_tests"],
                "total_cost_usd": round(s["total_cost_usd"], 4),
                "pass_rate": round(s["passed"] / s["completed"] * 100, 1) if s["completed"] else 0,
                "tools_covered": len(s["tools_called"]),
                "tools_total": len(s["tools"]),
            }

        if event.get("type") == "run_completed":
            enriched["passed"] = s["passed"]
            enriched["failed"] = s["failed"]
            enriched["errors"] = s["errors"]
            enriched["timeouts"] = s["timeouts"]
            enriched["pass_rate"] = round(s["passed"] / s["completed"] * 100, 1) if s["completed"] else 0
            enriched["total_cost_usd"] = round(s["total_cost_usd"], 4)
            duration = time.time() - (self._parse_ts(s["started_at"]) or time.time())
            enriched["duration_s"] = round(duration, 1)

        return enriched

    def _parse_ts(self, ts_str) -> Optional[float]:
        if ts_str is None:
            return None
        if isinstance(ts_str, (int, float)):
            return ts_str
        try:
            dt = datetime.fromisoformat(str(ts_str))
            return dt.timestamp()
        except (ValueError, TypeError):
            return None

    def _get_state_snapshot(self) -> Dict:
        """Return a JSON-serializable state snapshot for reconnecting clients."""
        s = self._state
        return {
            "run_id": s["run_id"],
            "total_tests": s["total_tests"],
            "agent_name": s["agent_name"],
            "tools": s["tools"],
            "passed": s["passed"],
            "failed": s["failed"],
            "errors": s["errors"],
            "timeouts": s["timeouts"],
            "completed": s["completed"],
            "total_cost_usd": round(s["total_cost_usd"], 4),
            "total_duration_sec": round(s["total_duration_sec"], 2),
            "tools_called": list(s["tools_called"]),
            "active_tests": s["active_tests"],
            "event_log": s["event_log"][-200:],
            "failures": s["failures"],
            "started_at": s["started_at"],
            "run_completed": s["run_completed"],
            "validation": s["validation"],
            "pass_rate": round(s["passed"] / s["completed"] * 100, 1) if s["completed"] else 0,
        }

    def _load_report(self) -> Dict:
        """Load the latest test_run_report.json."""
        if self.report_file and Path(self.report_file).exists():
            with open(self.report_file, "r") as f:
                return json.load(f)
        return {"error": "Report not available yet"}

    def _check_validation_report(self) -> None:
        """Check for validation_report.json and update state if found."""
        if self._state["validation"]:
            return  # Already loaded
        search_dirs = []
        if self.results_dir:
            search_dirs.append(Path(self.results_dir))
        if self.report_file:
            search_dirs.append(Path(self.report_file).parent)
        for d in search_dirs:
            vpath = d / "validation_report.json"
            if vpath.exists():
                try:
                    with open(vpath, "r") as f:
                        data = json.load(f)
                    summary = data.get("summary", {})
                    self._state["validation"] = summary
                    # Push event to clients
                    event = {"type": "validation_completed", "summary": summary}
                    self._update_state(event)
                    asyncio.get_event_loop().call_soon(
                        lambda ev=event: asyncio.ensure_future(self._broadcast(ev))
                    )
                except (json.JSONDecodeError, OSError):
                    pass
                return

    async def _broadcast(self, event: Dict) -> None:
        """Send event to all connected WebSocket clients."""
        if not self._clients:
            return
        # Ensure JSON-serializable
        msg = json.dumps(event, default=str)
        disconnected = set()
        for client in self._clients:
            try:
                await client.send(msg)
            except websockets.exceptions.ConnectionClosed:
                disconnected.add(client)
        self._clients -= disconnected

    async def _send_state_snapshot(self, websocket) -> None:
        """Send full state snapshot to a single client."""
        snapshot = self._get_state_snapshot()
        await websocket.send(json.dumps({
            "type": "state_snapshot",
            **snapshot,
        }, default=str))


# ------------------------------------------------------------------
# Standalone entry point
# ------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Phase C Live Monitor Server")
    parser.add_argument("--log", required=True, help="Path to conversations.log")
    parser.add_argument("--port", type=int, default=8080, help="Server port (default: 8080)")
    parser.add_argument("--host", default="0.0.0.0", help="Server host (default: 0.0.0.0)")
    parser.add_argument("--report", default=None, help="Path to test_run_report.json")
    args = parser.parse_args()

    server = MonitorUIServer(
        port=args.port,
        host=args.host,
        log_file=args.log,
        report_file=args.report,
    )

    print(f"Dashboard running at http://localhost:{args.port}")
    print(f"Tailing log file: {args.log}")
    asyncio.run(server.start_standalone())


if __name__ == "__main__":
    main()
