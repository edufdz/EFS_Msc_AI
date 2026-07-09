"""
Tests for Sprint E3 — Interaction & Transition Coverage.

Covers:
- covering array generation (IPOG) and the t-way coverage guarantee
- factor extraction from the agent map (tools, parameters, preconditions)
- FSM transition / transition-pair / round-trip coverage
- refactored B1 calculator (floors, covering array, transition goals)
- B4 Phase 1 (covering-array allocation + per-tool floor) and Phase 1.5
"""

from __future__ import annotations

import os
import sys
from itertools import combinations, product

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.coverage.calculator import build_test_configuration, calculate_coverage_goals
from src.coverage.interaction import (
    MAX_FACTORS,
    extract_factors_from_agent_map,
    generate_covering_array,
    tool_of_row,
    verify_covering_array,
)
from src.coverage.models import CoverageGoals, TransitionCoverageGoals
from src.coverage.transition import (
    compute_all_transitions,
    compute_round_trip_paths,
    compute_transition_pairs,
    extract_fsm,
)


# ---------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------

def _fsm() -> dict:
    return {
        "states": [
            {"state_id": "S0", "name": "initial", "is_initial": True, "is_terminal": False},
            {"state_id": "S1", "name": "after_lookup", "is_initial": False, "is_terminal": False},
            {"state_id": "S2", "name": "terminal", "is_initial": False, "is_terminal": True},
        ],
        "transitions": [
            {"from_state": "S0", "to_state": "S1", "trigger": "lookup_order", "guard": None, "frequency": 0.8},
            {"from_state": "S1", "to_state": "S2", "trigger": "process_refund", "guard": None, "frequency": 0.5},
            {"from_state": "S1", "to_state": "S0", "trigger": "escalate", "guard": None, "frequency": 0.2},
        ],
    }


def _agent_map(with_fsm: bool = True) -> dict:
    m = {
        "agent_id": "e3-test",
        "metadata": {"type": "support", "purpose": "Refund support agent"},
        "components": {
            "tools": [
                {
                    "name": "process_refund",
                    "risk_level": "critical",
                    "parameters": [
                        {"name": "amount", "type": "float"},
                        {"name": "order_id", "type": "str"},
                    ],
                    "preconditions": ["amount must not be None", "amount > 0"],
                },
                {
                    "name": "escalate",
                    "risk_level": "high",
                    "parameters": [{"name": "reason", "type": "str"}],
                },
                {"name": "lookup_order", "risk_level": "low", "parameters": []},
            ]
        },
        "risk_flags": {"all_risks": []},
    }
    if with_fsm:
        m["behavioural_model"] = {"fsm": _fsm()}
    return m


_SPEC_FACTORS = [
    {"name": "tool", "levels": ["check_order", "process_refund", "escalate"]},
    {"name": "order_age", "levels": ["<30_days", ">30_days"]},
    {"name": "amount", "levels": ["<$100", ">$100", ">$500"]},
]


# ---------------------------------------------------------------
# E3.1 — Covering array generation
# ---------------------------------------------------------------

