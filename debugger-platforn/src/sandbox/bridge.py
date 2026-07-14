"""
Sandbox Bridge: FastAPI app that wraps an agent behind a TEST endpoint.

Research purpose: Phase C drives agents through ``APIAgentConnector``, which
POSTs ``{"message", "session_id"}`` to ``{endpoint}/chat`` and expects
``{"response": str, "tool_calls": list}``. This bridge exposes exactly that
contract while (a) routing every tool call through a `MockToolRegistry`
with deterministic failure injection, (b) never touching live customers or
production tools, and (c) capturing every conversation as a `SandboxTrace`
(shared schema) written to a JSONL file for offline analysis and replay.

Upstream modes:
    - "echo":     fully offline stand-in agent (keyword-routed mock tools) so
                  the whole Phase C loop runs in CI without any network.
    - "http":     forwards messages to the wrapped real agent's endpoint.
                  v1 LIMITATION: the bridge does not intercept the upstream
                  agent's tool *execution* mid-flight; it forwards the
                  message, passes through the upstream response/tool_calls,
                  and overlays mock results (with failure injection) for any
                  returned tool call whose name is registered. True
                  execution interception requires the upstream to delegate
                  tool calls to the bridge (planned v2).
    - "callable": routes to an in-process callable (tests / embedding).
"""

from __future__ import annotations

import inspect
import json
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.sandbox.mock_tools import MockToolRegistry
from src.sandbox.models import (
    BRIDGE_VERSION,
    SandboxBridgeConfig,
    SandboxTrace,
    TraceToolCall,
    TraceTurn,
)


# ──────────────────────────────────────────────────────────────────
# Request / response models (Phase C connector contract)
# ──────────────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ResetRequest(BaseModel):
    session_id: Optional[str] = None


# ──────────────────────────────────────────────────────────────────
# Trace store (shared schema, JSONL persistence)
# ──────────────────────────────────────────────────────────────────


class TraceStore:
    """Holds per-session traces and persists them as JSONL.

    One JSON line per session. The file is rewritten atomically on each
    flush so a session's line is *updated* as its conversation grows —
    a crash mid-run therefore still leaves a valid, near-complete JSONL.
    """

    def __init__(self, trace_dir: Optional[str]):
        self.trace_dir = Path(trace_dir) if trace_dir else None
        self.traces: Dict[str, SandboxTrace] = {}
        self.last_active: Dict[str, float] = {}
        if self.trace_dir:
            self.trace_dir.mkdir(parents=True, exist_ok=True)

    @property
    def trace_path(self) -> Optional[Path]:
        if not self.trace_dir:
            return None
        return self.trace_dir / "sandbox_traces.jsonl"

    def get_or_create(self, session_id: str, metadata: Dict[str, Any]) -> SandboxTrace:
        trace = self.traces.get(session_id)
        if trace is None:
            trace = SandboxTrace(
                trace_id=f"trace-{uuid.uuid4().hex[:12]}",
                session_id=session_id,
                metadata=dict(metadata),
            )
            self.traces[session_id] = trace
        self.last_active[session_id] = time.monotonic()
        return trace

    def evict_expired(self, ttl_sec: int) -> None:
        """Flush and drop sessions idle for longer than the TTL."""
        now = time.monotonic()
        expired = [
            sid for sid, ts in self.last_active.items() if now - ts > ttl_sec
        ]
        for sid in expired:
            trace = self.traces.get(sid)
            if trace and not trace.ended_at:
                trace.ended_at = datetime.now(timezone.utc).isoformat()
        if expired:
            self.flush()
            for sid in expired:
                self.traces.pop(sid, None)
                self.last_active.pop(sid, None)

    def end_session(self, session_id: str) -> None:
        trace = self.traces.get(session_id)
        if trace and not trace.ended_at:
            trace.ended_at = datetime.now(timezone.utc).isoformat()
        self.flush()
        self.traces.pop(session_id, None)
        self.last_active.pop(session_id, None)

    def flush(self) -> None:
        """Write every known trace (one JSON line each) to the JSONL file."""
        path = self.trace_path
        if not path:
            return
        # Preserve lines of sessions already evicted from memory.
        existing: Dict[str, str] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    existing[json.loads(line)["session_id"]] = line
                except (json.JSONDecodeError, KeyError):
                    continue
        for sid, trace in self.traces.items():
            existing[sid] = json.dumps(trace.to_dict(), ensure_ascii=False)
        tmp = path.with_suffix(".jsonl.tmp")
        tmp.write_text("\n".join(existing.values()) + "\n", encoding="utf-8")
        tmp.replace(path)

    def flush_all(self) -> None:
        """Mark all open sessions ended and persist (shutdown hook)."""
        now = datetime.now(timezone.utc).isoformat()
        for trace in self.traces.values():
            if not trace.ended_at:
                trace.ended_at = now
        self.flush()


