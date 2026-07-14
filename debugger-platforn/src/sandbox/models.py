"""
Pydantic models for the Sandbox Bridge subsystem.

Research purpose: the sandbox bridge wraps a production conversational agent
behind a TEST endpoint with a mock tool layer and deterministic failure
injection. These models define (a) how each mock tool behaves
(`MockToolConfig`), (b) how the bridge itself is wired
(`SandboxBridgeConfig`), and (c) the *shared trace schema*
(`SandboxTrace`) in which every sandboxed conversation is captured, so that
Phase C executions and the replay/fidelity harness speak the same language.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

BRIDGE_VERSION = "1.0.0"


def _utcnow_iso() -> str:
    """ISO-8601 UTC timestamp (shared trace schema uses strings for JSONL)."""
    return datetime.now(timezone.utc).isoformat()


class MockToolConfig(BaseModel):
    """Configuration for one mocked tool.

    The canned ``response`` is returned for every call unless failure
    injection kicks in. ``response_variants`` (optional) lets a mock cycle
    deterministically through several plausible payloads, which increases
    behavioural coverage without an LLM.

    Failure injection (all driven by the bridge-level seed, so runs are
    reproducible):
        - ``error_rate``:  probability [0..1] the call returns ``error_payload``
        - ``empty_rate``:  probability [0..1] the call returns an empty result
        - ``latency_ms``:  artificial latency added to every call
    """

    name: str
    response: Any = Field(default_factory=lambda: {"status": "ok"})
    response_variants: Optional[List[Any]] = None

    # Failure injection knobs
    error_rate: float = 0.0
    empty_rate: float = 0.0
    latency_ms: int = 0
    error_payload: Any = Field(
        default_factory=lambda: {"status": "error", "error": "injected_tool_failure"}
    )


class SandboxBridgeConfig(BaseModel):
    """Wiring for one sandbox bridge instance.

    Upstream modes:
        - ``echo``:     deterministic stand-in agent (offline / CI); replies
                        with templated support responses and calls 0-2 mock
                        tools chosen by keyword rules.
        - ``http``:     forwards each message to ``upstream_url``/chat (the
                        wrapped *real* agent) and overlays mock results for
                        any returned tool call whose name is registered.
        - ``callable``: routes each message to ``upstream_callable`` — an
                        in-process function ``(message, session_id) -> dict``
                        returning ``{"response": str, "tool_calls": list}``
                        (may be sync or async). Useful for unit-testing
                        custom upstreams without a socket.
    """

    mode: Literal["echo", "http", "callable"] = "echo"
    upstream_url: Optional[str] = None
    upstream_callable: Optional[Callable[..., Any]] = None
    mock_tools: List[MockToolConfig] = Field(default_factory=list)
    trace_dir: Optional[str] = None
    language: str = "Spanish"
    session_ttl_sec: int = 3600
    seed: int = 42

    model_config = {"arbitrary_types_allowed": True}


class TraceTurn(BaseModel):
    """One conversation turn in the shared trace schema."""

    role: Literal["user", "assistant"]
    content: str
    timestamp: str = Field(default_factory=_utcnow_iso)


class TraceToolCall(BaseModel):
    """One tool invocation in the shared trace schema.

    ``injected_failure`` records whether the mock layer deliberately broke
    this call ("error" | "empty_response") — the ground truth the diagnosis
    phase needs to distinguish injected faults from genuine agent failures.
    """

    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    result: Any = None
    injected_failure: Optional[str] = None
    latency_ms: int = 0


class SandboxTrace(BaseModel):
    """Shared trace schema: one sandboxed conversation session.

    Serialised as one JSON line per session in the bridge's trace JSONL
    file, and returned verbatim by ``GET /sessions/{id}/trace`` so the
    replay harness, Phase C executor and offline analysis all consume the
    exact same record.
    """

    trace_id: str
    session_id: str
    started_at: str = Field(default_factory=_utcnow_iso)
    ended_at: Optional[str] = None
    turns: List[TraceTurn] = Field(default_factory=list)
    tool_calls: List[TraceToolCall] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Plain-dict form (JSON-able) of the trace."""
        return self.model_dump(mode="json")