class TestGenerateCoveringArray:
    def test_pairwise_covers_all_pairs(self):
        rows = generate_covering_array(_SPEC_FACTORS, strength=2)
        assert verify_covering_array(rows, _SPEC_FACTORS, strength=2)
        # Manually check every pair appears in some row
        for fa, fb in combinations(_SPEC_FACTORS, 2):
            for la, lb in product(fa["levels"], fb["levels"]):
                assert any(
                    r[fa["name"]] == la and r[fb["name"]] == lb for r in rows
                ), f"missing pair ({fa['name']}={la}, {fb['name']}={lb})"

    def test_much_smaller_than_exhaustive(self):
        rows = generate_covering_array(_SPEC_FACTORS, strength=2)
        exhaustive = 3 * 2 * 3
        assert len(rows) < exhaustive
        # Theoretical lower bound: product of the two largest level counts
        assert len(rows) >= 9

    def test_rows_are_complete_assignments(self):
        rows = generate_covering_array(_SPEC_FACTORS, strength=2)
        names = {f["name"] for f in _SPEC_FACTORS}
        for row in rows:
            assert set(row) == names
            for f in _SPEC_FACTORS:
                assert row[f["name"]] in f["levels"]

    def test_strength_3_is_exhaustive_for_3_factors(self):
        rows = generate_covering_array(_SPEC_FACTORS, strength=3)
        assert verify_covering_array(rows, _SPEC_FACTORS, strength=3)
        assert len(rows) == 18  # 3-way over 3 factors = full cartesian product

    def test_many_factors_pairwise(self):
        factors = [
            {"name": f"f{i}", "levels": [f"l{j}" for j in range(2 + i % 3)]}
            for i in range(8)
        ]
        rows = generate_covering_array(factors, strength=2)
        assert verify_covering_array(rows, factors, strength=2)
        exhaustive = 1
        for f in factors:
            exhaustive *= len(f["levels"])
        assert len(rows) < exhaustive / 10  # orders of magnitude smaller

    def test_single_factor(self):
        rows = generate_covering_array([{"name": "tool", "levels": ["a", "b"]}])
        assert {r["tool"] for r in rows} == {"a", "b"}

    def test_strength_1_each_choice(self):
        rows = generate_covering_array(_SPEC_FACTORS, strength=1)
        for f in _SPEC_FACTORS:
            assert set(f["levels"]) <= {r[f["name"]] for r in rows}
        assert len(rows) == 3  # max level count

    def test_empty_and_degenerate_inputs(self):
        assert generate_covering_array([]) == []
        assert generate_covering_array([{"name": "x", "levels": []}]) == []
        assert generate_covering_array([{"name": "", "levels": ["a"]}]) == []

    def test_duplicate_levels_and_names_deduped(self):
        factors = [
            {"name": "a", "levels": ["1", "1", "2"]},
            {"name": "a", "levels": ["9"]},  # duplicate name ignored
            {"name": "b", "levels": ["x", "y"]},
        ]
        rows = generate_covering_array(factors, strength=2)
        deduped = [
            {"name": "a", "levels": ["1", "2"]},
            {"name": "b", "levels": ["x", "y"]},
        ]
        assert verify_covering_array(rows, deduped, strength=2)
        assert all(r["a"] in ("1", "2") for r in rows)

    def test_strength_above_factor_count_degrades(self):
        two = _SPEC_FACTORS[:2]
        rows = generate_covering_array(two, strength=6)
        assert verify_covering_array(rows, two, strength=2)


# ---------------------------------------------------------------
# E3.1 — Factor extraction
# ---------------------------------------------------------------

class TestExtractFactors:
    def test_tool_factor_from_high_critical(self):
        factors = extract_factors_from_agent_map(_agent_map())
        by_name = {f["name"]: f for f in factors}
        assert "tool" in by_name
        assert set(by_name["tool"]["levels"]) == {"process_refund", "escalate"}
        # Low-risk tool never becomes a level
        assert "lookup_order" not in by_name["tool"]["levels"]

    def test_parameter_factors_with_precondition_boundaries(self):
        factors = extract_factors_from_agent_map(_agent_map())
        by_name = {f["name"]: f for f in factors}
        amount = by_name["process_refund.amount"]
        # "must not be None" precondition -> missing level
        assert "missing" in amount["levels"]
        # "> 0" precondition -> negative boundary
        assert "negative" in amount["levels"]

    def test_critical_tool_parameters_before_high(self):
        factors = extract_factors_from_agent_map(_agent_map())
        names = [f["name"] for f in factors]
        assert names.index("process_refund.amount") < names.index("escalate.reason")

    def test_capped_at_max_factors(self):
        m = _agent_map(with_fsm=False)
        m["components"]["tools"] = [
            {
                "name": f"tool_{i}",
                "risk_level": "high",
                "parameters": [{"name": f"p{j}", "type": "str"} for j in range(5)],
            }
            for i in range(6)
        ]
        factors = extract_factors_from_agent_map(m)
        assert len(factors) <= MAX_FACTORS

    def test_no_high_risk_tools_returns_empty(self):
        m = _agent_map(with_fsm=False)
        for t in m["components"]["tools"]:
            t["risk_level"] = "low"
        assert extract_factors_from_agent_map(m) == []

    def test_degrades_on_minimal_map(self):
        assert extract_factors_from_agent_map({}) == []
        assert extract_factors_from_agent_map({"components": {}}) == []

    def test_tool_of_row(self):
        assert tool_of_row({"tool": "escalate", "escalate.reason": "empty"}) == "escalate"
        assert tool_of_row({"process_refund.amount": "zero"}) == "process_refund"
        assert tool_of_row({}) is None


# ---------------------------------------------------------------
# E3.2 — FSM transition coverage
# ---------------------------------------------------------------

