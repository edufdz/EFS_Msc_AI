"""
Projection Layer: maps failures from every source onto the shared taxonomy.

The predictive-validity study compares failures from two independent origins:

  1. SYNTHETIC — Phase C execution failures diagnosed by Phase D, whose
     vocabulary is :class:`src.diagnosis.models.RootCauseType` (12 values).
  2. PRODUCTION — human-process signals mined from real deployed-agent
     conversations, whose vocabulary is the eight production failure
     categories defined in the TechRepair failure-analysis plan
     (docs/Agent_Failure_Plan.md).

Comparability is impossible until both speak the same vocabulary, so this
module defines two TOTAL, FROZEN mappings onto
:class:`src.evaluation.taxonomy.FailureCategory`.  Totality is enforced at
import time: adding a RootCauseType or production category without extending
the projection is an immediate error, not a silent measurement gap.

Both maps are deliberately simple dictionaries — the dissertation must be able
to print them as a table and defend every row.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from src.diagnosis.models import RootCauseType
from src.evaluation.taxonomy import TAXONOMY_VERSION, FailureCategory

# ----------------------------------------------------------------------
# Production-side vocabulary (Agent_Failure_Plan.md, section "Failure
# Taxonomy") — the eight categories detectable from human-process signals.
# ----------------------------------------------------------------------

PRODUCTION_CATEGORIES: List[str] = [
    "comprehension",        # agent did not understand the request
    "resolution",           # agent understood but could not resolve; user demanded a human
    "data_gap",             # backend data (GSPN/orders) missing or incomplete
    "loop_stall",           # conversation circled without progress
    "delivery_infra",       # WhatsApp/API delivery failure
    "missed_escalation",    # frustration expressed but agent did not escalate
    "silent_abandonment",   # customer stopped responding, no resolution
    "hallucination",        # agent gave wrong information
]


# Production category -> shared taxonomy.  One row per category; every row
# individually defensible:
#   - comprehension     : the agent misread the user's need           -> COMPREHENSION_FAILURE
#   - resolution        : understood but unresolved, human requested  -> RESOLUTION_FAILURE
#   - data_gap          : upstream data missing                        -> DATA_GAP
#   - loop_stall        : repeated questions/answers, no progress      -> INFINITE_LOOP
#   - delivery_infra    : message never reached the customer           -> DELIVERY_FAILURE
#   - missed_escalation : should have escalated and did not            -> ESCALATION_FAILURE
#   - silent_abandonment: conversation died without closure            -> PREMATURE_EXIT
#   - hallucination     : fabricated/wrong information                 -> HALLUCINATION
PRODUCTION_CATEGORY_PROJECTION: Dict[str, FailureCategory] = {
    "comprehension": FailureCategory.COMPREHENSION_FAILURE,
    "resolution": FailureCategory.RESOLUTION_FAILURE,
    "data_gap": FailureCategory.DATA_GAP,
    "loop_stall": FailureCategory.INFINITE_LOOP,
    "delivery_infra": FailureCategory.DELIVERY_FAILURE,
    "missed_escalation": FailureCategory.ESCALATION_FAILURE,
    "silent_abandonment": FailureCategory.PREMATURE_EXIT,
    "hallucination": FailureCategory.HALLUCINATION,
}


# Phase D root cause -> shared taxonomy.  One row per RootCauseType:
#   - prompt_issue         : prompt defect misdirects the agent        -> COMPREHENSION_FAILURE
#   - tool_selection_error : wrong tool chosen                          -> WRONG_TOOL
#   - tool_schema_mismatch : bad arguments / schema drift               -> TOOL_MISUSE
#   - missing_guardrail    : policy rule not enforced                   -> GUARDRAIL_VIOLATION
#   - retry_logic_bug      : retry storm / stuck retrying               -> INFINITE_LOOP
#   - hallucination        : fabricated information                     -> HALLUCINATION
#   - timeout_handling     : timed out / never delivered a usable reply -> DELIVERY_FAILURE
#   - error_handling       : upstream error surfaced raw / mishandled   -> DATA_GAP
#   - state_management     : lost context, re-asks, circular dialogue   -> INFINITE_LOOP
#   - validation_missing   : unvalidated input reached a tool           -> TOOL_MISUSE
#   - edge_case_unhandled  : understood but had no path to resolve      -> RESOLUTION_FAILURE
#   - service_unavailable  : dependency down                            -> DELIVERY_FAILURE
ROOT_CAUSE_PROJECTION: Dict[RootCauseType, FailureCategory] = {
    RootCauseType.PROMPT_ISSUE: FailureCategory.COMPREHENSION_FAILURE,
    RootCauseType.TOOL_SELECTION_ERROR: FailureCategory.WRONG_TOOL,
    RootCauseType.TOOL_SCHEMA_MISMATCH: FailureCategory.TOOL_MISUSE,
    RootCauseType.MISSING_GUARDRAIL: FailureCategory.GUARDRAIL_VIOLATION,
    RootCauseType.RETRY_LOGIC_BUG: FailureCategory.INFINITE_LOOP,
    RootCauseType.HALLUCINATION: FailureCategory.HALLUCINATION,
    RootCauseType.TIMEOUT_HANDLING: FailureCategory.DELIVERY_FAILURE,
    RootCauseType.ERROR_HANDLING: FailureCategory.DATA_GAP,
    RootCauseType.STATE_MANAGEMENT: FailureCategory.INFINITE_LOOP,
    RootCauseType.VALIDATION_MISSING: FailureCategory.TOOL_MISUSE,
    RootCauseType.EDGE_CASE_UNHANDLED: FailureCategory.RESOLUTION_FAILURE,
    RootCauseType.SERVICE_UNAVAILABLE: FailureCategory.DELIVERY_FAILURE,
}


# Totality checks — fail LOUDLY at import time, not silently at measurement
# time.  A new RootCauseType or production category must extend the maps.
_missing_root_causes = [rc for rc in RootCauseType if rc not in ROOT_CAUSE_PROJECTION]
if _missing_root_causes:  # pragma: no cover - guarded by tests
    raise RuntimeError(
        f"ROOT_CAUSE_PROJECTION is not total; missing {_missing_root_causes}. "
        f"Extend the projection (taxonomy version {TAXONOMY_VERSION})."
    )
_missing_production = [c for c in PRODUCTION_CATEGORIES if c not in PRODUCTION_CATEGORY_PROJECTION]
if _missing_production:  # pragma: no cover - guarded by tests
    raise RuntimeError(
        f"PRODUCTION_CATEGORY_PROJECTION is not total; missing {_missing_production}. "
        f"Extend the projection (taxonomy version {TAXONOMY_VERSION})."
    )


def project_production_category(category: str) -> FailureCategory:
    """Project a production failure category onto the shared taxonomy.

    Raises KeyError for unknown categories — an unknown production category
    means the ground-truth builder and the projection have diverged, which
    must never pass silently.
    """
    return PRODUCTION_CATEGORY_PROJECTION[category]


def project_root_cause(root_cause: RootCauseType | str) -> FailureCategory:
    """Project a Phase D root cause onto the shared taxonomy."""
    if isinstance(root_cause, str):
        root_cause = RootCauseType(root_cause)
    return ROOT_CAUSE_PROJECTION[root_cause]


def project_diagnosis_report(diagnosis_report: dict) -> List[dict]:
    """Convert a Phase D diagnosis report into shared-taxonomy synthetic
    failures suitable for :func:`compute_predictive_validity`.

    Each failure cluster yields one synthetic-failure dict with:
      ``failure_category`` (shared taxonomy value), ``tool_involved`` (when
      the cluster names one), ``cluster_id``, ``root_cause`` and
      ``frequency`` for provenance.
    """
    failures: List[dict] = []
    for cluster in diagnosis_report.get("clusters", []) or []:
        root_cause = (
            cluster.get("root_cause", {}).get("root_cause_type")
            if isinstance(cluster.get("root_cause"), dict)
            else cluster.get("root_cause_type") or cluster.get("root_cause")
        )
        if not root_cause:
            continue
        try:
            category = project_root_cause(root_cause)
        except ValueError:
            # Unknown/free-text root cause: skip rather than guess.
            continue
        affected = cluster.get("affected_tools") or []
        tool: Optional[str] = (
            cluster.get("tool_involved")
            or cluster.get("primary_tool")
            or (affected[0] if affected else None)
        )
        failures.append({
            "failure_category": category.value,
            "tool_involved": tool,
            "cluster_id": cluster.get("cluster_id"),
            "root_cause": str(root_cause),
            "frequency": cluster.get("failure_count", cluster.get("frequency", 1)),
            "source": "phase_d",
        })
    return failures


def projection_table() -> Dict[str, List[dict]]:
    """Return both projections as JSON-friendly tables (for docs/UI)."""
    return {
        "taxonomy_version": TAXONOMY_VERSION,
        "production_to_shared": [
            {"production_category": k, "shared_category": v.value}
            for k, v in PRODUCTION_CATEGORY_PROJECTION.items()
        ],
        "root_cause_to_shared": [
            {"root_cause": k.value, "shared_category": v.value}
            for k, v in ROOT_CAUSE_PROJECTION.items()
        ],
    }
