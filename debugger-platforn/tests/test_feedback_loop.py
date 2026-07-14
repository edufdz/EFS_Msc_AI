"""Tests for the production-feedback loop (src/feedback)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.feedback import (
    LeakageError,
    build_feedback_corpus,
    generate_blind_suite,
    generate_feedback_suite,
    production_failure_to_seed,
    verify_no_leakage,
)
from src.production.ground_truth import GroundTruthFailure


AGENT_MAP = {
    "agent_id": "test-agent",
    "metadata": {"type": "support", "conversation_language": "Spanish"},
    "components": {
        "tools": [
            {"name": "get_order_status", "description": "Look up an order",
             "parameters": [{"name": "order_id", "type": "string"}]},
            {"name": "escalate_to_human", "description": "Escalate",
             "parameters": []},
        ],
        "prompts": [],
    },
    "risk_flags": {"all_risks": []},
}


def _failure(cid="conv-1", categories=None, shared=None, score=8.0, ts="2026-03-01T12:00:00+00:00"):
    return GroundTruthFailure(
        conversation_id=cid,
        timestamp=datetime.fromisoformat(ts),
        failure_score=score,
        production_categories=categories or ["resolution"],
        shared_categories=shared or ["resolution_failure"],
        severity="high",
        evidence={"resolution": {"escalation_reason": "solicitó agente"}},
        tools_involved=["get_order_status"],
        escalated=True,
        message_count=12,
    )


def _conv(cid="conv-1"):
    return {
        "id": cid,
        "messages": [
            {"source": "customer", "text_body": "Hola, mi orden 12345678 no llega, mi correo es a@b.com"},
            {"source": "ai_agent", "text_body": "Déjeme revisar su orden"},
            {"source": "customer", "text_body": "quiero hablar con un agente"},
        ],
    }


class TestSeedConversion:
    def test_seed_fields(self):
        seed = production_failure_to_seed(_failure(), _conv())
        assert seed.trace_id == "conv-1"
        assert seed.failure_category == "resolution_failure"
        assert seed.outcome == "escalation"
        assert seed.tool_sequence == ["get_order_status"]
        assert seed.severity == "high"
        assert len(seed.conversation_snippet) == 3

    def test_seed_is_anonymised(self):
        seed = production_failure_to_seed(_failure(), _conv())
        joined = seed.user_goal_inferred + " ".join(
            t["content"] for t in seed.conversation_snippet
        )
        assert "a@b.com" not in joined
        assert "12345678" not in joined

    def test_primary_category_is_highest_severity(self):
        failure = _failure(
            categories=["loop_stall", "hallucination"],
            shared=["infinite_loop", "hallucination"],
        )
        seed = production_failure_to_seed(failure, _conv())
        assert seed.failure_category == "hallucination"  # high > medium


class TestCorpus:
    def test_per_category_cap(self):
        failures = [
            _failure(cid=f"c{i}", score=float(i)) for i in range(30)
        ]
        convs = [_conv(cid=f"c{i}") for i in range(30)]
        corpus, prov = build_feedback_corpus(failures, convs, per_category_cap=10)
        assert corpus.total_seeds == 10
        # Highest scores kept
        kept = sorted(prov.values())
        assert "c29" in kept and "c0" not in kept

    def test_provenance_maps_to_conversations(self):
        corpus, prov = build_feedback_corpus([_failure()], [_conv()])
        assert prov == {"prod_conv-1": "conv-1"}


class TestSuites:
    def test_blind_suite_has_no_production_data(self):
        suite = generate_blind_suite(AGENT_MAP, target_count=20)
        assert len(suite.test_cases) == 20
        assert all(t.scenario.source != "production_seed" for t in suite.test_cases)

    def test_feedback_suite_contains_seeds_within_budget(self):
        failures = [_failure(cid=f"c{i}") for i in range(10)]
        convs = [_conv(cid=f"c{i}") for i in range(10)]
        corpus, prov = build_feedback_corpus(failures, convs)
        suite, used = generate_feedback_suite(
            AGENT_MAP, corpus, prov, target_count=20, seed_budget_fraction=0.3,
        )
        assert len(suite.test_cases) == 20
        seed_tests = [t for t in suite.test_cases if t.coverage_goal == "production_seed"]
        assert 1 <= len(seed_tests) <= 6  # 30% of 20
        assert used == {f"c{i}" for i in range(10)}

    def test_reproducible_with_same_seed(self):
        s1 = generate_blind_suite(AGENT_MAP, target_count=10, rng_seed=7)
        s2 = generate_blind_suite(AGENT_MAP, target_count=10, rng_seed=7)
        # IDs are fresh UUIDs per invocation; the pairing structure is what
        # reproducibility guarantees.
        ids1 = [(t.scenario.title, t.persona.name) for t in s1.test_cases]
        ids2 = [(t.scenario.title, t.persona.name) for t in s2.test_cases]
        assert ids1 == ids2


class TestLeakageGuard:
    def test_clean_passes(self):
        verify_no_leakage({"c1", "c2"}, [_failure(cid="c9")])

    def test_leak_raises(self):
        with pytest.raises(LeakageError, match="c1"):
            verify_no_leakage({"c1"}, [_failure(cid="c1")])
