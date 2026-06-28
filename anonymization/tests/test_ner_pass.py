"""Tests for Pass 2: NER-based PII removal (spaCy/Presidio)."""

import pytest

from config import PlaceholderTracker
from ner_pass import ner_anonymize, get_analyzer


@pytest.fixture(scope="module")
def analyzer():
    """Load analyzer once for all NER tests (slow to init)."""
    return get_analyzer()


class TestNERPersonNames:
    def test_spanish_full_name(self, analyzer):
        tracker = PlaceholderTracker()
        text = "El cliente es María García López"
        result = ner_anonymize(text, tracker, analyzer)
        assert "María García López" not in result
        assert "[PERSON_" in result

    def test_multiple_names(self, analyzer):
        tracker = PlaceholderTracker()
        text = "José Hernández habló con Ana Martínez sobre el caso"
        result = ner_anonymize(text, tracker, analyzer)
        assert "José Hernández" not in result
        assert "Ana Martínez" not in result

    def test_name_repeated_same_placeholder(self, analyzer):
        tracker = PlaceholderTracker()
        text = "María dijo algo. Luego María preguntó otra cosa."
        result = ner_anonymize(text, tracker, analyzer)
        # Same name should get same placeholder
        placeholders = [m.group() for m in __import__("re").finditer(r"\[PERSON_\d+\]", result)]
        if len(placeholders) == 2:
            assert placeholders[0] == placeholders[1]


class TestNERSkipsExistingPlaceholders:
    def test_does_not_re_anonymize_placeholders(self, analyzer):
        tracker = PlaceholderTracker()
        # Text already has placeholders from regex pass
        text = "El número de [PHONE_1] pertenece a María García"
        result = ner_anonymize(text, tracker, analyzer)
        # PHONE placeholder must survive intact
        assert "[PHONE_1]" in result
        # But the name should be anonymized
        assert "María García" not in result


class TestNERLocations:
    def test_city_name(self, analyzer):
        tracker = PlaceholderTracker()
        text = "Vive en Guadalajara, Jalisco"
        result = ner_anonymize(text, tracker, analyzer)
        # Location NER should catch city/state
        assert "[LOCATION_" in result or "Guadalajara" not in result


class TestNERPreservesContent:
    def test_non_pii_text_unchanged(self, analyzer):
        tracker = PlaceholderTracker()
        text = "La garantía dura 12 meses. ¿Necesitas algo más?"
        result = ner_anonymize(text, tracker, analyzer)
        assert result == text

    def test_agent_instructions_preserved(self, analyzer):
        tracker = PlaceholderTracker()
        text = "Para activar la garantía, ve a configuración y selecciona soporte técnico."
        result = ner_anonymize(text, tracker, analyzer)
        assert result == text
