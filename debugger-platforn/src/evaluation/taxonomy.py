"""
Shared Failure Taxonomy (Sprint E12.1, frozen for the predictive-validity study).

Defines the failure categories that every measurement in the harness is
expressed against, maps each category to OWASP LLM 2025 / OWASP Agentic 2026
taxonomy IDs (the same IDs Phase A attaches to risk_flags), and assigns
severity weights used by weighted APFD and prioritisation.

This is the SHARED taxonomy spanning both failure sources: synthetic failures
(Phase C execution + Phase D diagnosis) and real production failures
(human-process signals: escalations, takeovers, complaints, QA flags).  Both
sources are projected onto it by :mod:`src.evaluation.projection`.  The first
twelve categories are synthetic-native; the last four exist because production
telemetry surfaces failure modes that agent-structure-derived testing does not
name (comprehension, resolution, backend data gaps, delivery infrastructure).

FROZEN: the category set below is versioned and must not change during a
measurement campaign — precision/recall comparisons are only meaningful
against a fixed vocabulary.  Bump TAXONOMY_VERSION if it ever changes.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List

TAXONOMY_VERSION = "1.0-frozen-2026-07-14"


class FailureCategory(str, Enum):
    WRONG_TOOL = "wrong_tool"                     # Agent called the wrong tool
    MISSED_TOOL = "missed_tool"                   # Agent should have called a tool but didn't
    HALLUCINATION = "hallucination"               # Agent fabricated information
    PII_LEAK = "pii_leak"                         # Agent disclosed PII
    GUARDRAIL_VIOLATION = "guardrail_violation"   # Agent violated a numbered policy rule
    EXCESSIVE_AGENCY = "excessive_agency"         # Agent took action without confirmation
    ESCALATION_FAILURE = "escalation_failure"     # Agent failed to escalate when it should have
    LANGUAGE_ERROR = "language_error"             # Agent responded in wrong language
    TOOL_MISUSE = "tool_misuse"                   # Agent called tool with wrong/dangerous args
    INFINITE_LOOP = "infinite_loop"               # Agent stuck in a loop
    PREMATURE_EXIT = "premature_exit"             # Agent ended conversation prematurely
    STYLE_VIOLATION = "style_violation"           # Agent violated style guide (tone, length)
    # Production-spanning categories (observed in human-process signals)
    COMPREHENSION_FAILURE = "comprehension_failure"  # Agent did not understand the user's need
    RESOLUTION_FAILURE = "resolution_failure"        # Agent understood but could not resolve; user demanded a human
    DATA_GAP = "data_gap"                            # Backend/tool data missing or incomplete
    DELIVERY_FAILURE = "delivery_failure"            # Message/infrastructure delivery failure


# OWASP LLM 2025 (LLM01-LLM10) and OWASP Agentic 2026 (ASI01-ASI10) IDs,
# matching the taxonomy IDs Phase A attaches to risk_flags.all_risks[].
CATEGORY_TAXONOMY_IDS: Dict[FailureCategory, List[str]] = {
    FailureCategory.WRONG_TOOL: ["ASI02"],                       # Tool Misuse and Exploitation
    FailureCategory.MISSED_TOOL: ["ASI08"],                      # Cascading Failures
    FailureCategory.HALLUCINATION: ["LLM09"],                    # Misinformation
    FailureCategory.PII_LEAK: ["LLM02", "ASI03"],                # Sensitive Info Disclosure / Privilege Abuse
    FailureCategory.GUARDRAIL_VIOLATION: ["LLM01", "ASI01"],     # Prompt Injection / Goal Hijack
    FailureCategory.EXCESSIVE_AGENCY: ["LLM06", "ASI03"],        # Excessive Agency / Privilege Abuse
    FailureCategory.ESCALATION_FAILURE: ["ASI09"],               # Human-Agent Trust Exploitation
    FailureCategory.LANGUAGE_ERROR: ["LLM05"],                   # Improper Output Handling
    FailureCategory.TOOL_MISUSE: ["ASI02", "LLM06"],             # Tool Misuse / Excessive Agency
    FailureCategory.INFINITE_LOOP: ["LLM10", "ASI08"],           # Unbounded Consumption / Cascading Failures
    FailureCategory.PREMATURE_EXIT: ["ASI09"],                   # Human-Agent Trust Exploitation
    FailureCategory.STYLE_VIOLATION: ["LLM05"],                  # Improper Output Handling
    FailureCategory.COMPREHENSION_FAILURE: ["LLM09"],            # Misinformation (wrong-topic responses)
    FailureCategory.RESOLUTION_FAILURE: ["ASI09"],               # Human-Agent Trust Exploitation
    FailureCategory.DATA_GAP: ["ASI08"],                         # Cascading Failures (upstream data)
    FailureCategory.DELIVERY_FAILURE: ["ASI08"],                 # Cascading Failures (infrastructure)
}


# Severity level per failure category.
CATEGORY_SEVERITY: Dict[FailureCategory, str] = {
    FailureCategory.WRONG_TOOL: "high",
    FailureCategory.MISSED_TOOL: "medium",
    FailureCategory.HALLUCINATION: "high",
    FailureCategory.PII_LEAK: "critical",
    FailureCategory.GUARDRAIL_VIOLATION: "critical",
    FailureCategory.EXCESSIVE_AGENCY: "critical",
    FailureCategory.ESCALATION_FAILURE: "high",
    FailureCategory.LANGUAGE_ERROR: "low",
    FailureCategory.TOOL_MISUSE: "high",
    FailureCategory.INFINITE_LOOP: "medium",
    FailureCategory.PREMATURE_EXIT: "medium",
    FailureCategory.STYLE_VIOLATION: "low",
    FailureCategory.COMPREHENSION_FAILURE: "high",
    FailureCategory.RESOLUTION_FAILURE: "high",
    FailureCategory.DATA_GAP: "medium",
    FailureCategory.DELIVERY_FAILURE: "medium",
}


# Numeric weights used by weighted APFD and prioritisation.
SEVERITY_WEIGHTS: Dict[str, int] = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
}


def severity_weight(category: FailureCategory) -> int:
    """Return the numeric severity weight (1-4) for a failure category."""
    return SEVERITY_WEIGHTS[CATEGORY_SEVERITY[category]]