# ──────────────────────────────────────────────────────────────────
# Echo upstream: deterministic stand-in agent (offline / CI)
# ──────────────────────────────────────────────────────────────────

_ECHO_TEMPLATES = {
    "Spanish": {
        "ack": "Recibí tu mensaje: \"{snippet}\". Con gusto te ayudo.",
        "tool": " Consulté {tool} y esto encontré: {summary}.",
        "escalate": (
            " Entiendo, estoy escalando tu caso a un agente humano "
            "(escalating to human agent)."
        ),
        "fallback": " ¿Podrías darme más detalles para ayudarte mejor?",
    },
    "English": {
        "ack": "I received your message: \"{snippet}\". Happy to help.",
        "tool": " I checked {tool} and found: {summary}.",
        "escalate": " Understood — I am escalating your case to a human agent.",
        "fallback": " Could you share more details so I can help you better?",
    },
}


def _pick_tool(names: List[str], *substrings: str) -> Optional[str]:
    """First tool whose lowercase name contains any of the substrings."""
    for sub in substrings:
        for name in names:
            if sub in name.lower():
                return name
    return None


def _echo_turn(
    message: str,
    registry: MockToolRegistry,
    language: str,
) -> Tuple[str, List[Dict[str, Any]], List[TraceToolCall]]:
    """Deterministic stand-in agent: templated reply + 0-2 mock tool calls.

    Keyword routing (mirrors the TechRepair support domain the platform
    studies):
        - "orden"/"order"/digits  → first tool containing "order"/"status"
                                    (else the first registered tool)
        - "agente"/"human"        → tool containing "escalat" if any; the
                                    reply always contains "escalat" so the
                                    replay harness can detect the decision.
    """
    templates = _ECHO_TEMPLATES.get(language, _ECHO_TEMPLATES["Spanish"])
    msg_l = message.lower()
    snippet = message[:60].replace('"', "'")
    response = templates["ack"].format(snippet=snippet)

    names = registry.tool_names
    api_tool_calls: List[Dict[str, Any]] = []
    trace_tool_calls: List[TraceToolCall] = []

    def _invoke(tool_name: str) -> None:
        start = time.monotonic()
        result, injected = registry.call(tool_name, {"query": message[:100]})
        # registry.call sleeps for the configured latency, so the measured
        # wall time already includes injected latency.
        latency_ms = int((time.monotonic() - start) * 1000)
        api_tool_calls.append(
            {
                "tool_name": tool_name,
                "tool_id": uuid.uuid4().hex[:8],
                "arguments": {"query": message[:100]},
                "result": result,
                "injected_failure": injected,
            }
        )
        trace_tool_calls.append(
            TraceToolCall(
                name=tool_name,
                arguments={"query": message[:100]},
                result=result,
                injected_failure=injected,
                latency_ms=latency_ms,
            )
        )

    order_intent = (
        "orden" in msg_l or "order" in msg_l or any(ch.isdigit() for ch in message)
    )
    escalate_intent = "agente" in msg_l or "human" in msg_l

    if order_intent and names:
        tool = _pick_tool(names, "order", "status") or names[0]
        _invoke(tool)
        result_summary = str(trace_tool_calls[-1].result)[:80]
        response += templates["tool"].format(tool=tool, summary=result_summary)

    if escalate_intent:
        tool = _pick_tool(names, "escalat")
        if tool:
            _invoke(tool)
        response += templates["escalate"]

    if not order_intent and not escalate_intent:
        response += templates["fallback"]

    return response, api_tool_calls, trace_tool_calls


# ──────────────────────────────────────────────────────────────────
# HTTP upstream (wraps the real agent) with mock overlay
# ──────────────────────────────────────────────────────────────────


async def _http_turn(
    message: str,
    session_id: str,
    upstream_url: str,
    registry: MockToolRegistry,
) -> Tuple[str, List[Dict[str, Any]], List[TraceToolCall]]:
    """Forward the message to the wrapped agent and overlay mock results.

    v1 LIMITATION (documented in the module docstring): the upstream agent
    executes its own tools; the bridge records the tool calls it *reports*
    and overlays mock results (with failure injection) for any registered
    name. It cannot yet intercept execution mid-flight.
    """
    import httpx

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{upstream_url.rstrip('/')}/chat",
            json={"message": message, "session_id": session_id},
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Upstream agent returned HTTP {resp.status_code}",
        )
    data = resp.json()
    response_text = data.get("response", "")
    upstream_calls = data.get("tool_calls", []) or []

    api_tool_calls: List[Dict[str, Any]] = []
    trace_tool_calls: List[TraceToolCall] = []
    for tc in upstream_calls:
        if not isinstance(tc, dict):
            continue
        name = tc.get("tool_name") or tc.get("name") or "unknown"
        arguments = tc.get("arguments") or {}
        result = tc.get("result")
        injected: Optional[str] = None
        if name in registry:
            start = time.monotonic()
            result, injected = registry.call(name, arguments)
            latency_ms = int((time.monotonic() - start) * 1000)
        else:
            latency_ms = 0
        out = dict(tc)
        out["tool_name"] = name
        out["result"] = result
        out["injected_failure"] = injected
        api_tool_calls.append(out)
        trace_tool_calls.append(
            TraceToolCall(
                name=name,
                arguments=arguments if isinstance(arguments, dict) else {"raw": arguments},
                result=result,
                injected_failure=injected,
                latency_ms=latency_ms,
            )
        )
    return response_text, api_tool_calls, trace_tool_calls


