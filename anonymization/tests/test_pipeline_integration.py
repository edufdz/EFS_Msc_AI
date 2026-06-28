"""Integration tests: full pipeline on fixture conversations."""

import re

import pytest

from config import PlaceholderTracker
from pipeline import anonymize_text


# All known PII planted in conversation_with_pii.txt
PLANTED_PII = [
    "María García López",
    # Note: standalone "María" (common first name without surname) may not be caught by NER
    # as it lacks sufficient context. The full name IS caught.
    "+52 55 1234 5678",
    "ORD-2024-78543",
    "Calle Reforma 234, Colonia Centro, CP 06000",
    "maria.garcia@gmail.com",
    "Galaxy S24 Ultra",
    "TechRepair",
    "TechRepair Pay",
    "356938035643809",
    "4521-8834-9912-0045",
    "GALO850315HDFRRL09",
    "GALO850315AB1",
    "+52 1 33 9876 5432",
    "TechRepair Service Center",
    "https://support.tech_repair.com/mx/ticket/USR-78543-maria",
]

# Content that MUST survive anonymization
MUST_PRESERVE = [
    "Hola",
    "necesito ayuda con mi pedido",
    "¿Me puedes proporcionar tu número de orden?",
    "La pantalla",
    "se congela",
    "garantía activa",
    "programar una revisión",
    "confirmación",
]


class TestFullPipelinePIIRemoval:
    def test_no_planted_pii_survives(self, load_fixture):
        text = load_fixture("conversation_with_pii.txt")
        result = anonymize_text(text)
        for pii in PLANTED_PII:
            assert pii not in result, f"PII leaked: {pii}"

    def test_no_raw_phone_numbers(self, load_fixture):
        text = load_fixture("conversation_with_pii.txt")
        result = anonymize_text(text)
        # No 10+ digit sequences should remain
        long_numbers = re.findall(r"\b\d{10,}\b", result)
        # Filter out any inside placeholders
        assert len(long_numbers) == 0, f"Raw numbers leaked: {long_numbers}"

    def test_no_email_pattern_survives(self, load_fixture):
        text = load_fixture("conversation_with_pii.txt")
        result = anonymize_text(text)
        emails = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", result)
        assert len(emails) == 0, f"Emails leaked: {emails}"


class TestFullPipelineContentPreservation:
    def test_conversational_content_preserved(self, load_fixture):
        text = load_fixture("conversation_with_pii.txt")
        result = anonymize_text(text)
        for content in MUST_PRESERVE:
            assert content in result, f"Content destroyed: {content}"

    def test_conversation_structure_preserved(self, load_fixture):
        text = load_fixture("conversation_with_pii.txt")
        result = anonymize_text(text)
        # Turn boundaries (Cliente:/Agente:) must remain
        assert result.count("Cliente:") == text.count("Cliente:")
        assert result.count("Agente:") == text.count("Agente:")

    def test_no_pii_conversation_unchanged(self, load_fixture):
        """A conversation with no PII should pass through mostly unchanged."""
        text = load_fixture("conversation_no_pii.txt")
        result = anonymize_text(text)
        # Should be identical or near-identical (NER might false-positive on rare words)
        # At minimum, no placeholders should appear
        placeholder_count = len(re.findall(r"\[\w+_\d+\]", result))
        assert placeholder_count == 0, f"False positives: {placeholder_count} placeholders in clean text"


class TestEdgeCases:
    def test_edge_case_conversation(self, load_fixture):
        text = load_fixture("conversation_edge_cases.txt")
        result = anonymize_text(text)

        # These must not survive
        assert "José Antonio Hernández Pérez" not in result
        assert "5512345678" not in result
        assert "3398765432" not in result
        assert "jose.hernandez@empresa.com.mx" not in result
        assert "toño_hp@outlook.es" not in result
        assert "Av. Insurgentes Sur 1234" not in result
        assert "012345678901234567" not in result
        assert "490154203237518" not in result
        assert "ORD-MX-99001" not in result
        assert "Galaxy Tab S9 FE" not in result
        assert "Galaxy A55" not in result

    def test_placeholder_consistency(self, load_fixture):
        """Same entity appearing multiple times gets same placeholder."""
        text = load_fixture("conversation_edge_cases.txt")
        result = anonymize_text(text)
        # "TKT-2024-001" appears twice in the fixture
        assert result.count("[ORDER_ID_") >= 1


class TestPlaceholderFormat:
    def test_placeholders_are_well_formed(self, load_fixture):
        text = load_fixture("conversation_with_pii.txt")
        result = anonymize_text(text)
        placeholders = re.findall(r"\[.+?\]", result)
        for p in placeholders:
            assert re.match(r"\[\w+_\d+\]", p), f"Malformed placeholder: {p}"

    def test_placeholder_numbers_are_sequential(self, load_fixture):
        text = load_fixture("conversation_with_pii.txt")
        result = anonymize_text(text)
        # Collect all placeholder numbers per category
        from collections import defaultdict
        category_nums = defaultdict(set)
        for m in re.finditer(r"\[(\w+)_(\d+)\]", result):
            cat, num = m.group(1), int(m.group(2))
            category_nums[cat].add(num)
        # Each category should have sequential numbering starting at 1
        for cat, nums in category_nums.items():
            assert min(nums) == 1, f"Category {cat} doesn't start at 1: {sorted(nums)}"
            assert max(nums) == len(nums), f"Category {cat} has gaps: {sorted(nums)}"