class TestTransitionCoverage:
    def test_all_transitions(self):
        transitions = compute_all_transitions(_fsm())
        assert ("S0", "lookup_order", "S1") in transitions
        assert ("S1", "process_refund", "S2") in transitions
        assert ("S1", "escalate", "S0") in transitions
        assert len(transitions) == 3

    def test_all_transitions_dedupes(self):
        fsm = _fsm()
        fsm["transitions"].append(dict(fsm["transitions"][0]))
        assert len(compute_all_transitions(fsm)) == 3

    def test_transition_pairs_are_consecutive(self):
        pairs = compute_transition_pairs(_fsm())
        assert ("S0", "lookup_order", "S1", "process_refund") in pairs
        assert ("S0", "lookup_order", "S1", "escalate") in pairs
        assert ("S1", "escalate", "S0", "lookup_order") in pairs
        # No pair may join non-consecutive transitions
        transitions = compute_all_transitions(_fsm())
        edge = {(f, t): to for f, t, to in transitions}
        for state_a, t1, state_b, t2 in pairs:
            assert edge[(state_a, t1)] == state_b
            assert (state_b, t2) in edge

    def test_round_trips_end_at_initial_or_terminal(self):
        paths = compute_round_trip_paths(_fsm())
        assert paths
        for p in paths:
            assert p[0] == "S0"
            assert p[-1] in ("S0", "S2")
            assert len(p) % 2 == 1  # alternating state/trigger/state

    def test_round_trips_capped(self):
        # Dense FSM: many states fully connected back to initial
        states = [{"state_id": f"S{i}", "name": f"s{i}", "is_initial": i == 0,
                   "is_terminal": False} for i in range(6)]
        transitions = [
            {"from_state": f"S{i}", "to_state": f"S{j}", "trigger": f"t{i}{j}"}
            for i in range(6) for j in range(6) if i != j
        ]
        paths = compute_round_trip_paths({"states": states, "transitions": transitions})
        assert 0 < len(paths) <= 20

    def test_round_trips_prioritise_high_risk(self):
        paths = compute_round_trip_paths(_fsm(), high_risk_tools={"process_refund"})
        assert "process_refund" in paths[0][1::2]

    def test_graceful_on_missing_fsm(self):
        for bad in (None, {}, {"transitions": []}, {"transitions": [{"from_state": "A"}]}):
            assert compute_all_transitions(bad) == []
            assert compute_transition_pairs(bad) == []
            assert compute_round_trip_paths(bad) == []

    def test_extract_fsm(self):
        assert extract_fsm(_agent_map()) is not None
        assert extract_fsm(_agent_map(with_fsm=False)) is None
        assert extract_fsm({}) is None
        assert extract_fsm({"behavioural_model": {"fsm": {"transitions": []}}}) is None


# ---------------------------------------------------------------
# E3.3 / E3.4 — Calculator refactor + models
# ---------------------------------------------------------------

class TestCalculator:
    def test_per_tool_floor_replaces_flat_counts(self):
        goals = calculate_coverage_goals(_agent_map())
        mi = goals.tool_coverage.min_invocations_per_tool
        assert mi["process_refund"] == 3  # was 25
        assert mi["escalate"] == 3       # was 15
        assert mi["lookup_order"] == 1   # was 5

    def test_covering_array_generated(self):
        goals = calculate_coverage_goals(_agent_map())
        tc = goals.tool_coverage
        assert tc.interaction_strength == 2
        assert tc.covering_array
        factors = extract_factors_from_agent_map(_agent_map())
        assert verify_covering_array(tc.covering_array, factors, strength=2)
        # Covering array supersedes legacy pairwise combos
        assert tc.tool_combinations == []

    def test_fallback_to_legacy_combos_without_factors(self):
        m = _agent_map(with_fsm=False)
        # Two high-risk tools with no parameters -> single 2-level factor
        # -> fewer than 2 factors -> legacy pairwise fallback
        m["components"]["tools"] = [
            {"name": "a", "risk_level": "high"},
            {"name": "b", "risk_level": "critical"},
            {"name": "c", "risk_level": "low"},
        ]
        goals = calculate_coverage_goals(m)
        assert goals.tool_coverage.covering_array == []
        assert ["a", "b"] in goals.tool_coverage.tool_combinations

    def test_transition_goals_from_fsm(self):
        goals = calculate_coverage_goals(_agent_map())
        tcov = goals.transition_coverage
        assert isinstance(tcov, TransitionCoverageGoals)
        assert len(tcov.all_transitions) == 3
        assert tcov.transition_pairs  # < 50 transitions -> pairs included
        assert tcov.round_trip_paths

    def test_transition_goals_none_without_fsm(self):
        goals = calculate_coverage_goals(_agent_map(with_fsm=False))
        assert goals.transition_coverage is None

    def test_pairs_skipped_when_many_transitions(self):
        m = _agent_map(with_fsm=False)
        states = [{"state_id": f"S{i}", "name": f"s{i}", "is_initial": i == 0,
                   "is_terminal": i == 59} for i in range(60)]
        transitions = [
            {"from_state": f"S{i}", "to_state": f"S{i+1}", "trigger": f"t{i}"}
            for i in range(59)
        ]
        m["behavioural_model"] = {"fsm": {"states": states, "transitions": transitions}}
        goals = calculate_coverage_goals(m)
        assert len(goals.transition_coverage.all_transitions) == 59
        assert goals.transition_coverage.transition_pairs == []

    def test_forced_budget_lower_than_legacy(self):
        """The forced Phase-1 budget (floors + covering array) must be lower
        than the legacy flat allocation (25/15/10/5 per tool)."""
        goals = calculate_coverage_goals(_agent_map())
        legacy = 25 + 15 + 5  # critical + high + low under the old scheme
        new_forced = (
            sum(goals.tool_coverage.min_invocations_per_tool.values())
            + len(goals.tool_coverage.covering_array)
        )
        assert new_forced < legacy

    def test_configuration_json_roundtrip(self):
        import json

        from src.coverage.models import TestConfiguration

        config = build_test_configuration(_agent_map())
        blob = json.loads(json.dumps(config.model_dump(), default=str))
        restored = TestConfiguration.model_validate(blob)
        assert restored.coverage_goals.transition_coverage.all_transitions == \
            config.coverage_goals.transition_coverage.all_transitions
        assert restored.coverage_goals.tool_coverage.covering_array == \
            config.coverage_goals.tool_coverage.covering_array

    def test_sample_output_degrades_gracefully(self):
        """tests/sample_output.json has no behavioural_model and only
        low-risk tools — must still produce valid goals."""
        import json
        from pathlib import Path

        sample = Path(__file__).parent / "sample_output.json"
        agent_map = json.loads(sample.read_text())
        goals = calculate_coverage_goals(agent_map)
        assert goals.transition_coverage is None
        assert goals.tool_coverage.covering_array == []
        assert all(v <= 3 for v in goals.tool_coverage.min_invocations_per_tool.values())


