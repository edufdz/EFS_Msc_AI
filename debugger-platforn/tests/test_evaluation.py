"""
Tests for the Suite-Quality Measurement Harness (Sprint E12).

Covers: failure taxonomy, APFD calculator, predictive validity,
behaviour-space diversity, mutation operators, the unified harness,
and the generate_tests.py --evaluate CLI flag.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.evaluation.apfd import calculate_apfd, calculate_weighted_apfd, compare_orderings
from src.evaluation.diversity import compute_suite_diversity
from src.evaluation.harness import (
    build_fault_matrix,
    evaluate_suite,
    infer_detectable_failures,
    synthetic_failures_from_suite,
)
from src.evaluation.mutation import MutationOperator, compute_mutation_score, generate_mutants
from src.evaluation.predictive_validity import (
    ProductionSignal,
    compute_predictive_validity,
    load_production_signals,
)
from src.evaluation.taxonomy import (
    CATEGORY_SEVERITY,
    CATEGORY_TAXONOMY_IDS,
    SEVERITY_WEIGHTS,
    FailureCategory,
    severity_weight,
)
# Aliased so pytest does not try to collect the pydantic models as test classes
from src.generator.models import TestCase as SuiteTestCase
from src.generator.models import TestSuite as SuiteModel
from src.generator.models import TestSuiteSummary as SuiteSummary
from src.personas.models import Persona, PersonaEdgeBehaviors, PersonaStyle, PersonaTraits
from src.scenarios.models import (
    Scenario,
    ScenarioFailureConditions,
    ScenarioSuccessConditions,
)


# ---------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------

def _agent_map() -> dict:
    return {
        "metadata": {
            "type": "support",
            "purpose": "Help users with account issues",
            "conversation_language": "English",
        },
        "components": {
            "tools": [
                {
                    "name": "lookup_account",
                    "description": "Look up a user account by ID",
                    "risk_level": "low",
                    "read_only": True,
                    "parameters": [{"name": "account_id", "type": "string"}],
                },
                {
                    "name": "reset_password",
                    "description": "Reset a user password",
                    "risk_level": "high",
                    "parameters": [{"name": "account_id", "type": "string"}],
                    "preconditions": ["user identity confirmed"],
                },
                {
                    "name": "escalate_to_human",
                    "description": "Escalate the conversation to a human agent",
                    "risk_level": "medium",
                    "parameters": [],
                },
            ],
            "prompts": [],
        },
        "guardrails": {
            "rules": [
                {"rule_id": "R001", "text": "Never reveal customer PII", "category": "privacy",
                 "scope": "global", "target_tools": [], "conditions": []},
                {"rule_id": "R002", "text": "Always confirm before resetting a password",
                 "category": "confirmation", "scope": "tool",
                 "target_tools": ["reset_password"], "conditions": ["user confirms"]},
            ],
            "total_rules": 2,
        },
        "risk_flags": {"all_risks": []},
        "trace_analysis": {
            "failure_patterns": [
                {"sequence": ["lookup_account", "lookup_account"], "count": 12, "failure_rate": 0.8},
                {"sequence": ["reset_password"], "count": 5, "failure_rate": 0.6},
            ],
            "tool_frequency": {"lookup_account": 40, "reset_password": 10},
            "conversations": [
                {"trace_id": "tr_1", "outcome": "escalation", "tool_calls": ["lookup_account", "escalate_to_human"]},
                {"trace_id": "tr_2", "outcome": "success", "tool_calls": ["lookup_account"]},
            ],
        },
    }


def _persona(
    persona_id: str = "p1",
    *,
    politeness: int = 8,
    patience: int = 8,
    clarity: int = 8,
    language_proficiency: int = 8,
    tone: str = "neutral",
    tests_boundaries: bool = False,
    rage_quits: bool = False,
) -> Persona:
    return Persona(
        persona_id=persona_id,
        name=f"Persona {persona_id}",
        agent_type="support",
        source="template",
        traits=PersonaTraits(
            patience=patience, clarity=clarity, tech_savviness=5,
            politeness=politeness, verbosity=5,
            language_proficiency=language_proficiency,
        ),
        style=PersonaStyle(tone=tone, formality="casual", typo_rate=0.1),
        edge_behaviors=PersonaEdgeBehaviors(
            tests_boundaries=tests_boundaries, rage_quits=rage_quits,
        ),
        created_at=datetime.now(timezone.utc),
    )


def _scenario(
    scenario_id: str = "s1",
    *,
    scenario_type: str = "happy_path",
    variant_type: str | None = None,
    required_tools: list[str] | None = None,
    forbidden_tools: list[str] | None = None,
    pii_leaked: bool = False,
) -> Scenario:
    return Scenario(
        scenario_id=scenario_id,
        title=f"Scenario {scenario_id}",
        description="A test scenario",
        user_goal="Get help with my account",
        category="support",
        type=scenario_type,
        variant_type=variant_type,
        required_tools=required_tools or [],
        forbidden_tools=forbidden_tools or [],
        success_conditions=ScenarioSuccessConditions(),
        failure_conditions=ScenarioFailureConditions(pii_leaked=pii_leaked),
        created_at=datetime.now(timezone.utc),
    )


def _test_case(test_id: str, number: int, scenario: Scenario, persona: Persona,
               target_tool: str | None = None, chaos: bool = False) -> SuiteTestCase:
    return SuiteTestCase(
        test_id=test_id,
        test_number=number,
        scenario=scenario,
        persona=persona,
        execution_config={
            "max_turns": 20,
            "chaos_injection": {"timeout": chaos, "malformed_response": False, "data_conflict": False},
        },
        coverage_goal="tool_coverage",
        target_tool=target_tool,
        difficulty="medium",
    )


def _suite(test_cases: list[SuiteTestCase]) -> SuiteModel:
    return SuiteModel(
        test_suite_id="suite-1",
        agent_id="agent-1",
        test_cases=test_cases,
        summary=SuiteSummary(total_tests=len(test_cases)),
        created_at=datetime.now(timezone.utc),
    )


def _sample_suite() -> SuiteModel:
    p_polite = _persona("p1")
    p_attacker = _persona("p2", politeness=2, patience=2, tests_boundaries=True, tone="angry")
    p_novice = _persona("p3", clarity=2, language_proficiency=2)
    s_happy = _scenario("s1", required_tools=["lookup_account", "reset_password"])
    s_adv = _scenario("s2", scenario_type="edge_case", variant_type="adversarial",
                      required_tools=["reset_password"], forbidden_tools=["escalate_to_human"],
                      pii_leaked=True)
    s_err = _scenario("s3", scenario_type="error_path", required_tools=["lookup_account"])
    return _suite([
        _test_case("t1", 1, s_happy, p_polite),
        _test_case("t2", 2, s_adv, p_attacker),
        _test_case("t3", 3, s_err, p_novice, target_tool="lookup_account", chaos=True),
        _test_case("t4", 4, s_happy, p_attacker),
    ])


# ---------------------------------------------------------------
# E12.1 — Taxonomy
# ---------------------------------------------------------------

class TestTaxonomy:
    def test_all_categories_have_taxonomy_ids(self):
        for category in FailureCategory:
            ids = CATEGORY_TAXONOMY_IDS[category]
            assert ids, f"{category} has no taxonomy IDs"
            for tid in ids:
                assert tid.startswith(("LLM", "ASI")), f"unexpected taxonomy ID {tid}"

    def test_all_categories_have_severity(self):
        for category in FailureCategory:
            assert CATEGORY_SEVERITY[category] in SEVERITY_WEIGHTS

    def test_severity_weights(self):
        assert SEVERITY_WEIGHTS == {"critical": 4, "high": 3, "medium": 2, "low": 1}
        assert severity_weight(FailureCategory.PII_LEAK) == 4
        assert severity_weight(FailureCategory.STYLE_VIOLATION) == 1

    def test_categories_are_strings(self):
        assert FailureCategory.WRONG_TOOL == "wrong_tool"
        assert len(FailureCategory) == 12


# ---------------------------------------------------------------
# E12.2 — APFD
# ---------------------------------------------------------------

class TestAPFD:
    def test_apfd_known_value(self):
        # 5 tests, 2 faults; f1 first detected at position 1, f2 at position 3:
        # APFD = 1 - (1+3)/(5*2) + 1/(2*5) = 0.7
        order = ["t1", "t2", "t3", "t4", "t5"]
        matrix = {"t1": {"f1"}, "t3": {"f2"}}
        assert calculate_apfd(order, matrix) == pytest.approx(0.7)

    def test_apfd_perfect_first_test(self):
        # Every fault detected by the first test: APFD = 1 - n/(n*m*?) ...
        # n=2 tests, m=1 fault at position 1: 1 - 1/2 + 1/4 = 0.75
        assert calculate_apfd(["t1", "t2"], {"t1": {"f1"}}) == pytest.approx(0.75)

    def test_apfd_undetected_fault_penalised(self):
        # f3 never detected by any test in the ordering -> position n+1 = 6
        # APFD = 1 - (1+3+6)/(5*3) + 0.1 = 0.4333...
        order = ["t1", "t2", "t3", "t4", "t5"]
        matrix = {"t1": {"f1"}, "t3": {"f2"}, "t99": {"f3"}}
        assert calculate_apfd(order, matrix) == pytest.approx(1 - 10 / 15 + 0.1)

    def test_apfd_empty(self):
        assert calculate_apfd([], {}) == 0.0
        assert calculate_apfd(["t1"], {}) == 0.0

    def test_weighted_apfd_uniform_equals_unweighted(self):
        order = ["t1", "t2", "t3", "t4", "t5"]
        matrix = {"t1": {"f1"}, "t3": {"f2"}}
        weights = {"f1": 1.0, "f2": 1.0}
        assert calculate_weighted_apfd(order, matrix, weights) == pytest.approx(
            calculate_apfd(order, matrix)
        )

    def test_weighted_apfd_rewards_early_critical(self):
        order = ["t1", "t2", "t3", "t4", "t5"]
        matrix = {"t1": {"f1"}, "t3": {"f2"}}
        early_critical = calculate_weighted_apfd(order, matrix, {"f1": 4.0, "f2": 1.0})
        late_critical = calculate_weighted_apfd(order, matrix, {"f1": 1.0, "f2": 4.0})
        assert early_critical > late_critical

    def test_compare_orderings(self):
        matrix = {"t1": {"f1"}, "t3": {"f2"}}
        forward = ["t1", "t2", "t3", "t4", "t5"]
        backward = list(reversed(forward))
        result = compare_orderings(forward, backward, matrix)
        assert result["apfd_a"] == pytest.approx(0.7)
        assert result["winner"] == "a"
        assert result["delta"] == pytest.approx(result["apfd_a"] - result["apfd_b"])

    def test_compare_orderings_tie(self):
        matrix = {"t1": {"f1"}, "t2": {"f1"}}
        result = compare_orderings(["t1", "t2"], ["t2", "t1"], matrix)
        assert result["winner"] == "tie"


# ---------------------------------------------------------------
# E12.3 — Predictive validity
# ---------------------------------------------------------------

class TestPredictiveValidity:
    def _signal(self, signal_id: str, category: FailureCategory,
                tool: str | None = None, rule: str | None = None) -> ProductionSignal:
        return ProductionSignal(
            signal_id=signal_id,
            trace_id=f"trace_{signal_id}",
            failure_category=category,
            description="test signal",
            tool_involved=tool,
            guardrail_rule_id=rule,
            source="qa_flag",
        )

    def test_precision_recall(self):
        signals = [
            self._signal("sig1", FailureCategory.PII_LEAK, tool="lookup_account"),
            self._signal("sig2", FailureCategory.WRONG_TOOL, tool="reset_password"),
        ]
        synthetic = [
            {"failure_category": "pii_leak", "tool_involved": "lookup_account"},   # matches sig1
            {"failure_category": "hallucination", "tool_involved": None},          # false positive
        ]
        result = compute_predictive_validity(synthetic, signals)
        assert result["precision"] == pytest.approx(0.5)
        assert result["recall"] == pytest.approx(0.5)
        assert result["f1"] == pytest.approx(0.5)
        assert result["matched_signals"] == ["sig1"]
        assert result["unmatched_signals"] == ["sig2"]
        assert len(result["false_positives"]) == 1

    def test_match_by_guardrail_rule(self):
        signals = [self._signal("sig1", FailureCategory.GUARDRAIL_VIOLATION, rule="R002")]
        synthetic = [{"failure_category": "guardrail_violation", "guardrail_rule_id": "R002"}]
        result = compute_predictive_validity(synthetic, signals)
        assert result["recall"] == 1.0

    def test_category_only_signal_matches_on_category(self):
        signals = [self._signal("sig1", FailureCategory.HALLUCINATION)]
        synthetic = [{"failure_category": "hallucination"}]
        assert compute_predictive_validity(synthetic, signals)["recall"] == 1.0

    def test_category_mismatch_never_matches(self):
        signals = [self._signal("sig1", FailureCategory.PII_LEAK, tool="lookup_account")]
        synthetic = [{"failure_category": "wrong_tool", "tool_involved": "lookup_account"}]
        result = compute_predictive_validity(synthetic, signals)
        assert result["precision"] == 0.0
        assert result["recall"] == 0.0

    def test_empty_inputs(self):
        result = compute_predictive_validity([], [])
        assert result["precision"] == 0.0
        assert result["recall"] == 0.0
        assert result["f1"] == 0.0

    def test_load_production_signals(self):
        agent_map = _agent_map()
        signals = load_production_signals(agent_map["trace_analysis"], agent_map)

        # 2 failure patterns + 1 escalated conversation
        assert len(signals) == 3
        by_source = {s.source for s in signals}
        assert by_source == {"qa_flag", "escalation"}

        # Repeated tool -> infinite loop
        loop_signals = [s for s in signals if s.failure_category == FailureCategory.INFINITE_LOOP]
        assert len(loop_signals) == 1
        assert loop_signals[0].tool_involved == "lookup_account"

        # reset_password pattern picks up its guardrail rule
        rp = [s for s in signals if s.tool_involved == "reset_password"]
        assert rp and rp[0].guardrail_rule_id == "R002"

        # Escalated conversation -> escalation signal
        esc = [s for s in signals if s.source == "escalation"]
        assert esc and esc[0].failure_category == FailureCategory.ESCALATION_FAILURE

    def test_load_production_signals_none(self):
        assert load_production_signals(None, _agent_map()) == []


# ---------------------------------------------------------------
# E12.4 — Diversity
# ---------------------------------------------------------------

class TestDiversity:
    def test_diversity_report_shape(self):
        report = compute_suite_diversity(_sample_suite(), _agent_map())
        for key in ("trait_coverage", "scenario_coverage", "tool_pair_coverage",
                    "archetype_coverage", "overall_diversity"):
            assert 0.0 <= report[key] <= 1.0, key

    def test_trait_cells(self):
        report = compute_suite_diversity(_sample_suite(), _agent_map())
        # 3 distinct personas -> up to 3 distinct trait cells out of 3^10
        assert report["trait_cells_total"] == 3 ** 10
        assert 1 <= report["trait_cells_filled"] <= 3
        assert report["trait_coverage"] == pytest.approx(
            report["trait_cells_filled"] / 3 ** 10, abs=1e-6
        )

    def test_tool_pair_coverage_uses_agent_map_universe(self):
        # Agent has 3 tools -> 3 possible pairs; s1 exercises the
        # (lookup_account, reset_password) pair only
        report = compute_suite_diversity(_sample_suite(), _agent_map())
        assert report["tool_pairs_total"] == 3
        assert report["tool_pairs_exercised"] == 1
        assert report["tool_pair_coverage"] == pytest.approx(1 / 3, abs=1e-4)

    def test_archetype_coverage(self):
        report = compute_suite_diversity(_sample_suite(), _agent_map())
        # p1=ideal_customer, p2=adversarial, p3=confused_novice -> 3/6
        assert report["archetype_coverage"] == pytest.approx(0.5)
        assert "adversarial" in report["archetypes_used"]

    def test_single_tool_agent_pair_coverage_trivially_full(self):
        agent_map = _agent_map()
        agent_map["components"]["tools"] = agent_map["components"]["tools"][:1]
        report = compute_suite_diversity(_sample_suite(), agent_map)
        assert report["tool_pair_coverage"] == 1.0


# ---------------------------------------------------------------
# E12.5 — Mutation
# ---------------------------------------------------------------

class TestMutation:
    def test_generate_mutants_all_operators(self):
        agent_map = _agent_map()
        mutants = generate_mutants(agent_map)
        operators = {m["operator"] for m in mutants}
        assert operators == {op.value for op in MutationOperator}

    def test_mutants_have_required_fields_and_unique_ids(self):
        mutants = generate_mutants(_agent_map())
        ids = [m["mutant_id"] for m in mutants]
        assert len(set(ids)) == len(ids)
        for m in mutants:
            assert m["description"]
            assert isinstance(m["modified_agent_map"], dict)

    def test_original_agent_map_not_modified(self):
        agent_map = _agent_map()
        before = copy.deepcopy(agent_map)
        generate_mutants(agent_map)
        assert agent_map == before

    def test_remove_guardrail_mutant(self):
        mutants = [m for m in generate_mutants(_agent_map(), [MutationOperator.REMOVE_GUARDRAIL])]
        assert len(mutants) == 2  # one per rule
        for m in mutants:
            assert len(m["modified_agent_map"]["guardrails"]["rules"]) == 1

    def test_swap_tool_mutant(self):
        mutants = generate_mutants(_agent_map(), [MutationOperator.SWAP_TOOL])
        assert len(mutants) == 2  # adjacent pairs among 3 tools
        first = mutants[0]["modified_agent_map"]["components"]["tools"]
        assert first[0]["name"] == "reset_password"
        assert first[1]["name"] == "lookup_account"

    def test_remove_escalation_mutant(self):
        mutants = generate_mutants(_agent_map(), [MutationOperator.REMOVE_ESCALATION])
        assert len(mutants) == 1
        tool_names = [t["name"] for t in mutants[0]["modified_agent_map"]["components"]["tools"]]
        assert "escalate_to_human" not in tool_names

    def test_wrong_language_mutant(self):
        mutants = generate_mutants(_agent_map(), [MutationOperator.WRONG_LANGUAGE])
        assert len(mutants) == 1
        assert mutants[0]["modified_agent_map"]["metadata"]["conversation_language"] == "Spanish"

    def test_remove_confirmation_mutant(self):
        mutants = generate_mutants(_agent_map(), [MutationOperator.REMOVE_CONFIRMATION])
        # one for the tool precondition, one for the R002 guardrail
        assert len(mutants) == 2
        precond_mutant = mutants[0]["modified_agent_map"]
        reset_tool = precond_mutant["components"]["tools"][1]
        assert reset_tool["preconditions"] == []

    def test_truncate_context_mutant(self):
        mutants = generate_mutants(_agent_map(), [MutationOperator.TRUNCATE_CONTEXT])
        assert len(mutants) == 1
        assert mutants[0]["modified_agent_map"]["success_criteria"]["max_turns"] == 3

    def test_compute_mutation_score(self):
        mutants = generate_mutants(_agent_map(), [MutationOperator.WRONG_LANGUAGE,
                                                  MutationOperator.TRUNCATE_CONTEXT])
        m1, m2 = mutants[0]["mutant_id"], mutants[1]["mutant_id"]
        execution_results = {
            "original": {"t1": "pass", "t2": "pass"},
            m1: {"t1": "fail", "t2": "pass"},   # killed (t1 outcome differs)
            m2: {"t1": "pass", "t2": "pass"},   # survived
        }
        assert compute_mutation_score(None, mutants, execution_results) == pytest.approx(0.5)

    def test_compute_mutation_score_bool_results(self):
        mutants = generate_mutants(_agent_map(), [MutationOperator.WRONG_LANGUAGE])
        results = {mutants[0]["mutant_id"]: True}
        assert compute_mutation_score(None, mutants, results) == 1.0

    def test_compute_mutation_score_no_mutants(self):
        assert compute_mutation_score(None, [], {}) == 0.0


# ---------------------------------------------------------------
# E12.6 — Harness
# ---------------------------------------------------------------

class TestHarness:
    def test_infer_detectable_failures(self):
        suite = _sample_suite()
        # t2: adversarial variant + pii_leaked + forbidden tools + boundary-testing persona
        t2 = next(tc for tc in suite.test_cases if tc.test_id == "t2")
        cats = infer_detectable_failures(t2)
        assert FailureCategory.PII_LEAK in cats
        assert FailureCategory.GUARDRAIL_VIOLATION in cats
        assert FailureCategory.EXCESSIVE_AGENCY in cats

        # t3: chaos-injected + low language proficiency persona
        t3 = next(tc for tc in suite.test_cases if tc.test_id == "t3")
        cats = infer_detectable_failures(t3)
        assert FailureCategory.INFINITE_LOOP in cats
        assert FailureCategory.LANGUAGE_ERROR in cats

    def test_build_fault_matrix_scopes_by_tool(self):
        matrix = build_fault_matrix(_sample_suite())
        assert set(matrix) == {"t1", "t2", "t3", "t4"}
        assert "missed_tool@lookup_account" in matrix["t1"]
        assert "missed_tool@reset_password" in matrix["t1"]

    def test_synthetic_failures_deduplicated(self):
        failures = synthetic_failures_from_suite(_sample_suite())
        signatures = [(f["failure_category"], f["tool_involved"]) for f in failures]
        assert len(signatures) == len(set(signatures))
        assert all("failure_category" in f for f in failures)

    def test_evaluate_suite_report(self):
        report = evaluate_suite(_sample_suite(), _agent_map())
        assert set(report) == {
            "suite", "apfd", "diversity", "taxonomy_coverage",
            "predictive_validity", "mutation", "generated_at",
        }
        assert 0.0 < report["apfd"]["apfd"] <= 1.0
        assert 0.0 < report["apfd"]["weighted_apfd"] <= 1.0
        assert 0.0 <= report["diversity"]["overall_diversity"] <= 1.0
        assert 0.0 < report["taxonomy_coverage"]["coverage"] <= 1.0
        # trace_analysis is embedded in the agent map -> predictive validity runs
        assert report["predictive_validity"] is not None
        assert report["mutation"]["total_mutants"] > 0
        assert report["mutation"]["mutation_score"] is None

    def test_evaluate_suite_without_signals(self):
        agent_map = _agent_map()
        del agent_map["trace_analysis"]
        report = evaluate_suite(_sample_suite(), agent_map)
        assert report["predictive_validity"] is None

    def test_evaluate_suite_with_explicit_signals(self):
        signals = [ProductionSignal(
            signal_id="sig1", trace_id="tr1",
            failure_category=FailureCategory.PII_LEAK,
            description="PII leaked in production",
            tool_involved="reset_password",
        )]
        report = evaluate_suite(_sample_suite(), _agent_map(), production_signals=signals)
        # t2 targets pii_leak on reset_password -> the signal is recalled
        assert report["predictive_validity"]["recall"] == 1.0

    def test_report_is_json_serialisable(self):
        report = evaluate_suite(_sample_suite(), _agent_map())
        json.dumps(report, default=str)


# ---------------------------------------------------------------
# CLI integration: --evaluate flag
# ---------------------------------------------------------------

def test_generate_tests_evaluate_flag(tmp_path):
    """generate_tests.py --skip-ai --include-templates --evaluate writes evaluation_report.json."""
    from generate_tests import main as gen_main

    agent_map_path = tmp_path / "agent_map.json"
    agent_map_path.write_text(json.dumps(_agent_map(), indent=2))
    output_dir = tmp_path / "generated"

    runner = CliRunner()
    result = runner.invoke(gen_main, [
        str(agent_map_path),
        "--output-dir", str(output_dir),
        "--skip-ai",
        "--include-templates",
        "--evaluate",
        "--count", "15",
        "--seed", "42",
    ])
    assert result.exit_code == 0, f"CLI failed: {result.output}"

    report_path = output_dir / "evaluation_report.json"
    assert report_path.exists(), "Missing evaluation_report.json"

    with open(report_path) as f:
        report = json.load(f)
    assert "apfd" in report
    assert "diversity" in report
    assert "taxonomy_coverage" in report
    assert "mutation" in report
    assert report["suite"]["total_tests"] > 0
