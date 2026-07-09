"""
Sprint E8: APFD-weighted prioritisation tests.

Verify the fault-proneness estimator, the greedy APFD-maximising ordering
(including that it beats the pre-refactor arbitrary order on APFD), the
tier-preservation contract (seed -> coverage -> fill survives a budget cut),
and that the refactored TestSuiteGenerator keeps its public contract.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.evaluation.apfd import calculate_apfd
from src.evaluation.harness import build_fault_matrix
from src.generator.models import TestCase, TestSuite, TestSuiteSummary
from src.generator.prioritiser import (
    estimate_fault_proneness,
    prioritise_suite,
)
from src.personas.models import (
    Persona,
    PersonaEdgeBehaviors,
    PersonaStyle,
    PersonaTraits,
)
from src.scenarios.models import (
    Scenario,
    ScenarioFailureConditions,
    ScenarioSuccessConditions,
)

NOW = datetime.now(timezone.utc)

AGENT_MAP = {
    "agent_id": "test-agent",
    "components": {
        "tools": [
            {"name": "refund", "risk_level": "critical"},
            {"name": "lookup_order", "risk_level": "low"},
            {"name": "escalate", "risk_level": "high"},
            {"name": "send_email", "risk_level": "medium"},
        ]
    },
}


def _persona(name="p", source="template", boundaries=False, rage=False, incomplete=False):
    return Persona(
        persona_id=f"persona-{name}",
        name=name,
        agent_type="support",
        source=source,
        traits=PersonaTraits(
            patience=5, clarity=5, tech_savviness=5, politeness=5, verbosity=5,
            language_proficiency=8,
        ),
        style=PersonaStyle(tone="neutral", formality="casual", typo_rate=0.0),
        edge_behaviors=PersonaEdgeBehaviors(
            tests_boundaries=boundaries, rage_quits=rage,
            provides_incomplete_info=incomplete,
        ),
        created_at=NOW,
    )


def _scenario(sid, tools, variant=None, source="template",
              pii=False, wrong_tool=False, forbidden=None):
    return Scenario(
        scenario_id=sid,
        title=sid,
        description="d",
        user_goal="g",
        category="support",
        required_tools=tools,
        forbidden_tools=forbidden or [],
        variant_type=variant,
        source=source,
        success_conditions=ScenarioSuccessConditions(),
        failure_conditions=ScenarioFailureConditions(
            pii_leaked=pii, wrong_tool_called=wrong_tool,
        ),
        created_at=NOW,
    )


def _tc(num, scenario, persona, coverage_goal="scenario_coverage", target_tool=None,
        oracles=None):
    return TestCase(
        test_id=f"tc-{num}",
        test_number=num,
        scenario=scenario,
        persona=persona,
        execution_config={},
        coverage_goal=coverage_goal,
        target_tool=target_tool,
        difficulty="medium",
        oracles=oracles or [],
    )


# ----------------------------------------------------------------------
# E8.1 Fault-proneness estimator
# ----------------------------------------------------------------------

def test_risk_weight_orders_by_tool_risk():
    critical = _tc(1, _scenario("s1", ["refund"]), _persona())
    low = _tc(2, _scenario("s2", ["lookup_order"]), _persona())
    assert estimate_fault_proneness(critical, AGENT_MAP) > estimate_fault_proneness(low, AGENT_MAP)


def test_failure_history_boost_doubles_score():
    tc = _tc(1, _scenario("s1", ["refund"]), _persona())
    trace = {"failure_patterns": [{"sequence": ["refund"]}]}
    boosted = estimate_fault_proneness(tc, AGENT_MAP, trace)
    plain = estimate_fault_proneness(tc, AGENT_MAP)
    assert boosted == plain * 2.0


def test_inverse_trace_frequency_favours_rare_tools():
    rare = _tc(1, _scenario("s1", ["refund"]), _persona())
    common = _tc(2, _scenario("s2", ["escalate"]), _persona())
    # Give both tools the SAME risk so only frequency differs.
    amap = {
        "components": {"tools": [
            {"name": "refund", "risk_level": "high"},
            {"name": "escalate", "risk_level": "high"},
        ]}
    }
    trace = {"tool_frequency": {"refund": 1, "escalate": 500}}
    assert estimate_fault_proneness(rare, amap, trace) > estimate_fault_proneness(common, amap, trace)


def test_oracle_density_increases_score():
    with_oracles = _tc(1, _scenario("s1", ["lookup_order"]), _persona(),
                       oracles=[{"type": "postcondition"}, {"type": "taint"}])
    without = _tc(2, _scenario("s2", ["lookup_order"]), _persona())
    assert estimate_fault_proneness(with_oracles, AGENT_MAP) > estimate_fault_proneness(without, AGENT_MAP)


# ----------------------------------------------------------------------
# E8.2 Greedy APFD-maximising ordering
# ----------------------------------------------------------------------

def _diverse_suite():
    """Tests that each surface distinct faults, in a deliberately bad order."""
    return [
        _tc(1, _scenario("dup1", ["lookup_order"]), _persona()),
        _tc(2, _scenario("dup2", ["lookup_order"]), _persona()),
        _tc(3, _scenario("pii", ["refund"], pii=True), _persona(), target_tool="refund"),
        _tc(4, _scenario("adv", ["escalate"], variant="adversarial"),
            _persona(boundaries=True), target_tool="escalate"),
        _tc(5, _scenario("wrong", ["send_email"], wrong_tool=True),
            _persona(rage=True), target_tool="send_email"),
    ]


def test_prioritise_beats_original_apfd():
    cases = _diverse_suite()
    original_order = [tc.test_id for tc in cases]
    ordered = prioritise_suite(cases, AGENT_MAP, preserve_priority=False)
    new_order = [tc.test_id for tc in ordered]

    suite = TestSuite(
        test_suite_id="x", agent_id="a", test_cases=cases,
        summary=TestSuiteSummary(total_tests=len(cases)), created_at=NOW,
    )
    fm = build_fault_matrix(suite)
    assert calculate_apfd(new_order, fm) >= calculate_apfd(original_order, fm)


def test_prioritise_is_deterministic():
    cases = _diverse_suite()
    a = [tc.test_id for tc in prioritise_suite(cases, AGENT_MAP)]
    b = [tc.test_id for tc in prioritise_suite(cases, AGENT_MAP)]
    assert a == b


def test_prioritise_returns_all_and_only_inputs():
    cases = _diverse_suite()
    ordered = prioritise_suite(cases, AGENT_MAP)
    assert {tc.test_id for tc in ordered} == {tc.test_id for tc in cases}
    assert len(ordered) == len(cases)


def test_empty_input():
    assert prioritise_suite([], AGENT_MAP) == []


# ----------------------------------------------------------------------
# Tier preservation (Sprint E1/E3/E5 contract)
# ----------------------------------------------------------------------

def test_seed_and_coverage_tiers_ordered_first():
    seed = _tc(1, _scenario("seed", ["lookup_order"], source="production_seed"),
               _persona(source="production_seed"), coverage_goal="production_seed")
    coverage = _tc(2, _scenario("cov", ["refund"]), _persona(),
                   coverage_goal="interaction_coverage", target_tool="refund")
    adv = _tc(3, _scenario("adv", ["escalate"]), _persona(boundaries=True),
              coverage_goal="adversarial:LLM01", target_tool="escalate")
    fills = [_tc(10 + i, _scenario(f"f{i}", ["lookup_order"]), _persona(),
                 coverage_goal="scenario_coverage") for i in range(20)]

    ordered = prioritise_suite([*fills, adv, coverage, seed], AGENT_MAP)
    goals = [tc.coverage_goal for tc in ordered]

    # Seed first, coverage-forced / adversarial before any fill.
    assert goals[0] == "production_seed"
    first_fill = goals.index("scenario_coverage")
    assert goals.index("interaction_coverage") < first_fill
    assert goals.index("adversarial:LLM01") < first_fill


def test_priority_tests_survive_budget_cut():
    seed = _tc(1, _scenario("seed", ["lookup_order"], source="production_seed"),
               _persona(source="production_seed"), coverage_goal="production_seed")
    coverage = _tc(2, _scenario("cov", ["refund"]), _persona(),
                   coverage_goal="transition_coverage", target_tool="refund")
    fills = [_tc(10 + i, _scenario(f"f{i}", ["lookup_order"]), _persona(),
                 coverage_goal="scenario_coverage") for i in range(20)]

    ordered = prioritise_suite([*fills, coverage, seed], AGENT_MAP)
    kept = ordered[:3]  # simulate a tight budget cut
    kept_goals = {tc.coverage_goal for tc in kept}
    assert "production_seed" in kept_goals
    assert "transition_coverage" in kept_goals


# ----------------------------------------------------------------------
# Backward compatibility of the refactored generator
# ----------------------------------------------------------------------

def test_generator_public_contract_preserved():
    from src.coverage.calculator import build_test_configuration
    from src.generator.test_suite import TestSuiteGenerator

    config = build_test_configuration(AGENT_MAP)
    scenarios = [
        _scenario("s1", ["refund"], pii=True),
        _scenario("s2", ["lookup_order"]),
        _scenario("s3", ["escalate"], variant="adversarial"),
    ]
    personas = [_persona("a"), _persona("b", boundaries=True)]

    gen = TestSuiteGenerator(
        agent_map=AGENT_MAP,
        personas=personas,
        scenarios=scenarios,
        coverage_goals=config.coverage_goals,
        sandbox_config=config.sandbox_config,
    )
    suite = gen.generate(target_count=15)

    assert isinstance(suite, TestSuite)
    assert suite.summary.total_tests == len(suite.test_cases)
    assert len(suite.test_cases) <= 15
    # Numbered 1..n in prioritised order.
    assert [tc.test_number for tc in suite.test_cases] == list(range(1, len(suite.test_cases) + 1))