# ---------------------------------------------------------------
# E3.5 — B4 allocation (Phase 1 + Phase 1.5)
# ---------------------------------------------------------------

def _build_generator(agent_map, target_scenarios=True):
    from src.generator.test_suite import TestSuiteGenerator
    from src.personas.builder import PersonaBuilder
    from src.scenarios.library import ScenarioLibrary

    builder = PersonaBuilder(agent_map)
    builder.load_templates()
    lib = ScenarioLibrary(agent_map)
    lib.load_templates()
    if target_scenarios:
        # Guarantee scenarios exist for every tool in the map
        import uuid
        from datetime import datetime, timezone

        from src.scenarios.models import Scenario

        for tool in agent_map["components"]["tools"]:
            lib.scenarios.append(Scenario(
                scenario_id=str(uuid.uuid4()),
                title=f"Exercise {tool['name']}",
                description=f"User flow through {tool['name']}",
                user_goal=f"use {tool['name']}",
                category="support",
                required_tools=[tool["name"]],
                created_at=datetime.now(timezone.utc),
            ))
    config = build_test_configuration(agent_map)
    return TestSuiteGenerator(
        agent_map=agent_map,
        personas=builder.personas,
        scenarios=lib.scenarios,
        coverage_goals=config.coverage_goals,
        sandbox_config=config.sandbox_config,
    ), config


class TestPhase1InteractionAllocation:
    def test_one_test_per_covering_row(self):
        generator, config = _build_generator(_agent_map())
        tests = generator._generate_tool_coverage_tests()
        interaction = [t for t in tests if t.coverage_goal == "interaction_coverage"]
        assert len(interaction) == len(config.coverage_goals.tool_coverage.covering_array)

    def test_interaction_tests_carry_row_config(self):
        generator, config = _build_generator(_agent_map())
        tests = generator._generate_tool_coverage_tests()
        rows = config.coverage_goals.tool_coverage.covering_array
        for t in tests:
            if t.coverage_goal == "interaction_coverage":
                assert t.execution_config.get("interaction_config") in rows
                assert t.target_tool in ("process_refund", "escalate")

    def test_floor_is_topped_up_not_duplicated(self):
        generator, config = _build_generator(_agent_map())
        tests = generator._generate_tool_coverage_tests()
        goals = config.coverage_goals.tool_coverage
        per_tool = {}
        for t in tests:
            if t.target_tool and "+" not in t.target_tool:
                per_tool[t.target_tool] = per_tool.get(t.target_tool, 0) + 1
        for tool, floor in goals.min_invocations_per_tool.items():
            assert per_tool.get(tool, 0) >= floor, f"{tool} below floor"
        # Tools well covered by the array get no redundant floor tests:
        # array rows targeting a tool count toward its floor
        floor_tests = [t for t in tests if t.coverage_goal == "tool_coverage"]
        array_targets = [t.target_tool for t in tests
                         if t.coverage_goal == "interaction_coverage"]
        for tool in set(array_targets):
            n_array = array_targets.count(tool)
            n_floor = sum(1 for t in floor_tests if t.target_tool == tool)
            floor = goals.min_invocations_per_tool.get(tool, 0)
            assert n_floor == max(0, floor - n_array)

    def test_legacy_combo_path_still_works(self):
        m = _agent_map(with_fsm=False)
        m["components"]["tools"] = [
            {"name": "a", "risk_level": "high"},
            {"name": "b", "risk_level": "critical"},
        ]
        generator, config = _build_generator(m)
        tests = generator._generate_tool_coverage_tests()
        combo_tests = [t for t in tests if t.coverage_goal == "tool_combination"]
        assert len(combo_tests) == len(config.coverage_goals.tool_coverage.tool_combinations)
        assert not any(t.coverage_goal == "interaction_coverage" for t in tests)


