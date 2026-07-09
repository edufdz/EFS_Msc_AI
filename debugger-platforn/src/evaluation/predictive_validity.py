"""
Predictive Validity: Precision/Recall Against Production Signals (Sprint E12.3).

A test suite has predictive validity when the failures it can surface
correspond to failures observed in production (Langfuse traces, escalations,
complaints, QA flags).  This module converts production evidence into
``ProductionSignal`` objects and scores a suite's synthetic failures
against them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.evaluation.taxonomy import FailureCategory


@dataclass
class ProductionSignal:
    signal_id: str
    trace_id: str                              # Langfuse trace ID
    failure_category: FailureCategory
    description: str
    tool_involved: Optional[str] = None
    guardrail_rule_id: Optional[str] = None    # R001, R002, etc.
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "human_label"                # "escalation", "complaint", "qa_flag", "human_label"


def _category_of(value: Any) -> Optional[FailureCategory]:
    """Normalise a category value (str or FailureCategory) to the enum."""
    if isinstance(value, FailureCategory):
        return value
    if isinstance(value, str):
        try:
            return FailureCategory(value)
        except ValueError:
            return None
    return None


def _matches(synthetic: Dict[str, Any], signal: ProductionSignal) -> bool:
    """A synthetic failure matches a production signal when the failure
    category is the same AND the finer identifier the signal carries agrees:

      - signal names a tool          -> synthetic must name the same tool
      - signal names a guardrail rule -> synthetic must name the same rule
      - signal has neither            -> category match alone suffices
    """
    synth_category = _category_of(synthetic.get("failure_category"))
    if synth_category is None or synth_category != signal.failure_category:
        return False

    if signal.tool_involved is not None:
        if synthetic.get("tool_involved") == signal.tool_involved:
            return True
    if signal.guardrail_rule_id is not None:
        if synthetic.get("guardrail_rule_id") == signal.guardrail_rule_id:
            return True
    if signal.tool_involved is None and signal.guardrail_rule_id is None:
        return True
    return False


def compute_predictive_validity(
    synthetic_failures: List[Dict[str, Any]],
    production_signals: List[ProductionSignal],
) -> Dict[str, Any]:
    """Score synthetic failures against independent production signals.

    Args:
        synthetic_failures: dicts with keys ``failure_category`` (str or
            FailureCategory), and optionally ``tool_involved`` and
            ``guardrail_rule_id``.
        production_signals: independently sourced production failures.

    Returns:
        dict with ``precision`` (fraction of synthetic failures matching a
        real signal), ``recall`` (fraction of signals covered by at least one
        synthetic failure), ``f1``, ``matched_signals`` (signal IDs),
        ``unmatched_signals`` (signal IDs), and ``false_positives`` (the
        synthetic failures that matched nothing).
    """
    matched_signal_ids: List[str] = []
    unmatched_signal_ids: List[str] = []
    for signal in production_signals:
        if any(_matches(s, signal) for s in synthetic_failures):
            matched_signal_ids.append(signal.signal_id)
        else:
            unmatched_signal_ids.append(signal.signal_id)

    false_positives: List[Dict[str, Any]] = []
    n_matched_synthetic = 0
    for synth in synthetic_failures:
        if any(_matches(synth, signal) for signal in production_signals):
            n_matched_synthetic += 1
        else:
            false_positives.append(synth)

    n_synthetic = len(synthetic_failures)
    n_signals = len(production_signals)
    precision = n_matched_synthetic / n_synthetic if n_synthetic else 0.0
    recall = len(matched_signal_ids) / n_signals if n_signals else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "n_synthetic_failures": n_synthetic,
        "n_production_signals": n_signals,
        "matched_signals": matched_signal_ids,
        "unmatched_signals": unmatched_signal_ids,
        "false_positives": false_positives,
    }


# ----------------------------------------------------------------------
# Loading signals from Phase A trace analysis
# ----------------------------------------------------------------------

_ESCALATION_KEYWORDS = ("escalat", "handoff", "hand_off", "transfer_to_human", "human_agent")


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Read *key* from a dict or an attribute from an object."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _classify_sequence(sequence: List[str]) -> FailureCategory:
    """Heuristically map a failing tool sequence to a FailureCategory."""
    if not sequence:
        return FailureCategory.PREMATURE_EXIT
    # Same tool repeated back-to-back looks like a retry/stuck loop
    for a, b in zip(sequence, sequence[1:]):
        if a == b:
            return FailureCategory.INFINITE_LOOP
    # Sequence ending at an escalation tool: escalation-path failure
    if any(kw in sequence[-1].lower() for kw in _ESCALATION_KEYWORDS):
        return FailureCategory.ESCALATION_FAILURE
    return FailureCategory.TOOL_MISUSE


def load_production_signals(trace_result: Any, agent_map: Dict) -> List[ProductionSignal]:
    """Convert Phase A trace analysis into ProductionSignal objects.

    Accepts either a ``TraceAnalysisResult``-like object or the
    ``trace_analysis`` dict embedded in an agent map.  Produces one signal
    per Langfuse failure pattern (source="qa_flag") and one per escalation
    conversation (source="escalation").
    """
    if trace_result is None:
        return []

    signals: List[ProductionSignal] = []

    # Guardrail rules targeting a tool, used to attach rule IDs to signals
    guardrail_rules = (agent_map.get("guardrails") or {}).get("rules", [])
    rules_by_tool: Dict[str, str] = {}
    for rule in guardrail_rules:
        for tool in rule.get("target_tools", []) or []:
            rules_by_tool.setdefault(tool, rule.get("rule_id"))

    # 1) Langfuse failure patterns -> qa_flag signals
    failure_patterns = _get(trace_result, "failure_patterns", []) or []
    for i, pattern in enumerate(failure_patterns, start=1):
        sequence = list(_get(pattern, "sequence", []) or [])
        category = _classify_sequence(sequence)
        tool = sequence[-1] if sequence else None
        rate = _get(pattern, "failure_rate", None)
        count = _get(pattern, "count", None)
        description = f"Tool sequence {' -> '.join(sequence) or '(empty)'} correlated with failure"
        if rate is not None:
            description += f" (failure_rate={rate}"
            description += f", count={count})" if count is not None else ")"
        signals.append(ProductionSignal(
            signal_id=f"sig_pattern_{i:03d}",
            trace_id=str(_get(pattern, "trace_id", "") or f"pattern_{i}"),
            failure_category=category,
            description=description,
            tool_involved=tool,
            guardrail_rule_id=rules_by_tool.get(tool) if tool else None,
            source="qa_flag",
        ))

    # 2) Escalated conversations -> escalation signals
    conversations = _get(trace_result, "conversations", []) or []
    n_escalations = 0
    for conv in conversations:
        outcome = str(_get(conv, "outcome", "") or "").lower()
        escalated = bool(_get(conv, "escalated", False)) or "escalat" in outcome
        if not escalated:
            continue
        n_escalations += 1
        tools = list(_get(conv, "tool_calls", []) or _get(conv, "tools", []) or [])
        tool = tools[-1] if tools else None
        signals.append(ProductionSignal(
            signal_id=f"sig_escalation_{n_escalations:03d}",
            trace_id=str(_get(conv, "trace_id", "") or _get(conv, "conversation_id", "") or f"escalation_{n_escalations}"),
            failure_category=FailureCategory.ESCALATION_FAILURE,
            description="Conversation escalated to a human agent",
            tool_involved=tool,
            guardrail_rule_id=rules_by_tool.get(tool) if tool else None,
            source="escalation",
        ))

    return signals
