"""
Tests for the Non-LLM Oracle package (Sprint E4).

Covers: oracle generation from Phase A data (postconditions, guardrails,
taint flows, side effects, dependency edges), metamorphic relation
generation, oracle attachment to scenarios, and carry-through to test
cases and the test-suite summary.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.coverage.models import (
    CoverageGoals,
    EdgeCaseCoverageGoals,
    SandboxConfig,
    StressorCoverageGoals,
    ToolCoverageGoals,
)
# Aliased so pytest does not try to collect it as a test class
from src.generator.test_suite import TestSuiteGenerator as SuiteGenerator
from src.oracles.generator import generate_oracles_from_agent_map
from src.oracles.metamorphic import generate_metamorphic_relations
from src.oracles.models import MetamorphicRelation, Oracle, OracleType
from src.personas.models import Persona, PersonaEdgeBehaviors, PersonaStyle, PersonaTraits
from src.scenarios.library import ScenarioLibrary
from src.scenarios.models import Scenario


# ---------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------

def _agent_map() -> dict:
    """Agent map with all Phase A sections the oracle generator consumes."""
    return {
        "agent_id": "agent-1",
        "metadata": {
            "type": "support",
            "purpose": "Help customers with orders and refunds",
            "conversation_language": "Spanish",
            "language": {
                "primary_language": "Spanish",
                "code_switching_detected": True,
                "spanish_formality": "usted",
            },
        },
        "components": {
            "tools": [
                {
                    "name": "verify_order",
                    "risk_level": "low",
                    "read_only": True,
                    "postconditions": ["order status is verified"],
                    "side_effects": [],
                },
                {
                    "name": "process_refund",
                    "risk_level": "critical",
                    "read_only": False,
                    "state_modifying": True,
                    "preconditions": ["order status is verified"],
                    "postconditions": [
                        "order status changes to 'refunded'",
                        "customer receives a confirmation message",
                    ],
                    "side_effects": ["refund transaction recorded in ledger"],
                },
                {
                    "name": "escalate_to_human",
                    "risk_level": "medium",
                    "postconditions": None,
                    "side_effects": None,
                },
            ],
            "prompts": [],
        },
        "guardrails": {
            "rules": [
                {"rule_id": "R001", "text": "Never reveal customer PII",
                 "category": "prohibition", "scope": "global", "target_tools": []},
                {"rule_id": "R002", "text": "Always confirm before processing a refund",
                 "category": "requirement", "scope": "tool",
                 "target_tools": ["process_refund"]},
                {"rule_id": "R003", "text": "If unsure, escalate to a human",
                 "category": "fallback", "scope": "global", "target_tools": []},
            ],
            "total_rules": 3,
            "guardrail_language": "English",
            "guardrail_language_matches_conversation": False,
        },
        "risk_flags": {
            "pii_handling": True,
            "critical_actions": ["process_refund"],
            "taint_flows": [
                {
                    "source": "customer_email parameter",
                    "sink": "http_request body",
                    "path": ["escalate_to_human"],
                    "data_types": ["email"],
                    "risk_level": "high",
                    "taxonomy_ids": ["LLM02"],
                },
            ],
            "all_risks": [
                {"tool": "escalate_to_human", "risk_type": "pii", "pii_type": "email",
                 "severity": "high", "description": "email param"},
                {"tool": "process_refund", "risk_type": "critical_action", "pii_type": None,
                 "severity": "critical", "description": "financial op"},
                {"tool": "verify_order", "risk_type": "pii", "pii_type": "phone",
                 "severity": "medium", "description": "phone param"},
            ],
        },
        "behavioural_model": {
            "dependency_graph": {
                "edges": [
                    {"source_tool": "verify_order", "target_tool": "process_refund",
                     "edge_type": "requires", "weight": 1.0, "evidence": "static",
                     "description": "refund requires verified order"},
                    {"source_tool": "verify_order", "target_tool": "escalate_to_human",
                     "edge_type": "frequently_follows", "weight": 0.4,
                     "evidence": "trace", "description": "sometimes follows"},
                    # duplicate requires edge must be deduped
                    {"source_tool": "verify_order", "target_tool": "process_refund",
                     "edge_type": "requires", "weight": 0.7, "evidence": "ai_inferred",
                     "description": "dup"},
                ],
                "properties": {},
            },
            "coverage_targets": {},
        },
    }


def _scenario(
    scenario_id: str = "s1",
    *,
    required_tools: list[str] | None = None,
    optional_tools: list[str] | None = None,
    base_scenario_id: str | None = None,
) -> Scenario:
    return Scenario(
        scenario_id=scenario_id,
        title=f"Scenario {scenario_id}",
        description="A test scenario",
        user_goal="Get a refund for my order",
        category="support",
        required_tools=required_tools or [],
        optional_tools=optional_tools or [],
        base_scenario_id=base_scenario_id,
        created_at=datetime.now(timezone.utc),
    )


def _persona(persona_id: str = "p1") -> Persona:
    return Persona(
        persona_id=persona_id,
        name=f"Persona {persona_id}",
        agent_type="support",
        source="template",
        traits=PersonaTraits(
            patience=7, clarity=7, tech_savviness=5, politeness=7,
            verbosity=5, language_proficiency=8,
        ),
        style=PersonaStyle(tone="neutral", formality="casual", typo_rate=0.1),
        edge_behaviors=PersonaEdgeBehaviors(),
        created_at=datetime.now(timezone.utc),
    )


def _by_type(oracles: list[Oracle]) -> dict:
    grouped: dict = {}
    for o in oracles:
        grouped.setdefault(o.oracle_type, []).append(o)
    return grouped


# ---------------------------------------------------------------
# Oracle generator
# ---------------------------------------------------------------

class TestOracleGenerator:
    def test_postcondition_oracles(self):
        oracles = _by_type(generate_oracles_from_agent_map(_agent_map()))
        posts = oracles[OracleType.POSTCONDITION]
        # verify_order (1) + process_refund (2); escalate_to_human has None
        assert len(posts) == 3
        refund = [o for o in posts if o.applies_to_tools == ["process_refund"]]
        assert all(o.severity == "critical" for o in refund)
        assert all(o.source == "postcondition:process_refund" for o in refund)
        expressions = {o.check_expression for o in refund}
        # Recognised "status changes to 'X'" pattern compiles to a state comparison
        assert "tool_result.status == 'refunded'" in expressions
        # Unrecognised pattern falls back to a named check
        assert any("postcondition_holds" in e for e in expressions)
        # "status is verified" also matches the status pattern
        verify = next(o for o in posts if o.applies_to_tools == ["verify_order"])
        assert verify.check_expression == "tool_result.status == 'verified'"
        assert verify.severity == "low"

    def test_guardrail_oracles_pairs_and_severity(self):
        oracles = _by_type(generate_oracles_from_agent_map(_agent_map()))
        compliance = oracles[OracleType.GUARDRAIL_COMPLIANCE]
        violation = oracles[OracleType.GUARDRAIL_VIOLATION]
        assert len(compliance) == 3
        assert len(violation) == 3  # one pair per numbered rule

        by_rule = {o.applies_to_rules[0]: o for o in compliance}
        assert by_rule["R001"].severity == "critical"   # prohibition
        assert by_rule["R002"].severity == "high"       # requirement
        assert by_rule["R003"].severity == "low"        # fallback
        assert by_rule["R002"].applies_to_tools == ["process_refund"]
        assert "guardrail_followed('R001')" in by_rule["R001"].check_expression

        neg = {o.applies_to_rules[0]: o for o in violation}
        assert neg["R001"].oracle_type == OracleType.GUARDRAIL_VIOLATION
        assert "provocation_resisted('R001')" in neg["R001"].check_expression

    def test_taint_flow_oracles(self):
        oracles = _by_type(generate_oracles_from_agent_map(_agent_map()))
        taints = oracles[OracleType.TAINT_FLOW]
        sources = {o.source for o in taints}
        # Explicit taint flow
        assert "taint:customer_email parameter→http_request body" in sources
        # PII risk from all_risks without a traced flow (verify_order/phone)
        assert "taint:verify_order:phone" in sources
        # email risk on escalate_to_human is already covered by the traced flow
        assert "taint:escalate_to_human:email" not in sources
        flow = next(o for o in taints if o.source.startswith("taint:customer_email"))
        assert "email" in flow.check_expression
        assert flow.applies_to_tools == ["escalate_to_human"]

    def test_side_effect_oracles(self):
        oracles = _by_type(generate_oracles_from_agent_map(_agent_map()))
        sides = oracles[OracleType.SIDE_EFFECT]
        assert len(sides) == 1
        assert sides[0].applies_to_tools == ["process_refund"]
        assert sides[0].severity == "critical"
        assert "refund transaction recorded in ledger" in sides[0].check_expression

    def test_tool_sequence_oracles(self):
        oracles = _by_type(generate_oracles_from_agent_map(_agent_map()))
        seqs = oracles[OracleType.TOOL_SEQUENCE]
        # only "requires" edges, deduplicated
        assert len(seqs) == 1
        assert seqs[0].check_expression == "verify_order must be called before process_refund"
        assert set(seqs[0].applies_to_tools) == {"verify_order", "process_refund"}

    def test_empty_agent_map_is_graceful(self):
        assert generate_oracles_from_agent_map({}) == []

    def test_sparse_map_without_optional_sections(self):
        sparse = {
            "components": {"tools": [{"name": "t1", "risk_level": "low"}]},
            "risk_flags": {"all_risks": []},
        }
        assert generate_oracles_from_agent_map(sparse) == []


# ---------------------------------------------------------------
# Metamorphic relations
# ---------------------------------------------------------------

class TestMetamorphicRelations:
    def test_language_and_formality_relations_gated_on(self):
        scenarios = [_scenario("s1", required_tools=["verify_order"])]
        relations = generate_metamorphic_relations(scenarios, _agent_map())
        by_source = {r.source for r in relations}
        assert "language_invariance" in by_source   # mismatch + code switching
        assert "formality_invariance" in by_source  # usted detected
        assert "synonym_invariance" in by_source
        lang = next(r for r in relations if r.source == "language_invariance")
        assert lang.base_scenario_id == "s1"
        assert lang.mutant_scenario_id == "s1::language_invariance"
        assert lang.invariant == "tool_calls_equal"

    def test_language_and_formality_gated_off(self):
        agent_map = _agent_map()
        agent_map["metadata"]["language"] = {
            "primary_language": "English",
            "code_switching_detected": False,
            "spanish_formality": None,
        }
        agent_map["guardrails"]["guardrail_language_matches_conversation"] = True
        relations = generate_metamorphic_relations([_scenario("s1")], agent_map)
        sources = {r.source for r in relations}
        assert "language_invariance" not in sources
        assert "formality_invariance" not in sources
        assert "synonym_invariance" in sources  # always applicable for base scenarios

    def test_ordering_invariance_needs_multiple_tools(self):
        agent_map = _agent_map()
        multi = _scenario("multi", required_tools=["verify_order", "process_refund"])
        single = _scenario("single", required_tools=["verify_order"])
        relations = generate_metamorphic_relations([multi, single], agent_map)
        ordering = [r for r in relations if r.source == "ordering_invariance"]
        assert len(ordering) == 1
        assert ordering[0].base_scenario_id == "multi"
        assert ordering[0].invariant == "policy_outcome_equal"

    def test_synonym_relations_only_for_base_scenarios(self):
        variant = _scenario("v1", base_scenario_id="s1")
        relations = generate_metamorphic_relations([variant], _agent_map())
        assert not [r for r in relations if r.source == "synonym_invariance"]


# ---------------------------------------------------------------
# Attachment via ScenarioLibrary
# ---------------------------------------------------------------

class TestAttachOracles:
    def _library(self, scenarios: list[Scenario]) -> ScenarioLibrary:
        lib = ScenarioLibrary(_agent_map())
        lib.scenarios = scenarios
        return lib

    def test_tool_matched_oracles_attached(self):
        s = _scenario("s1", required_tools=["process_refund"])
        lib = self._library([s])
        counts = lib.attach_oracles(_agent_map())
        assert counts["oracles"] == len(s.oracles) > 0

        types = {o.oracle_type for o in s.oracles}
        assert OracleType.POSTCONDITION in types
        assert OracleType.SIDE_EFFECT in types
        assert OracleType.TOOL_SEQUENCE in types
        # Tool-scoped guardrail R002 targets process_refund
        rule_ids = {rid for o in s.oracles for rid in o.applies_to_rules}
        assert "R002" in rule_ids

    def test_global_guardrail_oracles_attached_to_all(self):
        s = _scenario("s1", required_tools=[])  # no tools at all
        lib = self._library([s])
        lib.attach_oracles(_agent_map())
        rule_ids = {rid for o in s.oracles for rid in o.applies_to_rules}
        assert {"R001", "R003"} <= rule_ids   # global-scope rules
        assert "R002" not in rule_ids         # tool-scoped, no matching tool
        # No tool-scoped oracles without tool overlap
        assert not [o for o in s.oracles if o.oracle_type == OracleType.POSTCONDITION]

    def test_no_duplicate_oracles(self):
        s = _scenario("s1", required_tools=["process_refund"],
                      optional_tools=["process_refund", "verify_order"])
        lib = self._library([s])
        lib.attach_oracles(_agent_map())
        ids = [o.oracle_id for o in s.oracles]
        assert len(ids) == len(set(ids))

    def test_metamorphic_relations_attached_to_base(self):
        s = _scenario("s1", required_tools=["verify_order", "process_refund"])
        lib = self._library([s])
        counts = lib.attach_oracles(_agent_map())
        assert counts["metamorphic_relations"] == len(s.metamorphic_relations) > 0
        assert all(r.base_scenario_id == "s1" for r in s.metamorphic_relations)

    def test_scenario_serialization_round_trip(self):
        s = _scenario("s1", required_tools=["process_refund"])
        lib = self._library([s])
        lib.attach_oracles(_agent_map())
        dumped = s.model_dump()
        assert dumped["oracles"]
        restored = Scenario.model_validate(dumped)
        assert restored.oracles == s.oracles
        assert restored.metamorphic_relations == s.metamorphic_relations

    def test_uses_constructor_agent_map_by_default(self):
        s = _scenario("s1", required_tools=["process_refund"])
        lib = self._library([s])
        counts = lib.attach_oracles()  # no explicit map
        assert counts["oracles"] > 0


# ---------------------------------------------------------------
# Carry-through to test cases and summary
# ---------------------------------------------------------------

class TestOracleCarryThrough:
    def test_test_cases_carry_scenario_oracles(self):
        agent_map = _agent_map()
        s = _scenario("s1", required_tools=["process_refund"])
        lib = ScenarioLibrary(agent_map)
        lib.scenarios = [s]
        lib.attach_oracles(agent_map)

        generator = SuiteGenerator(
            agent_map=agent_map,
            personas=[_persona()],
            scenarios=[s],
            coverage_goals=CoverageGoals(
                tool_coverage=ToolCoverageGoals(
                    min_invocations_per_tool={"process_refund": 2},
                ),
                edge_case_coverage=EdgeCaseCoverageGoals(
                    ambiguous_requests=1, incomplete_information=1,
                    user_changes_mind=1, contradictory_statements=1,
                ),
                stressor_coverage=StressorCoverageGoals(
                    timeout_scenarios=1, malformed_response_scenarios=1,
                    data_conflict_scenarios=1,
                ),
            ),
            sandbox_config=SandboxConfig(),
        )
        suite = generator.generate(target_count=10)

        assert suite.test_cases
        for tc in suite.test_cases:
            assert tc.oracles, "every test case should carry its scenario's oracles"
            for o in tc.oracles:
                assert set(o.keys()) == {
                    "oracle_id", "type", "description",
                    "check_expression", "severity",
                }

        # Summary counts (Sprint E4.5)
        assert suite.summary.total_oracles == sum(len(tc.oracles) for tc in suite.test_cases)
        assert suite.summary.total_oracles > 0
        assert sum(suite.summary.oracles_by_type.values()) == suite.summary.total_oracles
        assert OracleType.POSTCONDITION.value in suite.summary.oracles_by_type

    def test_scenarios_without_oracles_still_work(self):
        s = _scenario("s1", required_tools=["verify_order"])  # oracles never attached
        generator = SuiteGenerator(
            agent_map=_agent_map(),
            personas=[_persona()],
            scenarios=[s],
            coverage_goals=CoverageGoals(
                tool_coverage=ToolCoverageGoals(),
                edge_case_coverage=EdgeCaseCoverageGoals(
                    ambiguous_requests=1, incomplete_information=0,
                    user_changes_mind=0, contradictory_statements=0,
                ),
                stressor_coverage=StressorCoverageGoals(
                    timeout_scenarios=0, malformed_response_scenarios=0,
                    data_conflict_scenarios=0,
                ),
            ),
            sandbox_config=SandboxConfig(),
        )
        suite = generator.generate(target_count=3)
        assert suite.summary.total_oracles == 0
        assert all(tc.oracles == [] for tc in suite.test_cases)
