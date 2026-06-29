"""
Sprint 9 — Unit tests for multilingual/domain metadata detection.

Tests _detect_language_metadata, _detect_domain_metadata, and _score_language
from src/graph/builder.py.
"""

from __future__ import annotations

import sys
import os
import pytest

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from src.patterns.detector import PromptDefinition, ToolDefinition
from src.graph.builder import _detect_language_metadata, _detect_domain_metadata, _score_language


# ── Helpers ──

def _make_prompt(content: str, name: str = "system") -> PromptDefinition:
    return PromptDefinition(name=name, type="system_prompt", content=content)


def _make_tool(name: str, description: str = "") -> ToolDefinition:
    return ToolDefinition(
        id=name.lower().replace(" ", "_"),
        name=name,
        description=description,
        parameters=[],
        source="test",
        location={},
    )


# ── _score_language ──

class TestScoreLanguage:
    def test_counts_word_matches(self):
        text = "hola cliente bienvenido al servicio"
        score = _score_language(text, ["hola", "cliente", "bienvenido", "servicio"])
        assert score == 4

    def test_counts_extra_chars(self):
        text = "¿cómo está usted?"
        score = _score_language(text, [], extra_chars=["¿", "á"])
        assert score == 2

    def test_no_matches_returns_zero(self):
        assert _score_language("hello world", ["hola", "gracias"]) == 0

    def test_repeated_words_counted(self):
        text = "cliente y cliente y cliente"
        score = _score_language(text, ["cliente"])
        assert score == 3


# ── _detect_language_metadata: primary language ──

class TestPrimaryLanguage:
    def test_spanish_prompt(self):
        prompts = [_make_prompt(
            "Bienvenido al servicio de atención al cliente. "
            "Estamos aquí para ayuda con su consulta. Gracias por contactarnos."
        )]
        result = _detect_language_metadata(prompts)
        assert result["primary_language"] == "Spanish"
        assert "Spanish" in result["conversation_languages"]

    def test_english_prompt(self):
        prompts = [_make_prompt(
            "Welcome to our customer support service. "
            "We are here to help you with your problem. Thank you for contacting us."
        )]
        result = _detect_language_metadata(prompts)
        assert result["primary_language"] == "English"
        assert "English" in result["conversation_languages"]

    def test_portuguese_prompt(self):
        prompts = [_make_prompt(
            "Obrigado por entrar em contato com nosso serviço de atendimento. "
            "Estamos disponível para ajuda com sua consulta e agendamento."
        )]
        result = _detect_language_metadata(prompts)
        assert result["primary_language"] == "Portuguese"
        assert "Portuguese" in result["conversation_languages"]

    def test_empty_prompts_default_english(self):
        result = _detect_language_metadata([])
        assert result["primary_language"] == "English"
        assert result["confidence"] == 0.5

    def test_empty_content_default_english(self):
        prompts = [_make_prompt("")]
        result = _detect_language_metadata(prompts)
        assert result["primary_language"] == "English"


# ── Code-switching detection ──

class TestCodeSwitching:
    def test_mixed_spanish_english(self):
        prompts = [_make_prompt(
            "Welcome to our customer support service, please help. "
            "El cliente necesita ayuda con su problema y consulta. "
            "Thank you for your available solution and shipping status. "
            "Bienvenido al servicio de atención y soporte."
        )]
        result = _detect_language_metadata(prompts)
        assert result["code_switching_detected"] is True

    def test_single_language_no_code_switching(self):
        prompts = [_make_prompt(
            "Bienvenido al servicio de atención al cliente. "
            "Estamos aquí para ayuda con su consulta. Gracias."
        )]
        result = _detect_language_metadata(prompts)
        assert result["code_switching_detected"] is False


# ── Spanish formality ──

class TestSpanishFormality:
    def test_usted_form(self):
        prompts = [_make_prompt(
            "Estimado cliente, bienvenido al servicio. "
            "Le informamos que su consulta está siendo procesada. Gracias."
        )]
        result = _detect_language_metadata(prompts)
        assert result["spanish_formality"] == "usted"

    def test_tu_form(self):
        prompts = [_make_prompt(
            "Hola, bienvenido al servicio de ayuda. "
            "Tú puedes consultar tu estado aquí. ¿Quieres más información?"
        )]
        result = _detect_language_metadata(prompts)
        assert result["spanish_formality"] == "tú"

    def test_mixed_formality(self):
        prompts = [_make_prompt(
            "Estimado cliente, bienvenido al servicio de ayuda. "
            "Tú puedes consultar tu estado. Le informamos que está listo. Gracias."
        )]
        result = _detect_language_metadata(prompts)
        assert result["spanish_formality"] == "mixed"

    def test_english_no_formality(self):
        prompts = [_make_prompt(
            "Welcome to our customer support service. "
            "We are here to help you with your problem."
        )]
        result = _detect_language_metadata(prompts)
        assert result["spanish_formality"] is None


