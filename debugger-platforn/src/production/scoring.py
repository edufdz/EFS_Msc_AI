"""
Phase-1 structured signal scoring (docs/Agent_Failure_Plan.md).

Scores every conversation from structured, human-process signals only — no
language model is involved anywhere in this module.  That restriction is the
methodological core of the study: the ground truth against which synthetic
testing is validated must be independent of any LLM judge.

The failure-score formula and the eight production failure categories are
taken directly from the failure-analysis plan.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ----------------------------------------------------------------------
# Signal extraction helpers
# ----------------------------------------------------------------------


def _norm(text: str) -> str:
    """Lowercase and strip accents for robust Spanish keyword matching."""
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


# Customer explicitly asking for a human (Spanish variants)
_HUMAN_REQUEST_PATTERNS = [
    "hablar con un agente", "hablar con agente", "hablar con alguien",
    "hablar con una persona", "persona real", "un humano", "con humano",
    "asesor humano", "explicit_human_request",
]

# Escalation reasons that indicate missing backend data
_DATA_GAP_PATTERNS = ["sin datos completos", "sin garantia", "sin costo", "gspn"]

# Customer pushback suggesting the agent said something wrong
_PUSHBACK_PATTERNS = [
    "no es correcto", "eso no es cierto", "esta mal", "no es asi",
    "me dijeron otra cosa", "eso es incorrecto", "es mentira",
    "informacion incorrecta", "no coincide",
]

# Frustration wording in customer messages (beyond the detected intent)
_FRUSTRATION_PATTERNS = [
    "es una perdida de tiempo", "pesimo servicio", "pesimo", "molesto",
    "molesta", "harto", "harta", "queja", "profeco", "demanda",
    "inaceptable", "furioso", "furiosa", "enojado", "enojada",
]


@dataclass
class ConversationScore:
    """Structured-signal analysis of one production conversation."""

    conversation_id: str
    failure_score: float = 0.0
    categories: List[str] = field(default_factory=list)   # production vocabulary
    evidence: Dict[str, Any] = field(default_factory=dict)
    # Raw signals (kept for RQ2 coverage-gap characterisation)
    escalated: bool = False
    requested_human: bool = False
    human_takeover: bool = False
    frustration: bool = False
    expired_unresolved: bool = False
    unknown_intent_count: int = 0
    ai_message_count: int = 0
    min_confidence: Optional[float] = None
    customer_repeat_count: int = 0
    failed_delivery_count: int = 0
    message_count: int = 0
    tools_involved: List[str] = field(default_factory=list)


def _customer_texts(messages: List[Dict[str, Any]]) -> List[str]:
    return [
        (m.get("text_body") or "").strip()
        for m in messages
        if m.get("source") == "customer" and (m.get("text_body") or "").strip()
    ]


def _ai_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [m for m in messages if m.get("source") == "ai_agent"]


def _tool_names(messages: List[Dict[str, Any]]) -> List[str]:
    """Extract tool names from ai_tool_calls, skipping unnamed entries."""
    names: List[str] = []
    for m in messages:
        calls = m.get("ai_tool_calls") or []
        if isinstance(calls, dict):
            calls = calls.get("calls", []) or []
        for call in calls:
            if isinstance(call, dict):
                name = call.get("name") or call.get("tool") or call.get("tool_name")
            else:
                name = str(call)
            if name and name.lower() != "unknown":
                names.append(name)
    return names


def score_conversation(conv: Dict[str, Any]) -> ConversationScore:
    """Score one conversation with the Agent_Failure_Plan formula and
    classify it into production failure categories.

    Purely structural — reads only fields written by humans or operational
    systems (escalation records, delivery statuses, message metadata).
    """
    messages: List[Dict[str, Any]] = conv.get("messages") or []
    ai_msgs = _ai_messages(messages)
    customer_texts = _customer_texts(messages)

    score = ConversationScore(
        conversation_id=str(conv.get("id", "")),
        message_count=int(conv.get("message_count") or len(messages)),
        ai_message_count=len(ai_msgs),
        tools_involved=_tool_names(messages),
    )

    # --- Raw signals -------------------------------------------------
    reason_norm = _norm(str(conv.get("escalation_reason") or ""))
    score.escalated = bool(conv.get("escalated_at") or conv.get("escalation_reason"))
    score.human_takeover = bool(conv.get("taken_over_at") or conv.get("is_human_handling"))

    score.requested_human = any(p in reason_norm for p in map(_norm, _HUMAN_REQUEST_PATTERNS))
    if not score.requested_human:
        score.requested_human = any(
            any(p in _norm(t) for p in map(_norm, _HUMAN_REQUEST_PATTERNS))
            for t in customer_texts
        )

    intents = [m.get("ai_intent_detected") for m in ai_msgs if m.get("ai_intent_detected")]
    # Intent fields are also recorded on customer messages in some exports
    intents += [
        m.get("ai_intent_detected") for m in messages
        if m.get("source") == "customer" and m.get("ai_intent_detected")
    ]
    score.unknown_intent_count = sum(1 for i in intents if i == "unknown")
    score.frustration = (
        any(i == "complaint_or_frustration" for i in intents)
        or "complaint_escalation" in reason_norm
        or any(any(p in _norm(t) for p in map(_norm, _FRUSTRATION_PATTERNS)) for t in customer_texts)
    )

    confidences = [
        m.get("ai_confidence_score") for m in messages
        if m.get("ai_confidence_score") is not None
    ]
    score.min_confidence = min(confidences) if confidences else None

    # Customer repeating themselves: identical consecutive customer messages
    repeats = 0
    for a, b in zip(customer_texts, customer_texts[1:]):
        if a and _norm(a) == _norm(b):
            repeats += 1
    score.customer_repeat_count = repeats

    score.failed_delivery_count = sum(1 for m in messages if m.get("status") == "failed")

    last_substantive = next(
        (m for m in reversed(messages) if m.get("source") in ("customer", "ai_agent", "human_agent")),
        None,
    )
    score.expired_unresolved = (
        conv.get("status") == "expired"
        and not score.escalated
        and last_substantive is not None
        and last_substantive.get("source") == "ai_agent"
    )

    # --- Failure score (Agent_Failure_Plan formula) -------------------
    s = 0.0
    if score.escalated:
        s += 3
    if score.requested_human:
        s += 5
    if score.unknown_intent_count and score.ai_message_count:
        s += 2 * (score.unknown_intent_count / max(score.ai_message_count, 1))
    if score.min_confidence is not None and score.min_confidence < 0.5:
        s += 2 * (1 - score.min_confidence)
    if score.customer_repeat_count:
        s += 1 * score.customer_repeat_count
    if score.message_count > 40:
        s += 2
    if score.failed_delivery_count:
        s += 1
    if score.frustration:
        s += 3
    if score.expired_unresolved:
        s += 2
    if score.human_takeover:
        s += 4
    score.failure_score = round(s, 3)

    # --- Category classification --------------------------------------
    categories: List[str] = []
    evidence: Dict[str, Any] = {}

    # 1. Comprehension failure
    if (
        score.unknown_intent_count >= 2
        or (score.min_confidence is not None and score.min_confidence < 0.5)
        or score.customer_repeat_count >= 2
    ):
        categories.append("comprehension")
        evidence["comprehension"] = {
            "unknown_intents": score.unknown_intent_count,
            "min_confidence": score.min_confidence,
            "customer_repeats": score.customer_repeat_count,
        }

    # 2. Resolution failure (explicit human request)
    if score.requested_human:
        categories.append("resolution")
        evidence["resolution"] = {"escalation_reason": conv.get("escalation_reason")}

    # 3. Data gap
    if any(p in reason_norm for p in map(_norm, _DATA_GAP_PATTERNS)):
        categories.append("data_gap")
        evidence["data_gap"] = {"escalation_reason": conv.get("escalation_reason")}

    # 4. Loop / stall
    ai_texts = [_norm(m.get("text_body") or "") for m in ai_msgs if (m.get("text_body") or "").strip()]
    repeated_ai = 0
    seen: Dict[str, int] = {}
    for t in ai_texts:
        seen[t] = seen.get(t, 0) + 1
    repeated_ai = max(seen.values()) if seen else 0
    if score.message_count > 40 or repeated_ai >= 3:
        categories.append("loop_stall")
        evidence["loop_stall"] = {
            "message_count": score.message_count,
            "max_identical_ai_responses": repeated_ai,
        }

    # 5. Delivery / infrastructure failure
    if score.failed_delivery_count:
        error_codes = sorted({
            str(m.get("error_code")) for m in messages
            if m.get("status") == "failed" and m.get("error_code")
        })
        categories.append("delivery_infra")
        evidence["delivery_infra"] = {
            "failed_messages": score.failed_delivery_count,
            "error_codes": error_codes,
        }

    # 6. Missed escalation (frustration without escalation)
    if score.frustration and not score.escalated and not score.human_takeover:
        categories.append("missed_escalation")
        evidence["missed_escalation"] = {"frustration_detected": True}

    # 7. Silent abandonment
    if score.expired_unresolved:
        categories.append("silent_abandonment")
        evidence["silent_abandonment"] = {"status": conv.get("status")}

    # 8. Hallucination / wrong information (customer pushback heuristic)
    pushback = [
        t for t in customer_texts
        if any(p in _norm(t) for p in map(_norm, _PUSHBACK_PATTERNS))
    ]
    if pushback:
        categories.append("hallucination")
        evidence["hallucination"] = {"pushback_count": len(pushback)}

    score.categories = categories
    score.evidence = evidence
    return score
