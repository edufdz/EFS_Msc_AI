"""
Tests for the Production-Failure Seed Corpus (Sprint E1).

Covers: trace-to-seed adapter (classification, dedup, persona extraction),
seed-to-scenario / seed-to-persona converters, the mutation engine,
corpus expansion, ScenarioLibrary integration, B4 Phase 0 seed-preferential
allocation, offline trace loading, and the generate_tests.py CLI wiring.
"""

from __future__ import annotations

import json
import os
import random
import sys
from datetime import datetime, timezone

import pytest
from click.testing import CliRunner

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.evaluation.taxonomy import FailureCategory
from src.scenarios.library import ScenarioLibrary
from src.scenarios.models import Scenario
from src.scenarios.seed_corpus import (
    MUTATION_TYPES,
    FailureSeed,
    SeedCorpus,
    build_seed_corpus,
    expand_seed_corpus,
    extract_persona_from_trace,
    load_trace_result,
    mutate_seed,
    seed_to_persona,
    seed_to_scenario,
)


# ---------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------

def _agent_map() -> dict:
    return {
        "agent_id": "tech_repair_wa",
        "metadata": {
            "type": "support",
            "purpose": "TechRepair WhatsApp support agent",
            "conversation_language": "Spanish",
        },
        "components": {
            "tools": [
                {"name": "get_order_status", "risk_level": "low"},
                {"name": "update_address", "risk_level": "high"},
                {"name": "check_warranty", "risk_level": "low"},
                {"name": "escalate_to_human", "risk_level": "medium"},
            ]
        },
    }


def _conv(
    trace_id: str,
    tools: list[str],
    outcome: str = "escalation",
    messages: list[dict] | None = None,
    total_turns: int | None = None,
) -> dict:
    conv = {
        "trace_id": trace_id,
        "tool_sequence": tools,
        "outcome": outcome,
    }
    if messages is not None:
        conv["messages"] = messages
    if total_turns is not None:
        conv["total_turns"] = total_turns
    return conv


def _trace_result(conversations=None, failure_patterns=None) -> dict:
    return {
        "conversations": conversations or [],
        "failure_patterns": failure_patterns or [],
    }


