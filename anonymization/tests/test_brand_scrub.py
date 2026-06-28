"""Tests for brand term generalization."""

import pytest

from config import PlaceholderTracker
from brand_scrub import brand_anonymize


class TestBrandReplacement:
    def test_brand_name_replaced(self):
        tracker = PlaceholderTracker()
        text = "Mi dispositivo TechRepair no enciende"
        result = brand_anonymize(text, tracker)
        assert "TechRepair" not in result
        assert "[BRAND_" in result

    def test_device_name_replaced(self):
        tracker = PlaceholderTracker()
        text = "Compré un Galaxy S24 Ultra nuevo"
        result = brand_anonymize(text, tracker)
        assert "Galaxy S24 Ultra" not in result
        assert "[DEVICE_" in result

    def test_compound_term_matched_before_substring(self):
        """'Galaxy S24 Ultra' should match as one unit, not 'Galaxy' separately."""
        tracker = PlaceholderTracker()
        text = "El Galaxy S24 Ultra tiene buena cámara"
        result = brand_anonymize(text, tracker)
        # Should be a single device placeholder, not brand + leftover
        assert "S24" not in result
        assert "Ultra" not in result or "[DEVICE_" in result

    def test_service_name_replaced(self):
        tracker = PlaceholderTracker()
        text = "Ve al TechRepair Service Center más cercano"
        result = brand_anonymize(text, tracker)
        assert "TechRepair Service Center" not in result

    def test_multiple_brand_terms(self):
        tracker = PlaceholderTracker()
        text = "El TechRepair Galaxy A55 funciona con TechRepair Pay"
        result = brand_anonymize(text, tracker)
        assert "TechRepair" not in result
        assert "Galaxy A55" not in result
        assert "TechRepair Pay" not in result


class TestBrandPreservesContent:
    def test_non_brand_text_unchanged(self):
        tracker = PlaceholderTracker()
        text = "La garantía estándar dura 12 meses para todos los dispositivos."
        result = brand_anonymize(text, tracker)
        # Generic words should not be scrubbed
        assert "garantía" in result
        assert "dispositivos" in result

    def test_does_not_scrub_inside_existing_placeholders(self):
        tracker = PlaceholderTracker()
        text = "El [PHONE_1] es de la tienda TechRepair"
        result = brand_anonymize(text, tracker)
        assert "[PHONE_1]" in result
