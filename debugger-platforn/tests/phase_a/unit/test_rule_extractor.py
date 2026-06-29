"""Unit tests for rule_extractor.py — Sprint 6 (guardrail extraction)."""

import pytest

from src.patterns.rule_extractor import (
    PolicyRule,
    PolicyGraph,
    extract_rules_from_text,
    extract_rules_from_prompts,
)


class TestRuleExtraction:
    def test_numbered_rules(self):
        text = "1. Never share data.\n2. Always verify identity."
        rules = extract_rules_from_text(text)
        assert len(rules) >= 2

    def test_bullet_rules(self):
        text = "- Never share customer data.\n- Always verify identity."
        rules = extract_rules_from_text(text)
        assert len(rules) >= 2

    def test_prohibition_category(self):
        rules = extract_rules_from_text("1. Never disclose payment details.")
        assert len(rules) >= 1
        assert rules[0].category == "prohibition"

    def test_requirement_category(self):
        rules = extract_rules_from_text("1. Always verify the customer's identity.")
        assert len(rules) >= 1
        assert rules[0].category == "requirement"

    def test_escalation_category(self):
        rules = extract_rules_from_text("1. If unable to resolve, escalate to a human agent.")
        assert len(rules) >= 1
        assert any(r.category == "escalation" for r in rules)

    def test_fallback_category(self):
        rules = extract_rules_from_text("1. When in doubt, default to the lower estimate.")
        assert len(rules) >= 1
        assert any(r.category == "fallback" for r in rules)

    def test_constraint_category(self):
        rules = extract_rules_from_text("1. Only provide information about the customer's own orders.")
        assert len(rules) >= 1
        assert rules[0].category == "constraint"

    def test_empty_text_returns_empty(self):
        rules = extract_rules_from_text("")
        assert rules == []

    def test_short_text_returns_empty(self):
        rules = extract_rules_from_text("Hello")
        assert rules == []

    def test_rule_ids_sequential(self):
        text = "1. Never share data.\n2. Always verify.\n3. Must respond quickly."
        rules = extract_rules_from_text(text)
        ids = [r.rule_id for r in rules]
        assert ids[0] == "R001"
        if len(ids) > 1:
            assert ids[1] == "R002"


class TestSpanishRules:
    def test_spanish_prohibition(self):
        rules = extract_rules_from_text("1. Nunca compartas datos del cliente.")
        assert len(rules) >= 1
        assert rules[0].category == "prohibition"

    def test_spanish_requirement(self):
        rules = extract_rules_from_text("1. Siempre verifica la identidad del cliente.")
        assert len(rules) >= 1
        assert rules[0].category == "requirement"

    def test_spanish_language_detected(self):
        rules = extract_rules_from_text(
            "1. Nunca compartas datos del cliente.\n"
            "2. Siempre verifica la identidad del usuario."
        )
        assert all(r.language == "Spanish" for r in rules)

    def test_spanish_escalation(self):
        rules = extract_rules_from_text("- Si no puede resolver el problema, escalar a un agente humano.")
        assert len(rules) >= 1
        assert any(r.category in ("escalation", "prohibition") for r in rules)


class TestComplexityScoring:
    def test_simple_rule_is_1(self):
        rules = extract_rules_from_text("1. Never share customer data.")
        assert rules[0].complexity == 1

    def test_conditional_rule_is_2_or_higher(self):
        rules = extract_rules_from_text("1. If the customer is upset, apologize first.")
        assert len(rules) >= 1
        assert rules[0].complexity >= 2

    def test_exception_rule_is_4_or_higher(self):
        rules = extract_rules_from_text(
            "1. Do not process refunds for orders older than 30 days, except for premium customers."
        )
        assert len(rules) >= 1
        assert rules[0].complexity >= 4

    def test_sequential_rule_is_5(self):
        rules = extract_rules_from_text(
            "1. First check order status, then verify payment, finally process refund."
        )
        assert len(rules) >= 1
        assert rules[0].complexity == 5


class TestScopeDetection:
    def test_tool_specific_scope(self):
        rules = extract_rules_from_text(
            "1. When using refund_order, always verify the order first.",
            tool_names=["refund_order", "search"],
        )
        assert len(rules) >= 1
        assert rules[0].scope == "tool_specific"
        assert "refund_order" in rules[0].target_tools

    def test_conditional_scope(self):
        rules = extract_rules_from_text("1. If the customer is angry, apologize first.")
        assert len(rules) >= 1
        assert rules[0].scope == "conditional"

    def test_always_scope(self):
        rules = extract_rules_from_text("1. Never share customer data.")
        assert rules[0].scope == "always"


class TestConditionExtraction:
    def test_if_condition_extracted(self):
        rules = extract_rules_from_text("1. If the order is older than 30 days, escalate.")
        assert len(rules) >= 1
        assert len(rules[0].conditions) >= 1

    def test_when_condition_extracted(self):
        rules = extract_rules_from_text("1. When in doubt about the amount, ask for clarification.")
        assert len(rules) >= 1
        assert len(rules[0].conditions) >= 1


class TestExtractFromPrompts:
    def test_extracts_from_prompt_definitions(self):
        """Test using mock PromptDefinition objects."""

        class MockPrompt:
            def __init__(self, name, content):
                self.name = name
                self.content = content
                self.location = {"file": "test.py", "line": 1}

        prompts = [
            MockPrompt("system", "1. Never share data.\n2. Always verify identity."),
            MockPrompt("fallback", "- When in doubt, ask for help."),
        ]
        graph = extract_rules_from_prompts(prompts)
        assert isinstance(graph, PolicyGraph)
        assert graph.total_complexity > 0
        assert len(graph.rules) >= 3
        # IDs should be sequential across prompts
        ids = [r.rule_id for r in graph.rules]
        assert ids[0] == "R001"