def _seed(**overrides) -> FailureSeed:
    defaults = dict(
        seed_id="seed-001",
        trace_id="trace-abc",
        failure_category=FailureCategory.ESCALATION_FAILURE.value,
        tool_sequence=["get_order_status", "escalate_to_human"],
        user_goal_inferred="Check the status of my order",
        persona_features={"language": "Spanish", "formality": "formal",
                          "verbosity": 5, "emoji_use": "none",
                          "politeness": 8, "patience": 5},
        trigger_conditions=["user: where is my order"],
        outcome="escalation",
        conversation_snippet=[{"role": "user", "content": "donde esta mi pedido"}],
        severity="high",
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return FailureSeed(**defaults)


# ---------------------------------------------------------------
# E1.2 — trace-to-seed adapter
# ---------------------------------------------------------------

class TestBuildSeedCorpus:
    def test_successful_conversations_are_skipped(self):
        tr = _trace_result(conversations=[
            _conv("t1", ["get_order_status"], outcome="success", total_turns=4),
        ])
        corpus = build_seed_corpus(tr, _agent_map())
        assert corpus.total_seeds == 0
        assert corpus.seeds == []

    def test_escalation_classification(self):
        tr = _trace_result(conversations=[
            _conv("t1", ["get_order_status", "escalate_to_human"], total_turns=6),
        ])
        corpus = build_seed_corpus(tr, _agent_map())
        assert corpus.total_seeds == 1
        seed = corpus.seeds[0]
        assert seed.failure_category == FailureCategory.ESCALATION_FAILURE.value
        assert seed.outcome == "escalation"
        assert seed.severity == "high"

    def test_loop_classification(self):
        tr = _trace_result(conversations=[
            _conv("t1", ["get_order_status"] * 3, outcome="abandoned", total_turns=8),
        ])
        corpus = build_seed_corpus(tr, _agent_map())
        assert corpus.seeds[0].failure_category == FailureCategory.INFINITE_LOOP.value
        assert corpus.seeds[0].outcome == "loop"

    def test_premature_exit_classification(self):
        tr = _trace_result(conversations=[
            _conv("t1", [], outcome="abandoned", total_turns=1,
                  messages=[{"role": "user", "content": "hola"}]),
        ])
        corpus = build_seed_corpus(tr, _agent_map())
        assert corpus.seeds[0].failure_category == FailureCategory.PREMATURE_EXIT.value

    def test_wrong_tool_classification_from_failed_call(self):
        tr = _trace_result(conversations=[{
            "trace_id": "t1",
            "tool_calls": [
                {"tool_name": "get_order_status", "success": True},
                {"tool_name": "update_address", "success": False},
            ],
            "outcome": "complaint",
            "total_turns": 5,
        }])
        corpus = build_seed_corpus(tr, _agent_map())
        seed = corpus.seeds[0]
        assert seed.failure_category == FailureCategory.WRONG_TOOL.value
        assert seed.tool_sequence == ["get_order_status", "update_address"]

    def test_failure_patterns_become_seeds(self):
        tr = _trace_result(failure_patterns=[
            {"sequence": ["update_address", "escalate_to_human"], "count": 7},
        ])
        corpus = build_seed_corpus(tr, _agent_map())
        assert corpus.total_seeds == 1
        seed = corpus.seeds[0]
        assert seed.failure_category == FailureCategory.ESCALATION_FAILURE.value
        assert seed.tool_sequence == ["update_address", "escalate_to_human"]
        assert any("7 times" in t for t in seed.trigger_conditions)

    def test_dedup_keeps_highest_severity(self):
        # Two records with the same (category, tool_sequence) key
        tr = _trace_result(
            conversations=[
                _conv("t1", ["update_address", "escalate_to_human"], total_turns=5),
            ],
            failure_patterns=[
                {"sequence": ["update_address", "escalate_to_human"], "count": 3},
            ],
        )
        corpus = build_seed_corpus(tr, _agent_map())
        assert corpus.total_seeds == 1

    def test_aggregates(self):
        tr = _trace_result(conversations=[
            _conv("t1", ["get_order_status", "escalate_to_human"], total_turns=5),
            _conv("t2", ["update_address"] * 3, outcome="loop", total_turns=6),
        ])
        corpus = build_seed_corpus(tr, _agent_map())
        assert corpus.total_seeds == 2
        assert corpus.by_outcome == {"escalation": 1, "loop": 1}
        assert corpus.by_tool["escalate_to_human"] == 1
        assert corpus.by_tool["update_address"] == 1
        assert sum(corpus.by_category.values()) == 2

    def test_user_goal_is_anonymised_and_truncated(self):
        messages = [
            {"role": "user", "content": "my email is juan@example.com and order 1234567890 " + "x" * 300},
        ]
        tr = _trace_result(conversations=[
            _conv("t1", ["get_order_status", "escalate_to_human"],
                  messages=messages, total_turns=4),
        ])
        corpus = build_seed_corpus(tr, _agent_map())
        goal = corpus.seeds[0].user_goal_inferred
        assert "juan@example.com" not in goal
        assert "1234567890" not in goal
        assert "[email]" in goal
        assert len(goal) <= 200

    def test_works_with_object_style_trace_result(self):
        class FakeResult:
            conversations = [
                _conv("t1", ["get_order_status", "escalate_to_human"], total_turns=4),
            ]
            failure_patterns = []

        corpus = build_seed_corpus(FakeResult(), _agent_map())
        assert corpus.total_seeds == 1


# ---------------------------------------------------------------
# E1.2 — persona extraction
# ---------------------------------------------------------------

class TestExtractPersona:
    def test_spanish_formal(self):
        conv = {"messages": [
            {"role": "user", "content": "Buenos días, quisiera saber dónde está mi pedido, por favor. Usted podría ayudarme, le agradezco mucho."},
            {"role": "assistant", "content": "Claro que sí"},
            {"role": "user", "content": "Gracias, necesito la información de mi pedido hoy."},
        ]}
        features = extract_persona_from_trace(conv)
        assert features["language"] == "Spanish"
        assert features["formality"] == "formal"
        assert features["politeness"] == 8

    def test_english_casual_with_emoji(self):
        conv = {"messages": [
            {"role": "user", "content": "hey where is my stuff 😡😡😡"},
            {"role": "user", "content": "yo this is taking forever 😤"},
        ]}
        features = extract_persona_from_trace(conv)
        assert features["language"] == "English"
        assert features["formality"] == "casual"
        assert features["emoji_use"] in ("moderate", "frequent")
        assert features["verbosity"] <= 5

    def test_accepts_bare_message_list(self):
        features = extract_persona_from_trace([
            {"role": "user", "content": "this agent is useless and stupid"},
        ])
        assert features["politeness"] == 2
        assert features["patience"] == 3

    def test_empty_conversation(self):
        features = extract_persona_from_trace({"messages": []})
        assert features["message_count"] == 0
        assert features["verbosity"] == 5


# ---------------------------------------------------------------
# E1.3 — converters
# ---------------------------------------------------------------

class TestSeedToScenario:
    def test_basic_mapping(self):
        scenario = seed_to_scenario(_seed(), _agent_map())
        assert isinstance(scenario, Scenario)
        assert scenario.source == "production_seed"
        assert scenario.type == "error_path"
        assert scenario.difficulty == "hard"
        assert scenario.title == "Production failure: escalation_failure in get_order_status"
        assert scenario.user_goal == "Check the status of my order"
        assert scenario.required_tools == ["get_order_status", "escalate_to_human"]
        assert "production_failure" in scenario.tags
        assert FailureCategory.ESCALATION_FAILURE.value in scenario.tags
        assert "escalation" in scenario.tags

    def test_unknown_tools_filtered(self):
        seed = _seed(tool_sequence=["get_order_status", "nonexistent_tool"])
        scenario = seed_to_scenario(seed, _agent_map())
        assert scenario.required_tools == ["get_order_status"]

    def test_wrong_tool_sets_failure_condition(self):
        seed = _seed(
            failure_category=FailureCategory.WRONG_TOOL.value,
            outcome="complaint",
        )
        scenario = seed_to_scenario(seed, _agent_map())
        assert scenario.failure_conditions.wrong_tool_called is True
        assert scenario.success_conditions.user_satisfied is True
        assert scenario.success_conditions.tools_called == ["get_order_status", "escalate_to_human"]

    def test_starter_opener_from_snippet(self):
        scenario = seed_to_scenario(_seed(), _agent_map())
        assert scenario.starter_openers == ["donde esta mi pedido"]

    def test_serialisable_in_catalog(self):
        scenario = seed_to_scenario(_seed(), _agent_map())
        dumped = scenario.model_dump()
        assert json.dumps(dumped, default=str)  # round-trips to JSON


class TestSeedToPersona:
    def test_basic_mapping(self):
        persona = seed_to_persona(_seed(), agent_type="support")
        assert persona.source == "production_seed"
        assert persona.agent_type == "support"
        assert persona.style.formality == "formal"
        assert persona.traits.politeness == 8
        assert persona.edge_behaviors.rage_quits is True  # escalation outcome
        assert persona.sample_messages == ["donde esta mi pedido"]

    def test_defaults_when_no_features(self):
        persona = seed_to_persona(_seed(persona_features={}))
        assert persona.traits.verbosity == 5
        assert persona.style.formality == "casual"


# ---------------------------------------------------------------
# E1.4 — mutation engine
# ---------------------------------------------------------------

class TestMutateSeed:
    def test_unknown_mutation_type_raises(self):
        with pytest.raises(ValueError):
            mutate_seed(_seed(), "nonsense")

    def test_lineage_fields(self):
        for mtype in MUTATION_TYPES:
            mutant = mutate_seed(_seed(), mtype, agent_map=_agent_map(),
                                 rng=random.Random(42))
            assert mutant.seed_id != "seed-001"
            assert mutant.parent_seed_id == "seed-001"
            assert mutant.mutation_type == mtype
            assert mutant.failure_category == FailureCategory.ESCALATION_FAILURE.value

    def test_swap_persona_changes_traits_not_tools(self):
        mutant = mutate_seed(_seed(), "swap_persona", rng=random.Random(1))
        assert mutant.tool_sequence == ["get_order_status", "escalate_to_human"]
        assert mutant.persona_features["formality"] == "casual"  # flipped from formal
        assert mutant.persona_features["verbosity"] != 5

    def test_perturb_tool_arg_keeps_sequence(self):
        mutant = mutate_seed(_seed(), "perturb_tool_arg", rng=random.Random(1))
        assert mutant.tool_sequence == ["get_order_status", "escalate_to_human"]
        assert any("perturbed" in t for t in mutant.trigger_conditions)

    def test_adjacent_tool_replaces_one_tool(self):
        mutant = mutate_seed(_seed(), "adjacent_tool", agent_map=_agent_map(),
                             rng=random.Random(3))
        assert len(mutant.tool_sequence) == 2
        assert mutant.tool_sequence != ["get_order_status", "escalate_to_human"]
        # Replacement comes from the agent's tool inventory
        agent_tools = {t["name"] for t in _agent_map()["components"]["tools"]}
        assert all(t in agent_tools for t in mutant.tool_sequence)

    def test_add_noise_inserts_unrelated_tool(self):
        mutant = mutate_seed(_seed(), "add_noise", agent_map=_agent_map(),
                             rng=random.Random(5))
        assert len(mutant.tool_sequence) == 3
        added = set(mutant.tool_sequence) - {"get_order_status", "escalate_to_human"}
        assert added <= {"update_address", "check_warranty"}

    def test_change_language_flips(self):
        mutant = mutate_seed(_seed(), "change_language")
        assert mutant.persona_features["language"] == "English"
        mutant2 = mutate_seed(mutant, "change_language")
        assert mutant2.persona_features["language"] == "Spanish"

    def test_change_formality_flips(self):
        mutant = mutate_seed(_seed(), "change_formality")
        assert mutant.persona_features["formality"] == "casual"


class TestExpandSeedCorpus:
    def test_generates_mutations_per_seed(self):
        tr = _trace_result(conversations=[
            _conv("t1", ["get_order_status", "escalate_to_human"], total_turns=5),
            _conv("t2", ["update_address"] * 3, outcome="loop", total_turns=6),
        ])
        corpus = build_seed_corpus(tr, _agent_map())
        scenarios = expand_seed_corpus(corpus, mutations_per_seed=3,
                                       agent_map=_agent_map(),
                                       rng=random.Random(7))
        assert len(scenarios) == corpus.total_seeds * 3
        assert all(s.source == "production_seed" for s in scenarios)
        assert all(s.variant_type in MUTATION_TYPES for s in scenarios)
        # Mutants point back at their parent seed scenario
        seed_ids = {seed.seed_id for seed in corpus.seeds}
        assert all(s.base_scenario_id in seed_ids for s in scenarios)


# ---------------------------------------------------------------
# E1.5 — ScenarioLibrary integration
# ---------------------------------------------------------------

class TestLoadProductionSeeds:
    def test_appends_originals_plus_mutations(self):
        lib = ScenarioLibrary(_agent_map())
        tr = _trace_result(conversations=[
            _conv("t1", ["get_order_status", "escalate_to_human"], total_turns=5),
        ])
        loaded = lib.load_production_seeds(tr, mutations_per_seed=3)
        assert len(loaded) == 1 + 3  # original seed + 3 mutants
        assert len(lib.scenarios) == 4
        assert all(s.source == "production_seed" for s in lib.scenarios)

    def test_empty_trace_result_loads_nothing(self):
        lib = ScenarioLibrary(_agent_map())
        loaded = lib.load_production_seeds(_trace_result())
        assert loaded == []
        assert lib.scenarios == []


# ---------------------------------------------------------------
# Offline trace loading
# ---------------------------------------------------------------

class TestLoadTraceResult:
    def test_from_file_dict(self, tmp_path):
        path = tmp_path / "traces.json"
        path.write_text(json.dumps(_trace_result(
            conversations=[_conv("t1", ["get_order_status"], total_turns=3)],
        )))
        result = load_trace_result(traces_file=str(path))
        assert len(result["conversations"]) == 1

    def test_from_file_bare_list(self, tmp_path):
        path = tmp_path / "traces.json"
        path.write_text(json.dumps([_conv("t1", ["get_order_status"])]))
        result = load_trace_result(traces_file=str(path))
        assert len(result["conversations"]) == 1
        assert result["failure_patterns"] == []

    def test_from_agent_map_trace_analysis(self):
        agent_map = _agent_map()
        agent_map["trace_analysis"] = {
            "failure_patterns": [{"sequence": ["update_address"], "count": 2}],
        }
        result = load_trace_result(agent_map=agent_map)
        assert result["failure_patterns"][0]["count"] == 2

    def test_graceful_none_when_no_data(self):
        assert load_trace_result() is None
        assert load_trace_result(agent_map=_agent_map()) is None
        assert load_trace_result(traces_file="/does/not/exist.json") is None


# ---------------------------------------------------------------
# E1.6 — B4 Phase 0 seed-preferential allocation
# ---------------------------------------------------------------

class TestPhase0Allocation:
    def _generator(self, scenarios, target=20):
        from src.coverage.calculator import build_test_configuration
        from src.generator.test_suite import TestSuiteGenerator
        from src.personas.builder import PersonaBuilder

        agent_map = _agent_map()
        builder = PersonaBuilder(agent_map)
        builder.load_templates()
        config = build_test_configuration(agent_map)
        return TestSuiteGenerator(
            agent_map=agent_map,
            personas=builder.personas,
            scenarios=scenarios,
            coverage_goals=config.coverage_goals,
            sandbox_config=config.sandbox_config,
        )

    def _seed_scenarios(self, n=3):
        lib = ScenarioLibrary(_agent_map())
        tr = _trace_result(conversations=[
            _conv(f"t{i}", ["get_order_status", "escalate_to_human"] if i % 2
                  else ["update_address"] * 3,
                  outcome="escalation" if i % 2 else "loop", total_turns=5)
            for i in range(n)
        ])
        lib.load_templates()
        lib.load_production_seeds(tr, mutations_per_seed=2)
        return lib.scenarios

    def test_seed_tests_allocated_with_goal(self):
        scenarios = self._seed_scenarios()
        generator = self._generator(scenarios)
        suite = generator.generate(target_count=30)
        seed_tests = [tc for tc in suite.test_cases if tc.coverage_goal == "production_seed"]
        assert len(seed_tests) >= 1
        assert all(tc.scenario.source == "production_seed" for tc in seed_tests)

    def test_budget_capped_at_fraction(self):
        scenarios = self._seed_scenarios(n=10)
        generator = self._generator(scenarios)
        target = 30
        suite = generator.generate(target_count=target)
        seed_tests = [tc for tc in suite.test_cases if tc.coverage_goal == "production_seed"]
        assert 1 <= len(seed_tests) <= max(1, int(target * 0.2))

    def test_seed_tests_survive_trim(self):
        scenarios = self._seed_scenarios(n=4)
        generator = self._generator(scenarios)
        # Tiny target forces heavy trimming; Phase 0 tests must survive
        suite = generator.generate(target_count=10)
        seed_tests = [tc for tc in suite.test_cases if tc.coverage_goal == "production_seed"]
        assert len(seed_tests) >= 1
        assert suite.summary.total_tests == 10

    def test_no_seed_scenarios_no_phase0(self):
        lib = ScenarioLibrary(_agent_map())
        lib.load_templates()
        generator = self._generator(lib.scenarios)
        suite = generator.generate(target_count=15)
        assert all(tc.coverage_goal != "production_seed" for tc in suite.test_cases)

    def test_budget_fraction_configurable(self):
        from src.coverage.calculator import build_test_configuration
        from src.generator.test_suite import TestSuiteGenerator
        from src.personas.builder import PersonaBuilder

        agent_map = _agent_map()
        builder = PersonaBuilder(agent_map)
        builder.load_templates()
        config = build_test_configuration(agent_map)
        generator = TestSuiteGenerator(
            agent_map=agent_map,
            personas=builder.personas,
            scenarios=self._seed_scenarios(n=10),
            coverage_goals=config.coverage_goals,
            sandbox_config=config.sandbox_config,
            seed_budget_fraction=0.5,
        )
        suite = generator.generate(target_count=20)
        seed_tests = [tc for tc in suite.test_cases if tc.coverage_goal == "production_seed"]
        assert len(seed_tests) <= 10  # 50% of 20


# ---------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------

class TestCli:
    def test_flags_exist(self):
        from generate_tests import main
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "--use-traces" in result.output
        assert "--traces-file" in result.output

    def test_end_to_end_with_traces_file(self, tmp_path):
        from generate_tests import main

        agent_map = _agent_map()
        map_path = tmp_path / "agent_map.json"
        map_path.write_text(json.dumps(agent_map))

        traces = _trace_result(
            conversations=[
                _conv("t1", ["get_order_status", "escalate_to_human"],
                      total_turns=5,
                      messages=[{"role": "user", "content": "dónde está mi pedido por favor"}]),
            ],
            failure_patterns=[
                {"sequence": ["update_address", "update_address", "update_address"], "count": 4},
            ],
        )
        traces_path = tmp_path / "traces.json"
        traces_path.write_text(json.dumps(traces))

        out_dir = tmp_path / "out"
        runner = CliRunner()
        result = runner.invoke(main, [
            str(map_path),
            "--skip-ai", "--include-templates", "--use-traces",
            "--traces-file", str(traces_path),
            "--count", "25", "--seed", "42",
            "-o", str(out_dir),
        ])
        assert result.exit_code == 0, result.output
        assert "Production seeds:" in result.output

        catalog = json.loads((out_dir / "scenario_catalog.json").read_text())
        seed_scenarios = [s for s in catalog["scenarios"] if s["source"] == "production_seed"]
        assert len(seed_scenarios) >= 2  # 2 seeds + mutants (minus any dedup)

        suite = json.loads((out_dir / "test_suite.json").read_text())
        seed_tests = [tc for tc in suite["test_cases"] if tc["coverage_goal"] == "production_seed"]
        assert len(seed_tests) >= 1

    def test_use_traces_without_data_degrades_gracefully(self, tmp_path):
        from generate_tests import main

        map_path = tmp_path / "agent_map.json"
        map_path.write_text(json.dumps(_agent_map()))
        out_dir = tmp_path / "out"
        runner = CliRunner()
        result = runner.invoke(main, [
            str(map_path),
            "--skip-ai", "--include-templates", "--use-traces",
            "--count", "10",
            "-o", str(out_dir),
        ])
        assert result.exit_code == 0, result.output
        assert "skipping production seeds" in result.output
