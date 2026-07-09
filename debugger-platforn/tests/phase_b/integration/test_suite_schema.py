"""
Integration test: output schema validation — Sprint E-T.12.3.

Validates that the three emitted artefacts (test_suite.json,
persona_library.json, scenario_catalog.json) carry the fields the
enhancements add, using the fully-enhanced TechRepair run.
"""

from __future__ import annotations

from src.generator.models import TestSuite as SuiteModel

# Enhancement-introduced scenario sources (E1/E2/E5/E11)
_NEW_SCENARIO_SOURCES = {
    "policy_graph", "production_seed", "guardrail_compliance",
    "guardrail_violation", "adversarial_taint", "adversarial_taxonomy",
}
# Enhancement-introduced persona sources (E5/E6)
_NEW_PERSONA_SOURCES = {"production_grounded", "adversarial"}
# Enhancement-introduced coverage goals (E1/E3/E5)
_NEW_COVERAGE_GOALS = {"production_seed", "transition_coverage", "interaction_coverage"}


class TestTestSuiteSchema:
    def test_test_suite_model_validates(self, phase_b):
        gen = phase_b(map_name="tech_repair", use_traces=True)
        # Full pydantic validation of the serialised suite
        suite = SuiteModel.model_validate(gen.suite_raw)
        assert suite.test_cases

    def test_test_cases_have_required_fields(self, phase_b):
        gen = phase_b(map_name="tech_repair", use_traces=True)
        for tc in gen.suite_raw["test_cases"]:
            assert {"scenario", "persona", "execution_config", "coverage_goal",
                    "difficulty", "oracles"} <= set(tc.keys())
            assert isinstance(tc["oracles"], list)

    def test_oracle_carry_through_shape(self, phase_b):
        gen = phase_b(map_name="tech_repair", use_traces=True)
        for tc in gen.suite_raw["test_cases"]:
            for o in tc["oracles"]:
                assert set(o.keys()) == {
                    "oracle_id", "type", "description", "check_expression", "severity",
                }

    def test_summary_has_new_coverage_goals(self, phase_b):
        gen = phase_b(map_name="tech_repair", use_traces=True)
        goals = set(gen.suite_raw["summary"]["by_coverage_goal"])
        assert _NEW_COVERAGE_GOALS <= goals, f"missing: {_NEW_COVERAGE_GOALS - goals}"
        # Adversarial goals are taxonomy-suffixed (e.g. "adversarial:LLM02")
        assert any(g.startswith("adversarial:") for g in goals)

    def test_summary_oracle_accounting(self, phase_b):
        gen = phase_b(map_name="tech_repair", use_traces=True)
        summary = gen.suite_raw["summary"]
        assert summary["total_oracles"] > 0
        assert sum(summary["oracles_by_type"].values()) == summary["total_oracles"]
        assert summary["tool_invocation_counts"]

    def test_tool_invocation_counts_reflect_reduced_repetition(self, phase_b):
        """No single tool is invoked anywhere near the old flat 25x floor
        purely from the per-tool minimum (interaction coverage, E3)."""
        gen = phase_b(map_name="tech_repair", use_traces=True)
        mi = gen.config["coverage_goals"]["tool_coverage"]["min_invocations_per_tool"]
        assert max(mi.values()) <= 3


class TestPersonaLibrarySchema:
    def test_persona_sources_include_new_kinds(self, phase_b):
        gen = phase_b(map_name="tech_repair", use_traces=True)
        sources = set(gen.persona_sources)
        assert _NEW_PERSONA_SOURCES <= sources, f"missing: {_NEW_PERSONA_SOURCES - sources}"

    def test_personas_have_traits_and_edge_behaviors(self, phase_b):
        gen = phase_b(map_name="tech_repair", use_traces=True)
        for p in gen.library["personas"]:
            assert "traits" in p and "edge_behaviors" in p and "source" in p


class TestScenarioCatalogSchema:
    def test_scenario_sources_include_all_new_kinds(self, phase_b):
        gen = phase_b(map_name="tech_repair", use_traces=True)
        sources = set(gen.scenario_sources)
        assert _NEW_SCENARIO_SOURCES <= sources, f"missing: {_NEW_SCENARIO_SOURCES - sources}"

    def test_scenarios_have_oracles_field(self, phase_b):
        gen = phase_b(map_name="tech_repair", use_traces=True)
        for s in gen.catalog["scenarios"]:
            assert "oracles" in s
            assert isinstance(s["oracles"], list)

    def test_adversarial_and_policy_scenarios_carry_oracles(self, phase_b):
        gen = phase_b(map_name="tech_repair", use_traces=True)
        enriched = [
            s for s in gen.catalog["scenarios"]
            if s["source"] in ("adversarial_taint", "adversarial_taxonomy", "guardrail_compliance")
        ]
        assert enriched
        assert all(s["oracles"] for s in enriched), \
            "adversarial/guardrail scenarios should each carry >=1 oracle"
