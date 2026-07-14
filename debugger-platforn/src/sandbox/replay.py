"""
Replay harness: behavioural fidelity of the sandbox vs production.

Research purpose: the sandbox bridge is only useful for testing if it
behaves *like* the production agent. This module replays recorded
production conversations (TechRepair WhatsApp export schema: messages with
``source`` in {"customer", "ai_agent"} and ``text_body``) against a sandbox
``/chat`` endpoint and computes a deterministic, LLM-free fidelity score:

    overall = 0.5 * response_similarity   (difflib per-turn ratio)
            + 0.3 * tool_sequence_overlap (Jaccard over tool names)
            + 0.2 * escalation_agreement  (both or neither escalated)

The harness drives either a live URL (httpx) or a FastAPI app in-process
(starlette TestClient) via a small transport abstraction, so CI never opens
a socket.
"""

from __future__ import annotations

import difflib
import statistics
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

# Fidelity weights (kept module-level so the dissertation can cite them).
W_SIMILARITY = 0.5
W_TOOL_OVERLAP = 0.3
W_ESCALATION = 0.2

_ESCALATION_MARKER = "escalat"  # matches escalate/escalation/escalating/escalando... (en)


# ──────────────────────────────────────────────────────────────────
# Transport abstraction: live URL or in-process FastAPI app
# ──────────────────────────────────────────────────────────────────


class _Transport:
    """Minimal POST-only client over either a URL or an in-process app."""

    def __init__(self, target: Any):
        self._client: Any
        self._owns_client = True
        if isinstance(target, str):
            import httpx

            self._client = httpx.Client(base_url=target.rstrip("/"), timeout=120.0)
        elif hasattr(target, "post") and not hasattr(target, "router"):
            # Already a client (httpx.Client / TestClient) — reuse as-is.
            self._client = target
            self._owns_client = False
        else:
            # A FastAPI/Starlette app: drive it in-process, no network.
            from fastapi.testclient import TestClient

            self._client = TestClient(target)

    def post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        resp = self._client.post(path, json=payload)
        resp.raise_for_status()
        return resp.json()

    def close(self) -> None:
        if self._owns_client and hasattr(self._client, "close"):
            self._client.close()


# ──────────────────────────────────────────────────────────────────
# Replay result
# ──────────────────────────────────────────────────────────────────


@dataclass
class ReplayResult:
    """Outcome of replaying one production conversation into the sandbox."""

    conversation_id: str
    session_id: str
    turns: List[Dict[str, Any]] = field(default_factory=list)
    # Sandbox replies aligned with the customer messages that were replayed.
    sandbox_responses: List[str] = field(default_factory=list)
    sandbox_tool_names: List[str] = field(default_factory=list)

    @property
    def escalated(self) -> bool:
        """Sandbox decided to escalate: any reply or tool name mentions it."""
        if any(_ESCALATION_MARKER in r.lower() for r in self.sandbox_responses):
            return True
        return any(_ESCALATION_MARKER in n.lower() for n in self.sandbox_tool_names)


# ──────────────────────────────────────────────────────────────────
# Extraction helpers (TechRepair WhatsApp export schema)
# ──────────────────────────────────────────────────────────────────


def _customer_messages(conv: Dict[str, Any]) -> List[str]:
    return [
        (m.get("text_body") or "")
        for m in conv.get("messages", []) or []
        if m.get("source") == "customer" and (m.get("text_body") or "").strip()
    ]


def _production_replies(conv: Dict[str, Any]) -> List[str]:
    return [
        (m.get("text_body") or "")
        for m in conv.get("messages", []) or []
        if m.get("source") == "ai_agent" and (m.get("text_body") or "").strip()
    ]