# ── Guardrail language mismatch ──

class TestGuardrailMismatch:
    def test_english_rules_spanish_conversation(self):
        prompts = [_make_prompt(
            "Bienvenido al servicio de atención al cliente. "
            "Estamos aquí para ayuda con su consulta. Gracias."
        )]
        guardrail_rules = [
            "Never share customer data with third parties",
            "Always confirm the customer identity before changes",
            "Support agents must help resolve the problem",
        ]
        result = _detect_language_metadata(prompts, guardrail_rules)
        assert result["primary_language"] == "Spanish"
        assert result["guardrail_language"] == "English"
        assert result["language_mismatch"] is True

    def test_matching_languages_no_mismatch(self):
        prompts = [_make_prompt(
            "Bienvenido al servicio de atención al cliente. "
            "Estamos aquí para ayuda con su consulta. Gracias."
        )]
        guardrail_rules = [
            "Nunca compartir información del cliente",
            "Siempre confirmar la solución con el cliente",
        ]
        result = _detect_language_metadata(prompts, guardrail_rules)
        assert result["language_mismatch"] is False

    def test_no_guardrail_rules_defaults_to_primary(self):
        prompts = [_make_prompt(
            "Bienvenido al servicio de atención al cliente. "
            "Estamos aquí para ayuda con su consulta. Gracias."
        )]
        result = _detect_language_metadata(prompts, guardrail_rules=None)
        assert result["guardrail_language"] == result["primary_language"]
        assert result["language_mismatch"] is False


# ── Confidence ──

class TestConfidence:
    def test_high_signal_high_confidence(self):
        prompts = [_make_prompt(
            "Bienvenido al servicio de atención al cliente. "
            "Estamos aquí para ayuda con su consulta y reserva. "
            "Gracias por contactarnos. Le informamos sobre su pedido, "
            "factura, devolución, garantía, reparación, soporte e información."
        )]
        result = _detect_language_metadata(prompts)
        assert result["confidence"] >= 0.5

    def test_empty_prompt_low_confidence(self):
        result = _detect_language_metadata([_make_prompt("")])
        assert result["confidence"] == 0.5


# ── _detect_domain_metadata ──

class TestDomainDetection:
    def test_customer_support_domain(self):
        tools = [_make_tool("create_ticket", "Create a support ticket for complaint")]
        prompts = [_make_prompt("You are a helpdesk agent providing soporte.")]
        result = _detect_domain_metadata(tools, prompts)
        assert result["type"] == "customer_support"

    def test_sales_domain(self):
        tools = [_make_tool("process_order", "Process a purchase order")]
        prompts = [_make_prompt("Help the customer complete their product purchase at the best price.")]
        result = _detect_domain_metadata(tools, prompts)
        assert result["type"] == "sales"

    def test_scheduling_domain(self):
        tools = [_make_tool("book_appointment", "Book a calendar appointment")]
        prompts = [_make_prompt("Schedule the booking for the customer's reserva.")]
        result = _detect_domain_metadata(tools, prompts)
        assert result["type"] == "scheduling"

    def test_whatsapp_channel(self):
        tools = [_make_tool("send_whatsapp_message", "Send a WhatsApp message")]
        prompts = [_make_prompt("You are a support agent.")]
        result = _detect_domain_metadata(tools, prompts)
        assert result["channel"] == "whatsapp"

    def test_consumer_electronics_industry(self):
        tools = [_make_tool("check_warranty", "Check device warranty status")]
        prompts = [_make_prompt("Help with TechRepair phone issues and garantía.")]
        result = _detect_domain_metadata(tools, prompts)
        assert result["industry"] == "consumer_electronics"

    def test_no_signals_returns_none(self):
        tools = [_make_tool("do_thing", "Does a thing")]
        prompts = [_make_prompt("You are an agent.")]
        result = _detect_domain_metadata(tools, prompts)
        assert result["type"] is None
        assert result["industry"] is None
        assert result["channel"] is None

    def test_detected_from_field(self):
        result = _detect_domain_metadata([], [])
        assert result["detected_from"] == "tool_names_and_prompts"


# ── Multiple prompts ──

class TestMultiplePrompts:
    def test_language_across_multiple_prompts(self):
        prompts = [
            _make_prompt("Bienvenido al servicio."),
            _make_prompt("Estamos aquí para ayuda con su consulta."),
            _make_prompt("Gracias por contactarnos, cliente."),
        ]
        result = _detect_language_metadata(prompts)
        assert result["primary_language"] == "Spanish"

    def test_domain_across_tools_and_prompts(self):
        tools = [_make_tool("create_ticket")]
        prompts = [_make_prompt("Handle the complaint via WhatsApp support.")]
        result = _detect_domain_metadata(tools, prompts)
        assert result["type"] == "customer_support"
        assert result["channel"] == "whatsapp"
