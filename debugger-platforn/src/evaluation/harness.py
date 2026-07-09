"""
Unified Suite-Quality Evaluation Harness (Sprint E12.6).

Single entry point (:func:`evaluate_suite`) that runs every measurement the
harness provides against a generated test suite:

  - fault-detection potential per failure-taxonomy category
  - APFD / severity-weighted APFD of the suite's ordering
  - behaviour-space diversity (archive coverage)
  - predictive validity vs production signals (when available)
  - mutant generation counts (mutation *score* needs Phase C execution)

Because Phase B runs before any test is executed, fault detection is
approximated statically: each test case is mapped to the set of failure
categories its scenario, persona, and chaos configuration are designed to
surface.  This gives a *potential* fault-detection matrix that APFD and
taxonomy coverage are computed over; the same mapping yields the synthetic
failures scored against production signals.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from src.evaluation.apfd import calculate_apfd, calculate_weighted_apfd
from src.evaluation.diversity import compute_suite_diversity
from src.evaluation.mutation import generate_mutants
from src.evaluation.predictive_validity import (
    ProductionSignal,
    compute_predictive_validity,
    load_production_signals,
)
from src.evaluation.taxonomy import FailureCategory, severity_weight
from src.generator.models import TestCase, TestSuite

# Categories whose faults are tool-specific (scoped per tool in fault IDs)
_TOOL_SCOPED_CATEGORIES = {
    FailureCategory.WRONG_TOOL,
    FailureCategory.MISSED_TOOL,
    FailureCategory.TOOL_MISUSE,
    FailureCategory.PII_LEAK,
    FailureCategory.EXCESSIVE_AGENCY,
}

_VARIANT_CATEGORY_MAP: Dict[str, List[FailureCategory]] = {
    "ambiguity": [FailureCategory.WRONG_TOOL, FailureCategory.HALLUCINATION],
    "missing_info": [FailureCategory.TOOL_MISUSE],
    "interruption": [FailureCategory.PREMATURE_EXIT],
    "adversarial": [FailureCategory.GUARDRAIL_VIOLATION, FailureCategory.EXCESSIVE_AGENCY],
    "error": [FailureCategory.ESCALATION_FAILURE],
    "constraint": [FailureCategory.GUARDRAIL_VIOLATION],
    "multi_step": [FailureCategory.MISSED_TOOL, FailureCategory.INFINITE_LOOP],
}


def infer_detectable_failures(test_case: TestCase) -> Set[FailureCategory]:
    """Map a test case to the failure categories it is designed to detect.

    Static approximation used before Phase C execution: derived from the
    scenario's failure/success conditions, variant type, chaos injection,
    and the persona's edge behaviors and traits.
    """
    categories: Set[FailureCategory] = set()
    scenario = test_case.scenario
    persona = test_case.persona

    # Scenario failure conditions are explicit detection targets
    fc = scenario.failure_conditions
    if fc.pii_leaked:
        categories.add(FailureCategory.PII_LEAK)
    if fc.hallucinated_response:
        categories.add(FailureCategory.HALLUCINATION)
    if fc.wrong_tool_called:
        categories.add(FailureCategory.WRONG_TOOL)

    # A required/expected tool means the test can detect the agent missing it
    sc = scenario.success_conditions
    if sc.tool_called or sc.tools_called or scenario.required_tools:
        categories.add(FailureCategory.MISSED_TOOL)

    # Forbidden tools: test detects the agent overstepping
    if scenario.forbidden_tools:
        categories.add(FailureCategory.EXCESSIVE_AGENCY)

    # Variant-type targets
    if scenario.variant_type:
        categories.update(_VARIANT_CATEGORY_MAP.get(scenario.variant_type, []))

    # Chaos injection stresses retry/escalation behaviour
    chaos = (test_case.execution_config or {}).get("chaos_injection", {})
    if isinstance(chaos, dict) and any(chaos.values()):
        categories.add(FailureCategory.INFINITE_LOOP)
        categories.add(FailureCategory.ESCALATION_FAILURE)

    # Persona edge behaviors
    eb = persona.edge_behaviors
    if eb.tests_boundaries:
        categories.add(FailureCategory.GUARDRAIL_VIOLATION)
    if eb.rage_quits:
        categories.add(FailureCategory.PREMATURE_EXIT)
    if eb.provides_incomplete_info:
        categories.add(FailureCategory.TOOL_MISUSE)
    if eb.asks_off_topic:
        categories.add(FailureCategory.STYLE_VIOLATION)

    # Persona traits/style
    if persona.traits.language_proficiency <= 3:
        categories.add(FailureCategory.LANGUAGE_ERROR)
    if persona.style.tone in ("frustrated", "angry"):
        categories.add(FailureCategory.STYLE_VIOLATION)
        categories.add(FailureCategory.ESCALATION_FAILURE)

    return categories


def _test_tools(test_case: TestCase) -> Set[str]:
    tools: Set[str] = set(test_case.scenario.required_tools)
    if test_case.target_tool:
        tools.update(test_case.target_tool.split("+"))
    return tools


def build_fault_matrix(test_suite: TestSuite) -> Dict[str, Set[str]]:
    """Build the potential fault-detection matrix: test_id -> fault IDs.

    Fault IDs are ``category`` for global categories and ``category@tool``
    for tool-scoped categories, so two tests targeting the same failure mode
    on different tools count as detecting different faults.
    """
    matrix: Dict[str, Set[str]] = {}
    for tc in test_suite.test_cases:
        faults: Set[str] = set()
        tools = sorted(_test_tools(tc))
        for category in infer_detectable_failures(tc):
            if category in _TOOL_SCOPED_CATEGORIES and tools:
                faults.update(f"{category.value}@{tool}" for tool in tools)
            else:
                faults.add(category.value)
        matrix[tc.test_id] = faults
    return matrix


def _fault_weights(fault_matrix: Dict[str, Set[str]]) -> Dict[str, float]:
    """Severity weight per fault ID (fault ID prefix is the category)."""
    weights: Dict[str, float] = {}
    for faults in fault_matrix.values():
        for fault in faults:
            category = FailureCategory(fault.split("@")[0])
            weights[fault] = float(severity_weight(category))
    return weights


def synthetic_failures_from_suite(test_suite: TestSuite) -> List[Dict[str, Any]]:
    """Deduplicated (failure_category, tool_involved) signatures the suite
    can surface, in the shape ``compute_predictive_validity`` expects."""
    seen: Set[tuple] = set()
    failures: List[Dict[str, Any]] = []
    for tc in test_suite.test_cases:
        tools = sorted(_test_tools(tc)) or [None]
        for category in infer_detectable_failures(tc):
            scoped_tools = tools if category in _TOOL_SCOPED_CATEGORIES else [None]
            for tool in scoped_tools:
                key = (category.value, tool)
                if key in seen:
                    continue
                seen.add(key)
                failures.append({
                    "failure_category": category.value,
                    "tool_involved": tool,
                    "guardrail_rule_id": None,
                    "example_test_id": tc.test_id,
                })
    return failures


def evaluate_suite(
    test_suite: TestSuite,
    agent_map: Dict[str, Any],
    production_signals: Optional[List[ProductionSignal]] = None,
    trace_result: Any = None,
) -> Dict[str, Any]:
    """Run the full measurement harness against a test suite.

    Args:
        test_suite: the generated TestSuite (B4 output).
        agent_map: the Phase A agent map the suite was generated from.
        production_signals: independently sourced production failures; when
            omitted, signals are derived from *trace_result* (or the agent
            map's embedded ``trace_analysis``) if present.
        trace_result: Phase A trace analysis (object or dict).

    Returns:
        comprehensive quality report (JSON-serialisable dict).
    """
    test_order = [tc.test_id for tc in sorted(test_suite.test_cases, key=lambda t: t.test_number)]
    fault_matrix = build_fault_matrix(test_suite)
    weights = _fault_weights(fault_matrix)
    all_faults = {f for faults in fault_matrix.values() for f in faults}

    # Taxonomy coverage: which failure categories can the suite surface at all
    categories_covered = sorted({f.split("@")[0] for f in all_faults})
    categories_missing = sorted(
        c.value for c in FailureCategory if c.value not in categories_covered
    )

    apfd_section = {
        "apfd": round(calculate_apfd(test_order, fault_matrix), 4),
        "weighted_apfd": round(calculate_weighted_apfd(test_order, fault_matrix, weights), 4),
        "n_tests": len(test_order),
        "n_potential_faults": len(all_faults),
        "note": "Computed over the static potential-fault matrix (pre-execution).",
    }

    diversity_section = compute_suite_diversity(test_suite, agent_map)

    # Predictive validity (only when production evidence is available)
    if production_signals is None:
        if trace_result is None:
            trace_result = agent_map.get("trace_analysis")
        if trace_result is not None:
            production_signals = load_production_signals(trace_result, agent_map)

    if production_signals:
        synthetic_failures = synthetic_failures_from_suite(test_suite)
        predictive_section: Optional[Dict[str, Any]] = compute_predictive_validity(
            synthetic_failures, production_signals
        )
    else:
        predictive_section = None

    # Mutation: generate mutants; the score itself needs Phase C execution
    mutants = generate_mutants(agent_map)
    by_operator: Dict[str, int] = {}
    for m in mutants:
        by_operator[m["operator"]] = by_operator.get(m["operator"], 0) + 1
    mutation_section = {
        "total_mutants": len(mutants),
        "by_operator": by_operator,
        "mutation_score": None,
        "note": "Mutation score requires executing the suite against each mutant (Phase C).",
    }

    return {
        "suite": {
            "test_suite_id": test_suite.test_suite_id,
            "agent_id": test_suite.agent_id,
            "total_tests": test_suite.summary.total_tests,
        },
        "apfd": apfd_section,
        "diversity": diversity_section,
        "taxonomy_coverage": {
            "categories_covered": categories_covered,
            "categories_missing": categories_missing,
            "coverage": round(len(categories_covered) / len(FailureCategory), 4),
        },
        "predictive_validity": predictive_section,
        "mutation": mutation_section,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