def _production_tool_names(conv: Dict[str, Any]) -> List[str]:
    """Tool names from messages[].ai_tool_calls[].name, excluding "unknown"."""
    names: List[str] = []
    for m in conv.get("messages", []) or []:
        for tc in m.get("ai_tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            name = tc.get("name")
            if name and name != "unknown":
                names.append(name)
    return names


def _production_escalated(conv: Dict[str, Any]) -> bool:
    """Production decided to escalate: explicit field or escalation tool."""
    if conv.get("escalated_at"):
        return True
    return any(
        _ESCALATION_MARKER in n.lower() for n in _production_tool_names(conv)
    )


def _tool_name_of(tc: Dict[str, Any]) -> str:
    return str(tc.get("tool_name") or tc.get("name") or "")


# ──────────────────────────────────────────────────────────────────
# Replay
# ──────────────────────────────────────────────────────────────────


def replay_conversation(
    app_client_or_url: Any,
    production_conv: Dict[str, Any],
    max_turns: int = 10,
) -> ReplayResult:
    """Replay a production conversation's customer side into the sandbox.

    Plays each customer message (TechRepair export schema) into ``POST /chat``
    in order, under a single fresh session, and collects the sandbox
    responses and tool calls. The session is reset afterwards so its trace
    is flushed to the JSONL file.
    """
    transport = _Transport(app_client_or_url)
    session_id = f"replay-{uuid.uuid4().hex[:12]}"
    result = ReplayResult(
        conversation_id=str(production_conv.get("id", "")),
        session_id=session_id,
    )
    try:
        for message in _customer_messages(production_conv)[:max_turns]:
            data = transport.post(
                "/chat", {"message": message, "session_id": session_id}
            )
            response = data.get("response", "")
            tool_calls = data.get("tool_calls", []) or []
            result.turns.append(
                {
                    "user": message,
                    "sandbox_response": response,
                    "sandbox_tool_calls": tool_calls,
                }
            )
            result.sandbox_responses.append(response)
            result.sandbox_tool_names.extend(
                n for n in (_tool_name_of(tc) for tc in tool_calls if isinstance(tc, dict)) if n
            )
        # Flush the session's trace (best effort — /reset is bridge-specific).
        try:
            transport.post("/reset", {"session_id": session_id})
        except Exception:
            pass
    finally:
        transport.close()
    return result


# ──────────────────────────────────────────────────────────────────
# Fidelity scoring (deterministic, NO LLM)
# ──────────────────────────────────────────────────────────────────


def fidelity_score(
    production_conv: Dict[str, Any], replay_result: ReplayResult
) -> Dict[str, Any]:
    """Score how faithfully the sandbox reproduced production behaviour.

    Components (each in [0, 1]):
        - ``response_similarity``: mean ``difflib.SequenceMatcher`` ratio
          between the production ai_agent reply and the sandbox reply,
          aligned by turn index (over the turns both sides have).
        - ``tool_sequence_overlap``: Jaccard similarity between the sets of
          production tool names (``ai_tool_calls[].name``, excluding
          "unknown") and sandbox tool names. Both-empty counts as 1.0
          (perfect agreement on "no tools needed").
        - ``escalation_agreement``: True iff both or neither side decided
          to escalate.

    overall = 0.5*similarity + 0.3*overlap + 0.2*escalation_agreement.
    """
    prod_replies = _production_replies(production_conv)
    sandbox_replies = replay_result.sandbox_responses

    n = min(len(prod_replies), len(sandbox_replies))
    if n == 0:
        similarity = 0.0
    else:
        ratios = [
            difflib.SequenceMatcher(
                None, prod_replies[i].lower(), sandbox_replies[i].lower()
            ).ratio()
            for i in range(n)
        ]
        similarity = sum(ratios) / n

    prod_tools = set(_production_tool_names(production_conv))
    sandbox_tools = set(replay_result.sandbox_tool_names)
    if not prod_tools and not sandbox_tools:
        overlap = 1.0
    else:
        union = prod_tools | sandbox_tools
        overlap = len(prod_tools & sandbox_tools) / len(union) if union else 1.0

    agreement = _production_escalated(production_conv) == replay_result.escalated

    overall = (
        W_SIMILARITY * similarity
        + W_TOOL_OVERLAP * overlap
        + W_ESCALATION * (1.0 if agreement else 0.0)
    )

    return {
        "conversation_id": replay_result.conversation_id,
        "response_similarity": round(similarity, 4),
        "tool_sequence_overlap": round(overlap, 4),
        "escalation_agreement": bool(agreement),
        "overall": round(overall, 4),
        "turns_compared": n,
    }


# ──────────────────────────────────────────────────────────────────
# Batch replay
# ──────────────────────────────────────────────────────────────────


def replay_batch(
    url_or_app: Any,
    conversations: List[Dict[str, Any]],
    n: Optional[int] = None,
    max_turns: int = 10,
) -> Dict[str, Any]:
    """Replay up to ``n`` conversations and aggregate fidelity.

    Returns a summary dict with mean/median overall fidelity, per-component
    means, and per-conversation scores — the artefact the dissertation's
    sandbox-validity section reports.
    """
    batch = conversations[:n] if n is not None else conversations
    scores: List[Dict[str, Any]] = []
    for conv in batch:
        result = replay_conversation(url_or_app, conv, max_turns=max_turns)
        scores.append(fidelity_score(conv, result))

    overalls = [s["overall"] for s in scores]
    summary: Dict[str, Any] = {
        "num_conversations": len(scores),
        "mean_overall": round(statistics.fmean(overalls), 4) if overalls else 0.0,
        "median_overall": round(statistics.median(overalls), 4) if overalls else 0.0,
        "mean_response_similarity": (
            round(statistics.fmean(s["response_similarity"] for s in scores), 4)
            if scores
            else 0.0
        ),
        "mean_tool_sequence_overlap": (
            round(statistics.fmean(s["tool_sequence_overlap"] for s in scores), 4)
            if scores
            else 0.0
        ),
        "escalation_agreement_rate": (
            round(
                sum(1 for s in scores if s["escalation_agreement"]) / len(scores), 4
            )
            if scores
            else 0.0
        ),
        "per_conversation": scores,
    }
    return summary
