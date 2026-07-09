"""
Integration test: baseline regression / graceful degradation — Sprint E-T.12.2.

The original, un-enhanced pipeline must still produce a valid suite, and a
minimal agent map that lacks every enhanced field (no guardrails, no
behavioural_model, no risk taxonomy, no traces) must degrade gracefully:
enhanced generators produce empty output instead of crashing, and the base
pipeline still fills the requested test budget.
"""

from __future__ import annotations


class TestMinimalMapDegradesGracefully:
    def test_generation_succeeds(self, phase_b):
        gen = phase_b(map_name="python", use_traces=False)
        assert gen.suite.summary.total_tests > 0

    def test_budget_still_filled(self, phase_b):
        gen = phase_b(map_name="python", use_traces=False, count=25)
        # Base pipeline pads to the requested count from template + variant scenarios
        assert gen.suite.summary.total_tests == 25

    def test_baseline_tool_and_edge_coverage_present(self, phase_b):
        gen = phase_b(map_name="python", use_traces=False)
        goals = gen.suite.summary.by_coverage_goal
        assert any(k == "tool_coverage" or k.startswith("interaction") for k in goals)
        assert any(k.startswith("edge_case") for k in goals)

    def test_enhanced_generators_produce_no_output(self, phase_b):
        """No guardrails/risk/behavioural_model → no enhanced scenario sources."""
        gen = phase_b(map_name="python", use_traces=False)
        srcs = gen.scenario_sources
        for enhanced_source in (
            "policy_graph", "guardrail_compliance", "guardrail_violation",
            "adversarial_taint", "adversarial_taxonomy", "production_seed",
        ):
            assert enhanced_source not in srcs

    def test_no_oracles_without_phase_a_data(self, phase_b):
        gen = phase_b(map_name="python", use_traces=False)
        assert gen.suite.summary.total_oracles == 0
        assert all(tc.oracles == [] for tc in gen.suite.test_cases)

    def test_no_transition_coverage_without_fsm(self, phase_b):
        gen = phase_b(map_name="python", use_traces=False)
        assert gen.config["coverage_goals"]["transition_coverage"] is None

    def test_use_traces_without_data_does_not_crash(self, phase_b):
        """--use-traces on a map with no embedded trace_analysis and no file
        still succeeds (graceful no-op, no production seeds)."""
        gen = phase_b(map_name="python", use_traces=False, extra=["--use-traces"])
        assert gen.suite.summary.total_tests > 0
        assert "production_seed" not in gen.scenario_sources


class TestEnrichedMapWithoutTraces:
    """The enriched map still works with traces disabled (structural-only run)."""

    def test_structural_enhancements_still_run(self, phase_b):
        gen = phase_b(map_name="tech_repair", use_traces=False)
        srcs = gen.scenario_sources
        # Guardrail/policy/adversarial come from the map structure, not traces
        assert srcs.get("policy_graph", 0) > 0
        assert srcs.get("guardrail_compliance", 0) > 0
        assert gen.suite.summary.total_oracles > 0
        # ...but no trace-derived sources
        assert "production_seed" not in srcs
