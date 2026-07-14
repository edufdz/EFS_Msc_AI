"""Tests for the RQ4 generation arms (offline — LLM calls are mocked)."""

from __future__ import annotations

import json

import pytest

from src.experiments import arms as arms_module
from src.experiments.arms import (
    available_arms,
    generate_gan_suite,
    generate_naive_llm_suite,
)
from src.scenarios.library import _parse_json
from src.scenarios.models import Scenario, ScenarioFailureConditions, ScenarioSuccessConditions

AGENT_MAP = {
    "agent_id": "arms-test-agent",
    "metadata": {"type": "support", "conversation_language": "English"},
    "components": {
        "tools": [{"name": "get_order_status", "description": "d", "parameters": []}],
        "prompts": [],
    },
    "risk_flags": {"all_risks": []},
}


class TestAvailability:
    def test_llm_arms_skipped_without_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        runnable, skipped = available_arms(["blind", "feedback", "naive_llm", "gan"])
        assert runnable == ["blind", "feedback"]
        assert skipped == ["naive_llm", "gan"]

    def test_llm_arms_runnable_with_key(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        runnable, skipped = available_arms(["naive_llm", "gan"])
        assert runnable == ["naive_llm", "gan"] and skipped == []


class TestParseJson:
    def test_single_object(self):
        assert _parse_json('{"a": 1}') == {"a": 1}

    def test_array_with_prose(self):
        assert _parse_json('Here you go:\n[{"a": 1}, {"a": 2}]\nDone.') == [{"a": 1}, {"a": 2}]

    def test_sequential_objects_collected(self):
        text = '{"title": "s1"}\n{"title": "s2"}\n{"title": "s3"}'
        assert _parse_json(text) == [{"title": "s1"}, {"title": "s2"}, {"title": "s3"}]

    def test_fenced_json(self):
        assert _parse_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_no_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_json("no json here")


def _scenario(title, i=0):
    from datetime import datetime, timezone

    return Scenario(
        created_at=datetime.now(timezone.utc),
        scenario_id=f"s{i}",
        title=title,
        description="d",
        user_goal="do the thing",
        category="support",
        difficulty="medium",
        type="happy_path",
        required_tools=["get_order_status"],
        optional_tools=[],
        forbidden_tools=[],
        success_conditions=ScenarioSuccessConditions(),
        failure_conditions=ScenarioFailureConditions(),
        tags=[],
        estimated_turns=4,
    )


def _fake_personas(builder_self, count=3):
    from src.personas.builder import PersonaBuilder

    lib = PersonaBuilder(AGENT_MAP)
    return lib.load_templates()[:max(count, 2)]


class TestNaiveLLMArm:
    def test_assembles_suite_from_llm_outputs(self, monkeypatch):
        monkeypatch.setattr(
            "src.personas.builder.PersonaBuilder.generate_personas", _fake_personas,
        )
        monkeypatch.setattr(
            "src.scenarios.library.ScenarioLibrary.generate_scenarios",
            lambda self, count=5: [_scenario(f"AI scenario {i}", i) for i in range(count)],
        )
        suite = generate_naive_llm_suite(AGENT_MAP, target_count=12, rng_seed=1)
        assert len(suite.test_cases) == 12

    def test_raises_on_empty_generation(self, monkeypatch):
        monkeypatch.setattr(
            "src.personas.builder.PersonaBuilder.generate_personas", _fake_personas,
        )
        monkeypatch.setattr(
            "src.scenarios.library.ScenarioLibrary.generate_scenarios",
            lambda self, count=5: [],
        )
        with pytest.raises(RuntimeError, match="naive_llm arm produced"):
            generate_naive_llm_suite(AGENT_MAP, target_count=12, rng_seed=1)


class TestGanArm:
    def test_critic_filters_and_feedback_flows(self, monkeypatch):
        generated_batches = []

        def fake_generate(self, count=5):
            batch = [_scenario(f"cand {len(generated_batches)}-{i}", i) for i in range(count)]
            generated_batches.append(self.agent_purpose)
            self.scenarios.extend(batch)
            return batch

        def fake_scores(scenario_lib, scenarios):
            # Accept only index 0, critique the rest
            out = [{"index": 0, "score": 9.0, "critique": ""}]
            out += [
                {"index": i, "score": 3.0, "critique": f"too generic {i}"}
                for i in range(1, len(scenarios))
            ]
            return out

        monkeypatch.setattr(
            "src.personas.builder.PersonaBuilder.generate_personas", _fake_personas,
        )
        monkeypatch.setattr(
            "src.scenarios.library.ScenarioLibrary.generate_scenarios", fake_generate,
        )
        monkeypatch.setattr(arms_module, "_critic_scores", fake_scores)

        suite = generate_gan_suite(AGENT_MAP, target_count=10, rng_seed=1, rounds=2)
        assert len(suite.test_cases) == 10
        # Round 2's generation context contained round 1's critiques
        assert "too generic" in generated_batches[1]
        # Accepted scenarios are tagged
        accepted = [t for t in suite.test_cases if "gan_accepted" in (t.scenario.tags or [])]
        assert accepted

    def test_raises_when_critic_rejects_everything(self, monkeypatch):
        monkeypatch.setattr(
            "src.personas.builder.PersonaBuilder.generate_personas", _fake_personas,
        )
        monkeypatch.setattr(
            "src.scenarios.library.ScenarioLibrary.generate_scenarios",
            lambda self, count=5: [_scenario(f"c{i}", i) for i in range(count)],
        )
        monkeypatch.setattr(
            arms_module, "_critic_scores",
            lambda lib, scenarios: [
                {"index": i, "score": 1.0, "critique": "bad"} for i in range(len(scenarios))
            ],
        )
        with pytest.raises(RuntimeError, match="accepted zero"):
            generate_gan_suite(AGENT_MAP, target_count=10, rng_seed=1, rounds=1)
