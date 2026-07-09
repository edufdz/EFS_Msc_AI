"""
Tests for the guardrail compliance/violation test-pair generator (Sprint E11).

Covers: per-rule compliance+violation pair generation, complexity-based
variant scaling, conditional-rule condition-met/not-met tests, oracle
attachment (compliance→GUARDRAIL_COMPLIANCE, violation→GUARDRAIL_VIOLATION),
language-mismatch + code-switch provocations, language/formality invariance
metamorphic relations, naturalisation fallback, and ScenarioLibrary /
graceful-degradation integration for maps without guardrails.
"""

from __future__ import annotations

import pytest

from src.oracles.models import OracleType
from src.scenarios.guardrail_pairs import (
    _variant_counts,
    generate_guardrail_test_pairs,
    generate_language_invariance_pairs,
    naturalise_provocations,
)
from src.scenarios.library import ScenarioLibrary


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _agent_map() -> dict:
    """Guardrail-rich map: English rules over a Spanish conversation."""
    return {
        "agent_id": "guardrail-test-agent",
        "metadata": {
            "type": "support",
            "purpose": "Order support agent",
            "conversation_language": "Spanish",
            "language": {
                "primary_language": "Spanish",
                "code_switching_detected": True,
                "spanish_formality": "usted",
            },
        },
        "components": {
            "tools": [
                {"name": "verify_order", "risk_level": "low", "read_only": True},
                {"name": "process_refund", "risk_level": "critical"},
                {"name": "escalate_to_human", "risk_level": "medium"},
                {"name": "get_payment_info", "risk_level": "high"},
            ],
            "prompts": [],
        },
        "guardrails": {
            "rules": [
                {"rule_id": "R001",
                 "text": "Never disclose payment information",
                 "category": "prohibition", "complexity": 1,
                 "scope": "always", "target_tools": ["get_payment_info"],
                 "conditions": []},
                {"rule_id": "R002",
                 "text": "Always confirm before processing a refund",
                 "category": "requirement", "complexity": 2,
                 "scope": "tool_specific", "target_tools": ["process_refund"],
                 "conditions": []},
                {"rule_id": "R003",
                 "text": "If the order is older than 30 days, escalate to a human",
                 "category": "escalation", "complexity": 3,
                 "scope": "conditional",
                 "target_tools": ["escalate_to_human", "process_refund"],
                 "conditions": ["order older than 30 days"]},
                {"rule_id": "R004",
                 "text": "Do not grant discounts above 20 percent",
                 "category": "constraint", "complexity": 5,
                 "scope": "always", "target_tools": [], "conditions": []},
            ],
            "total_rules": 4,
            "guardrail_language_matches_conversation": False,
        },
        "risk_flags": {},
        "behavioural_model": {"dependency_graph": {"edges": []}},
    }


def _no_guardrails_map() -> dict:
    return {
        "agent_id": "bare-agent",
        "metadata": {"type": "custom", "purpose": "bare"},
        "components": {"tools": [{"name": "track_order", "risk_level": "low"}]},
    }


def _matching_language_map() -> dict:
    """English rules over an English conversation, no code switching."""
    m = _agent_map()
    m["metadata"]["conversation_language"] = "English"
    m["metadata"]["language"] = {
        "primary_language": "English",
        "code_switching_detected": False,
        "spanish_formality": None,
    }
    m["guardrails"]["guardrail_language_matches_conversation"] = True
    return m


# ---------------------------------------------------------------------------
# Complexity scaling
# ---------------------------------------------------------------------------

class TestVariantCounts:
    @pytest.mark.parametrize("complexity,expected", [
        (1, (1, 1)), (2, (1, 2)), (3, (2, 2)), (4, (2, 3)), (5, (2, 3)),
    ])
    def test_counts(self, complexity, expected):
        assert _variant_counts(complexity) == expected


# ---------------------------------------------------------------------------
# E11.1 — Pair generation
# ---------------------------------------------------------------------------

