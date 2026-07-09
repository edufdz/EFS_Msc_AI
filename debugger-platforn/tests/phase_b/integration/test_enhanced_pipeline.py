"""
Integration test: the full enhanced Phase B pipeline (B1-B4) — Sprint E-T.12.1.

Drives the real ``generate_tests`` CLI offline against the rich TechRepair agent
map and asserts that every enhancement's output is present and wired through
to the emitted test suite: policy-graph / guardrail / adversarial scenario
sources, non-LLM oracles attached, reduced per-tool repetition via interaction
coverage, FSM transition coverage consumed, production seeds/personas from
traces, and an APFD figure reported.
"""

from __future__ import annotations

import json

from src.scenarios.adversarial import present_taxonomy_ids


class TestEnhancedPipelineStructural:
    """Full B1-B4 against the TechRepair map with all structural enhancements."""

    def test_suite_is_valid_and_non_empty(self, phase_b):
        gen = phase_b(map_name="tech_repair", use_traces=True)
        assert gen.suite.summary.total_tests > 0
        # Round-trips through the pydantic model (valid JSON schema)
        assert json.loads((gen.out_dir / "test_suite.json").read_text())["test_cases"]

    def test_policy_graph_scenarios_present(self, phase_b):
        gen = phase_b(map_name="tech_repair", use_traces=True)
        assert gen.scenario_sources.get("policy_graph", 0) > 0

    def test_guardrail_compliance_and_violation_sources(self, phase_b):
        gen = phase_b(map_name="tech_repair", use_traces=True)
        srcs = gen.scenario_sources
        assert srcs.get("guardrail_compliance", 0) > 0
        assert srcs.get("guardrail_violation", 0) > 0

    def test_all_guardrail_rules_covered(self, phase_b):
        gen = phase_b(map_name="tech_repair", use_traces=True)
        rule_ids = {
            r["rule_id"] for r in gen.agent_map["guardrails"]["rules"]
        }
        covered = set()
        for s in gen.catalog["scenarios"]:
            if s["source"] in ("guardrail_compliance", "guardrail_violation", "policy_graph"):
                covered.update(t for t in s["tags"] if t in rule_ids)
        assert rule_ids <= covered, f"rules not covered: {rule_ids - covered}"

    def test_test_cases_carry_oracles(self, phase_b):
        gen = phase_b(map_name="tech_repair", use_traces=True)
        assert gen.suite.summary.total_oracles > 0
        assert any(tc.oracles for tc in gen.suite.test_cases)
        # Every attached oracle uses the compact 5-key carry-through shape (E4.5)
        for tc in gen.suite.test_cases:
            for o in tc.oracles:
                assert set(o.keys()) == {
                    "oracle_id", "type", "description", "check_expression", "severity",
                }

    def test_interaction_coverage_reduces_repetition(self, phase_b):
        """min_invocations per tool is a small floor (<=3), not 25x (E3)."""
        gen = phase_b(map_name="tech_repair", use_traces=True)
        mi = gen.config["coverage_goals"]["tool_coverage"]["min_invocations_per_tool"]
        assert mi, "expected per-tool floors"
        assert max(mi.values()) <= 3, f"per-tool repetition too high: {mi}"
        # Interaction covering array replaces flat repetition
        assert len(gen.config["coverage_goals"]["tool_coverage"]["covering_array"]) > 0

    def test_transition_coverage_consumed(self, phase_b):
        """behavioural_model FSM → transition coverage targets are populated."""
        gen = phase_b(map_name="tech_repair", use_traces=True)
        tcov = gen.config["coverage_goals"]["transition_coverage"]
        assert tcov is not None
        fsm_transitions = gen.agent_map["behavioural_model"]["fsm"]["transitions"]
        assert len(tcov["all_transitions"]) == len(fsm_transitions)
        assert len(tcov["transition_pairs"]) > 0
        # And the suite actually allocates transition-coverage tests
        assert "transition_coverage" in gen.suite.summary.by_coverage_goal

    def test_apfd_reported(self, phase_b):
        gen = phase_b(map_name="tech_repair", use_traces=True)
        assert "Estimated APFD" in gen.cli_output


class TestEnhancedPipelineWithTraces:
    """Production-seed (E1) and production-grounded persona (E6) enrichment."""

    def test_production_seed_scenarios_present(self, phase_b):
        gen = phase_b(map_name="tech_repair", use_traces=True)
        assert gen.scenario_sources.get("production_seed", 0) > 0

    def test_production_grounded_personas_present(self, phase_b):
        gen = phase_b(map_name="tech_repair", use_traces=True)
        assert gen.persona_sources.get("production_grounded", 0) > 0

    def test_seed_scenarios_allocated_in_suite(self, phase_b):
        """Seeds appear in the Phase-0 allocation (coverage_goal production_seed)."""
        gen = phase_b(map_name="tech_repair", use_traces=True)
        assert gen.suite.summary.by_coverage_goal.get("production_seed", 0) > 0

    def test_traces_off_yields_no_production_sources(self, phase_b):
        gen = phase_b(map_name="tech_repair", use_traces=False)
        assert "production_seed" not in gen.scenario_sources
        assert "production_grounded" not in gen.persona_sources


class TestEnhancedPipelineAdversarial:
    """Risk-guided adversarial coverage (E5)."""

    def test_adversarial_scenario_sources_present(self, phase_b):
        gen = phase_b(map_name="tech_repair", use_traces=True)
        srcs = gen.scenario_sources
        assert srcs.get("adversarial_taint", 0) > 0 or srcs.get("adversarial_taxonomy", 0) > 0

    def test_every_taxonomy_has_an_adversarial_scenario(self, phase_b):
        """Every taxonomy_id present in risk_flags gets >=1 adversarial test."""
        gen = phase_b(map_name="tech_repair", use_traces=True)
        present = set(present_taxonomy_ids(gen.agent_map))
        assert present, "fixture should carry OWASP/ASI taxonomy ids"
        adv_tags = set()
        for s in gen.catalog["scenarios"]:
            if s["source"] in ("adversarial_taint", "adversarial_taxonomy"):
                adv_tags.update(s["tags"])
        missing = present - adv_tags
        assert not missing, f"taxonomies with no adversarial scenario: {missing}"