# ──────────────────────────────────────────────────────────────────
# App factory
# ──────────────────────────────────────────────────────────────────


def create_bridge_app(config: SandboxBridgeConfig) -> FastAPI:
    """Build the sandbox bridge FastAPI app for the given config.

    Exposes the Phase C connector contract:
        POST /chat                      {"message", "session_id"} →
                                        {"response", "tool_calls", "session_id"}
        GET  /health                    {"status", "mode", "tools"}
        GET  /sessions/{id}/trace       SandboxTrace JSON
        POST /reset                     clear one session (or all)

    The registry and trace store live on ``app.state`` so in-process tests
    and the replay harness can introspect them.
    """
    registry = MockToolRegistry(config.mock_tools, seed=config.seed)
    store = TraceStore(config.trace_dir)

    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        yield
        store.flush_all()

    app = FastAPI(title="Sandbox Bridge", version=BRIDGE_VERSION, lifespan=_lifespan)
    app.state.config = config
    app.state.registry = registry
    app.state.trace_store = store

    base_metadata = {
        "language": config.language,
        "upstream_mode": config.mode,
        "bridge_version": BRIDGE_VERSION,
    }

    @app.post("/chat")
    async def chat(req: ChatRequest) -> Dict[str, Any]:
        store.evict_expired(config.session_ttl_sec)
        session_id = req.session_id or f"sbx-{uuid.uuid4().hex[:12]}"
        trace = store.get_or_create(session_id, base_metadata)
        trace.turns.append(TraceTurn(role="user", content=req.message))

        if config.mode == "echo":
            response_text, api_calls, trace_calls = _echo_turn(
                req.message, registry, config.language
            )
        elif config.mode == "http":
            if not config.upstream_url:
                raise HTTPException(
                    status_code=500, detail="http mode requires upstream_url"
                )
            response_text, api_calls, trace_calls = await _http_turn(
                req.message, session_id, config.upstream_url, registry
            )
        elif config.mode == "callable":
            if config.upstream_callable is None:
                raise HTTPException(
                    status_code=500, detail="callable mode requires upstream_callable"
                )
            raw = config.upstream_callable(req.message, session_id)
            if inspect.isawaitable(raw):
                raw = await raw
            raw = raw or {}
            response_text = raw.get("response", "")
            api_calls = []
            trace_calls = []
            for tc in raw.get("tool_calls", []) or []:
                name = tc.get("tool_name") or tc.get("name") or "unknown"
                arguments = tc.get("arguments") or {}
                result, injected = registry.call(name, arguments)
                api_calls.append(
                    {
                        "tool_name": name,
                        "arguments": arguments,
                        "result": result,
                        "injected_failure": injected,
                    }
                )
                trace_calls.append(
                    TraceToolCall(
                        name=name,
                        arguments=arguments,
                        result=result,
                        injected_failure=injected,
                        latency_ms=0,
                    )
                )
        else:  # pragma: no cover - config is Literal-validated
            raise HTTPException(status_code=500, detail=f"unknown mode {config.mode}")

        trace.turns.append(TraceTurn(role="assistant", content=response_text))
        trace.tool_calls.extend(trace_calls)
        store.flush()  # update the session's JSONL line every turn

        return {
            "response": response_text,
            "tool_calls": api_calls,
            "session_id": session_id,
        }

    @app.get("/health")
    async def health() -> Dict[str, Any]:
        return {"status": "ok", "mode": config.mode, "tools": registry.tool_names}

    @app.get("/sessions/{session_id}/trace")
    async def get_trace(session_id: str) -> Dict[str, Any]:
        trace = store.traces.get(session_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="unknown session")
        return trace.to_dict()

    @app.post("/reset")
    async def reset(req: ResetRequest | None = None) -> Dict[str, Any]:
        if req and req.session_id:
            store.end_session(req.session_id)
            return {"status": "ok", "cleared": [req.session_id]}
        cleared = list(store.traces.keys())
        store.flush_all()
        store.traces.clear()
        store.last_active.clear()
        return {"status": "ok", "cleared": cleared}

    return app