class TestGeneratePairs:
    def test_no_guardrails_returns_empty(self):
        assert generate_guardrail_test_pairs(_no_guardrails_map()) == []
        assert generate_guardrail_test_pairs({}) == []

    def test_every_rule_has_compliance_and_violation(self):
        scenarios = generate_guardrail_test_pairs(_agent_map())
        for rule_id in ("R001", "R002", "R003", "R004"):
            for_rule = [s for s in scenarios if rule_id in s.tags]
            comp = [s for s in for_rule if s.source == "guardrail_compliance"]
            viol = [s for s in for_rule if s.source == "guardrail_violation"]
            assert comp, f"{rule_id} missing compliance test"
            assert viol, f"{rule_id} missing violation test"

    def test_complexity_scales_variants(self):
        scenarios = generate_guardrail_test_pairs(_agent_map())
        # R001 complexity 1 → 1 compliance + 1 violation (+1 code-switch)
        r1_comp = [s for s in scenarios
                   if "R001" in s.tags and s.source == "guardrail_compliance"]
        assert len(r1_comp) == 1
        # R004 complexity 5 → 2 compliance + 3 violations
        r4_comp = [s for s in scenarios
                   if "R004" in s.tags and s.source == "guardrail_compliance"]
        r4_viol = [s for s in scenarios
                   if "R004" in s.tags and s.source == "guardrail_violation"]
        assert len(r4_comp) == 2
        # 3 base violations + 1 code-switch (code_switching_detected=True)
        assert len([s for s in r4_viol if "code_switching" not in s.tags]) == 3

    def test_titles_and_types(self):
        scenarios = generate_guardrail_test_pairs(_agent_map())
        comp = next(s for s in scenarios if s.source == "guardrail_compliance")
        viol = next(s for s in scenarios if s.source == "guardrail_violation")
        assert comp.title.startswith("Compliance:")
        assert comp.type == "happy_path"
        viol_r = next(s for s in scenarios
                      if s.source == "guardrail_violation" and "R001" in s.tags)
        assert viol_r.title.startswith("Violation:")
        assert viol_r.type == "error_path"
        assert viol_r.difficulty == "hard"
        assert "adversarial" in viol_r.tags

    def test_violation_tags_have_category(self):
        scenarios = generate_guardrail_test_pairs(_agent_map())
        viol = next(s for s in scenarios
                    if s.source == "guardrail_violation" and "R001" in s.tags)
        assert "prohibition" in viol.tags

    def test_pii_rule_sets_failure_condition(self):
        scenarios = generate_guardrail_test_pairs(_agent_map())
        viol = next(s for s in scenarios
                    if s.source == "guardrail_violation" and "R001" in s.tags)
        # R001 is about payment info → pii_leaked failure condition
        assert viol.failure_conditions.pii_leaked is True


# ---------------------------------------------------------------------------
# Oracle attachment
# ---------------------------------------------------------------------------

class TestOracleAttachment:
    def test_compliance_gets_compliance_oracle(self):
        scenarios = generate_guardrail_test_pairs(_agent_map())
        comp = next(s for s in scenarios
                    if s.source == "guardrail_compliance" and "R001" in s.tags)
        assert comp.oracles
        assert all(o.oracle_type == OracleType.GUARDRAIL_COMPLIANCE
                   for o in comp.oracles)
        assert "R001" in comp.oracles[0].applies_to_rules

    def test_violation_gets_violation_oracle(self):
        scenarios = generate_guardrail_test_pairs(_agent_map())
        viol = next(s for s in scenarios
                    if s.source == "guardrail_violation" and "R002" in s.tags)
        assert viol.oracles
        assert all(o.oracle_type == OracleType.GUARDRAIL_VIOLATION
                   for o in viol.oracles)
        assert "R002" in viol.oracles[0].applies_to_rules


# ---------------------------------------------------------------------------
# Conditional rules (E11.1.4)
# ---------------------------------------------------------------------------

class TestConditionalRules:
    def test_condition_met_and_not_met(self):
        scenarios = generate_guardrail_test_pairs(_agent_map())
        r3 = [s for s in scenarios if "R003" in s.tags]
        met = [s for s in r3 if "condition_met" in s.tags]
        not_met = [s for s in r3 if "condition_not_met" in s.tags]
        assert met, "conditional rule missing condition-met test"
        assert not_met, "conditional rule missing condition-not-met test"
        assert all("conditional" in s.tags for s in met + not_met)

    def test_non_conditional_rule_has_no_conditional_tests(self):
        scenarios = generate_guardrail_test_pairs(_agent_map())
        r1 = [s for s in scenarios if "R001" in s.tags]
        assert not any("conditional" in s.tags for s in r1)


# ---------------------------------------------------------------------------
# E11.2 — Language mismatch & code switching
# ---------------------------------------------------------------------------

class TestLanguageMismatch:
    def test_mismatch_tags_violations(self):
        scenarios = generate_guardrail_test_pairs(_agent_map(), language="Spanish")
        violations = [s for s in scenarios if s.source == "guardrail_violation"]
        assert all("language_mismatch" in s.tags for s in violations)

    def test_matching_language_no_mismatch_tag(self):
        scenarios = generate_guardrail_test_pairs(
            _matching_language_map(), language="English")
        violations = [s for s in scenarios if s.source == "guardrail_violation"]
        assert all("language_mismatch" not in s.tags for s in violations)

    def test_code_switch_provocation_present(self):
        scenarios = generate_guardrail_test_pairs(_agent_map())
        cs = [s for s in scenarios if "code_switching" in s.tags]
        # one per rule (4 rules)
        assert len(cs) == 4
        assert all(s.source == "guardrail_violation" for s in cs)
        # goal actually mixes languages
        assert any("please" in s.user_goal.lower() and "hola" in s.user_goal.lower()
                   for s in cs)

    def test_no_code_switch_when_not_detected(self):
        scenarios = generate_guardrail_test_pairs(_matching_language_map())
        assert not any("code_switching" in s.tags for s in scenarios)