class TestPhase15TransitionAllocation:
    def test_every_transition_gets_a_test(self):
        generator, config = _build_generator(_agent_map())
        tests = generator._generate_transition_coverage_tests()
        tcov = config.coverage_goals.transition_coverage
        transition_tests = [t for t in tests if t.coverage_goal == "transition_coverage"]
        assert len(transition_tests) == len(tcov.all_transitions)
        covered = {
            (
                t.execution_config["transition_target"]["from_state"],
                t.execution_config["transition_target"]["trigger"],
                t.execution_config["transition_target"]["to_state"],
            )
            for t in transition_tests
        }
        assert covered == set(tcov.all_transitions)

    def test_transition_tests_match_trigger_scenarios(self):
        generator, _config = _build_generator(_agent_map())
        tests = generator._generate_transition_coverage_tests()
        for t in tests:
            if t.coverage_goal == "transition_coverage" and t.target_tool:
                assert t.execution_config["transition_target"]["trigger"] == t.target_tool
                assert t.target_tool in t.scenario.required_tools

    def test_pair_and_round_trip_tests_created(self):
        generator, config = _build_generator(_agent_map())
        tests = generator._generate_transition_coverage_tests()
        tcov = config.coverage_goals.transition_coverage
        assert sum(1 for t in tests if t.coverage_goal == "transition_pair") == \
            len(tcov.transition_pairs)
        assert sum(1 for t in tests if t.coverage_goal == "round_trip") == \
            len(tcov.round_trip_paths)

    def test_no_transition_tests_without_fsm(self):
        generator, _config = _build_generator(_agent_map(with_fsm=False))
        assert generator._generate_transition_coverage_tests() == []


class TestFullSuiteIntegration:
    def test_generate_respects_target_and_includes_new_goals(self):
        generator, _config = _build_generator(_agent_map())
        suite = generator.generate(target_count=60)
        assert suite.summary.total_tests == 60
        goals = {tc.coverage_goal for tc in suite.test_cases}
        assert "interaction_coverage" in goals
        assert "transition_coverage" in goals

    def test_seed_phase0_untouched(self):
        """Phase 1.5 must not break the E1 seed-preferential allocation."""
        import uuid
        from datetime import datetime, timezone

        from src.scenarios.models import Scenario

        generator, _config = _build_generator(_agent_map())
        generator.scenarios.append(Scenario(
            scenario_id=str(uuid.uuid4()),
            title="Seeded failure",
            description="From production trace",
            user_goal="reproduce failure",
            category="support",
            required_tools=["process_refund"],
            source="production_seed",
            created_at=datetime.now(timezone.utc),
        ))
        # Re-index after mutation
        generator._scenarios_by_tool["process_refund"].append(generator.scenarios[-1])
        suite = generator.generate(target_count=20)
        seed_tests = [tc for tc in suite.test_cases if tc.coverage_goal == "production_seed"]
        assert len(seed_tests) >= 1
        assert suite.summary.total_tests == 20

    def test_total_forced_tests_not_higher_than_legacy(self):
        """'Total test count equal or lower than before': the coverage-forced
        phases (1 + 1.5) must demand fewer tests than legacy flat repetition."""
        generator, _config = _build_generator(_agent_map())
        phase1 = generator._generate_tool_coverage_tests()
        phase15 = generator._generate_transition_coverage_tests()
        legacy_forced = 25 + 15 + 5 + 1  # old flat counts + 1 legacy combo
        assert len(phase1) + len(phase15) <= legacy_forced
