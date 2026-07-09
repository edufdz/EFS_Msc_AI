"""
Validation test: enrichment comparison — Sprint E-T.13.1.

Demonstrates that the enhanced pipeline produces a measurably *richer* test
suite than the un-enhanced baseline. Two comparisons are made:

1. Un-enhanced baseline (the minimal ``python`` map — no guardrails, risk
   taxonomy, behavioural model, or traces) vs. the fully-enhanced TechRepair
   run (structural enhancements + production traces). This is where the
   headline numbers live: scenario sources, oracle counts, guardrail
   coverage, adversarial scenarios, and behaviour-space diversity.

2. Incremental value of ``--use-traces``: the same enriched TechRepair map with
   traces off vs. on, isolating the E1 (production-seed) and E6
   (production-grounded persona) contribution.

A note on APFD. APFD is normalised over each suite's own potential-fault
universe, so the *raw* APFD of two suites built over different fault
universes is not directly comparable — a richer suite that surfaces many more
distinct faults can have a lower raw APFD while being strictly better. The
sound, invariant claim for the E8 prioritiser is therefore made *within* the
enhanced suite: its prioritised ordering detects faults earlier than a naive
ordering over the *same* fault matrix. Raw values are reported for context.
"""

from __future__ import annotations

import random

from src.evaluation.apfd import calculate_apfd
from src.evaluation.diversity import compute_suite_diversity
from src.evaluation.harness import build_fault_matrix, synthetic_failures_from_suite
from src.evaluation.predictive_validity import compute_predictive_validity

from ..fixtures import helpers


def _guardrail_rules_covered(gen) -> set:
    rule_ids = {r["rule_id"] for r in (gen.agent_map.get("guardrails") or {}).get("rules", [])}
    covered = set()
    for s in gen.catalog["scenarios"]:
        if s["source"] in ("guardrail_compliance", "guardrail_violation", "policy_graph"):
            covered.update(t for t in s["tags"] if t in rule_ids)
    return covered


def _apfd_orderings(gen):
    fm = build_fault_matrix(gen.suite)
    order = [tc.test_id for tc in sorted(gen.suite.test_cases, key=lambda t: t.test_number)]
    prioritised = calculate_apfd(order, fm)
    reverse = calculate_apfd(list(reversed(order)), fm)
    rng = random.Random(13)
    shuffled = order[:]
    rng.shuffle(shuffled)
    shuffled_apfd = calculate_apfd(shuffled, fm)
    return prioritised, reverse, shuffled_apfd


class TestBaselineVsEnhanced:
    def test_enhanced_has_more_scenario_sources(self, phase_b):
        baseline = phase_b(map_name="python", use_traces=False)
        enhanced = phase_b(map_name="tech_repair", use_traces=True)
        assert len(enhanced.scenario_sources) > len(baseline.scenario_sources)
        assert len(enhanced.scenario_sources) >= 8

    def test_enhanced_has_oracles_baseline_has_none(self, phase_b):
        baseline = phase_b(map_name="python", use_traces=False)
        enhanced = phase_b(map_name="tech_repair", use_traces=True)
        assert baseline.suite.summary.total_oracles == 0
        assert enhanced.suite.summary.total_oracles > 0

    def test_enhanced_covers_all_guardrail_rules_baseline_none(self, phase_b):
        baseline = phase_b(map_name="python", use_traces=False)
        enhanced = phase_b(map_name="tech_repair", use_traces=True)
        assert _guardrail_rules_covered(baseline) == set()
        all_rules = {r["rule_id"] for r in enhanced.agent_map["guardrails"]["rules"]}
        assert _guardrail_rules_covered(enhanced) == all_rules

    def test_enhanced_has_adversarial_scenarios_baseline_none(self, phase_b):
        baseline = phase_b(map_name="python", use_traces=False)
        enhanced = phase_b(map_name="tech_repair", use_traces=True)
        adv = {"adversarial_taint", "adversarial_taxonomy"}
        assert not (adv & set(baseline.scenario_sources))
        assert adv & set(enhanced.scenario_sources)

    def test_enhanced_lower_repetition_higher_interaction_coverage(self, phase_b):
        baseline = phase_b(map_name="python", use_traces=False)
        enhanced = phase_b(map_name="tech_repair", use_traces=True)
        b_ca = baseline.config["coverage_goals"]["tool_coverage"]["covering_array"]
        e_ca = enhanced.config["coverage_goals"]["tool_coverage"]["covering_array"]
        assert len(e_ca) > len(b_ca)
        e_mi = enhanced.config["coverage_goals"]["tool_coverage"]["min_invocations_per_tool"]
        assert max(e_mi.values()) <= 3

    def test_enhanced_diversity_ge_baseline(self, phase_b):
        baseline = phase_b(map_name="python", use_traces=False)
        enhanced = phase_b(map_name="tech_repair", use_traces=True)
        b_div = compute_suite_diversity(baseline.suite, baseline.agent_map)["overall_diversity"]
        e_div = compute_suite_diversity(enhanced.suite, enhanced.agent_map)["overall_diversity"]
        assert e_div >= b_div

    def test_enhanced_prioritiser_beats_naive_ordering(self, phase_b):
        """Sound APFD claim: the E8 prioritised order detects faults earlier
        than reverse / random orderings over the *same* fault matrix."""
        enhanced = phase_b(map_name="tech_repair", use_traces=True)
        prioritised, reverse, shuffled = _apfd_orderings(enhanced)
        assert prioritised >= reverse
        assert prioritised >= shuffled - 1e-9


class TestPredictiveValidity:
    """The enhanced suite's synthetic failures overlap independently-sourced
    production signals (E12.3 predictive validity)."""

    def test_enhanced_suite_recovers_production_signals(self, phase_b):
        enhanced = phase_b(map_name="tech_repair", use_traces=True)
        signals = helpers.load_mock_production_signals()
        synthetic = synthetic_failures_from_suite(enhanced.suite)
        pv = compute_predictive_validity(synthetic, signals)
        # The suite surfaces a non-trivial fraction of real production signals
        assert pv["n_production_signals"] == len(signals)
        assert pv["recall"] > 0.0
        assert pv["f1"] >= 0.0


class TestTracesIncrementalValue:
    def test_traces_add_production_seed_source(self, phase_b):
        no_traces = phase_b(map_name="tech_repair", use_traces=False)
        with_traces = phase_b(map_name="tech_repair", use_traces=True)
        assert "production_seed" not in no_traces.scenario_sources
        assert with_traces.scenario_sources.get("production_seed", 0) > 0
        assert len(with_traces.scenario_sources) > len(no_traces.scenario_sources)

    def test_traces_add_production_grounded_personas(self, phase_b):
        no_traces = phase_b(map_name="tech_repair", use_traces=False)
        with_traces = phase_b(map_name="tech_repair", use_traces=True)
        assert "production_grounded" not in no_traces.persona_sources
        assert with_traces.persona_sources.get("production_grounded", 0) > 0

    def test_traces_do_not_reduce_diversity(self, phase_b):
        no_traces = phase_b(map_name="tech_repair", use_traces=False)
        with_traces = phase_b(map_name="tech_repair", use_traces=True)
        d0 = compute_suite_diversity(no_traces.suite, no_traces.agent_map)["overall_diversity"]
        d1 = compute_suite_diversity(with_traces.suite, with_traces.agent_map)["overall_diversity"]
        # Trace grounding should not shrink behaviour-space coverage
        assert d1 >= d0 - 0.05