# ---------------------------------------------------------------------------
# E11.3 — Metamorphic relations
# ---------------------------------------------------------------------------

class TestMetamorphicRelations:
    def test_language_invariance_per_compliance(self):
        scenarios = generate_guardrail_test_pairs(_agent_map())
        relations = generate_language_invariance_pairs(
            scenarios, _agent_map(), language="Spanish")
        comp = [s for s in scenarios if s.source == "guardrail_compliance"]
        lang = [r for r in relations if r.source == "language_invariance"]
        assert len(lang) == len(comp)
        assert all(r.mutant_scenario_id.endswith("::language_invariance")
                   for r in lang)

    def test_formality_invariance_for_spanish(self):
        scenarios = generate_guardrail_test_pairs(_agent_map())
        relations = generate_language_invariance_pairs(
            scenarios, _agent_map(), language="Spanish")
        form = [r for r in relations if r.source == "formality_invariance"]
        assert form, "expected formality invariance relations for Spanish"

    def test_no_formality_for_english(self):
        scenarios = generate_guardrail_test_pairs(
            _matching_language_map(), language="English")
        relations = generate_language_invariance_pairs(
            scenarios, _matching_language_map(), language="English")
        assert not [r for r in relations if r.source == "formality_invariance"]


# ---------------------------------------------------------------------------
# E11.4 — Naturalisation
# ---------------------------------------------------------------------------

class _FakeLLM:
    def __init__(self, goal="Naturalised customer message"):
        self.goal = goal
        self.calls = 0

    def create_sync_client(self):
        return object()

    def call_sync(self, client, prompt, max_tokens=512, temperature=0.8):
        self.calls += 1
        import json
        return json.dumps({"user_goal": self.goal}), 10, 5


class _BrokenLLM:
    def create_sync_client(self):
        raise RuntimeError("offline")

    def call_sync(self, *a, **k):
        raise RuntimeError("offline")


class TestNaturalisation:
    def test_none_llm_returns_unchanged(self):
        scenarios = generate_guardrail_test_pairs(_agent_map())
        out = naturalise_provocations(scenarios, _agent_map(), None)
        assert out == scenarios

    def test_only_violations_rewritten(self):
        scenarios = generate_guardrail_test_pairs(_agent_map())
        llm = _FakeLLM()
        out = naturalise_provocations(scenarios, _agent_map(), llm)
        for orig, new in zip(scenarios, out):
            if orig.source == "guardrail_violation":
                assert new.user_goal == "Naturalised customer message"
            else:
                assert new.user_goal == orig.user_goal

    def test_broken_llm_degrades_gracefully(self):
        scenarios = generate_guardrail_test_pairs(_agent_map())
        out = naturalise_provocations(scenarios, _agent_map(), _BrokenLLM())
        viol = [s for s in out if s.source == "guardrail_violation"]
        # original structural goals preserved
        assert all(s.user_goal for s in viol)


# ---------------------------------------------------------------------------
# E11.5 — ScenarioLibrary integration
# ---------------------------------------------------------------------------

class TestLibraryIntegration:
    def test_generate_guardrail_pairs_appends(self):
        lib = ScenarioLibrary(_agent_map(), language="Spanish")
        pairs = lib.generate_guardrail_pairs(naturalise=False)
        assert pairs
        assert all(p in lib.scenarios for p in pairs)
        # every rule covered
        covered = {t for p in pairs for t in p.tags} & {"R001", "R002", "R003", "R004"}
        assert covered == {"R001", "R002", "R003", "R004"}

    def test_metamorphic_relations_attached(self):
        lib = ScenarioLibrary(_agent_map(), language="Spanish")
        pairs = lib.generate_guardrail_pairs(naturalise=False)
        comp = [p for p in pairs if p.source == "guardrail_compliance"]
        assert any(p.metamorphic_relations for p in comp)

    def test_count_limit_caps(self):
        lib = ScenarioLibrary(_agent_map(), language="Spanish")
        pairs = lib.generate_guardrail_pairs(count_limit=3, naturalise=False)
        assert len(pairs) == 3

    def test_no_guardrails_returns_empty(self):
        lib = ScenarioLibrary(_no_guardrails_map(), language="English")
        assert lib.generate_guardrail_pairs(naturalise=False) == []

    def test_attach_oracles_still_works_after_pairs(self):
        # Full-pipeline behaviour: attach_oracles runs after guardrail pairs
        lib = ScenarioLibrary(_agent_map(), language="Spanish")
        lib.generate_guardrail_pairs(naturalise=False)
        counts = lib.attach_oracles()
        assert counts["oracles"] > 0
