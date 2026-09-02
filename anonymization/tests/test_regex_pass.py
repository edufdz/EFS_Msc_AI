"""Tests for Pass 1: Regex-based PII removal."""

import re

import pytest

from config import PlaceholderTracker
from regex_pass import regex_anonymize


# ---------------------------------------------------------------------------
# Phone numbers
# ---------------------------------------------------------------------------


class TestPhoneAnonymization:
    def test_mexican_mobile_with_country_code(self):
        tracker = PlaceholderTracker()
        text = "Llámame al +52 55 1234 5678"
        result = regex_anonymize(text, tracker)
        assert "+52 55 1234 5678" not in result
        assert "[PHONE_1]" in result

    def test_mexican_mobile_bare_10_digits(self):
        tracker = PlaceholderTracker()
        text = "Mi número es 5512345678 para contacto"
        result = regex_anonymize(text, tracker)
        assert "5512345678" not in result
        assert "[PHONE_" in result

    def test_spanish_mobile(self):
        tracker = PlaceholderTracker()
        text = "En España me llaman al +34 612 345 678"
        result = regex_anonymize(text, tracker)
        assert "612 345 678" not in result

    def test_multiple_phones_get_different_numbers(self):
        tracker = PlaceholderTracker()
        text = "Tengo +52 55 1234 5678 y +52 33 8765 4321"
        result = regex_anonymize(text, tracker)
        assert "[PHONE_1]" in result
        assert "[PHONE_2]" in result

    def test_same_phone_gets_same_placeholder(self):
        tracker = PlaceholderTracker()
        text = "Mi tel es +52 55 1234 5678. Repito: +52 55 1234 5678"
        result = regex_anonymize(text, tracker)
        assert result.count("[PHONE_1]") == 2
        assert "[PHONE_2]" not in result


# ---------------------------------------------------------------------------
# Emails
# ---------------------------------------------------------------------------


class TestEmailAnonymization:
    def test_standard_email(self):
        tracker = PlaceholderTracker()
        text = "Escríbeme a maria.garcia@gmail.com"
        result = regex_anonymize(text, tracker)
        assert "maria.garcia@gmail.com" not in result
        assert "[EMAIL_1]" in result

    def test_email_with_subdomain(self):
        tracker = PlaceholderTracker()
        text = "Correo: usuario@empresa.com.mx"
        result = regex_anonymize(text, tracker)
        assert "usuario@empresa.com.mx" not in result

    def test_email_with_plus(self):
        tracker = PlaceholderTracker()
        text = "Usa test+tag@domain.org"
        result = regex_anonymize(text, tracker)
        assert "test+tag@domain.org" not in result


# ---------------------------------------------------------------------------
# Order IDs
# ---------------------------------------------------------------------------


class TestOrderIDAnonymization:
    def test_orden_keyword(self):
        tracker = PlaceholderTracker()
        text = "Mi orden es ORD-2024-78543"
        result = regex_anonymize(text, tracker)
        assert "ORD-2024-78543" not in result
        assert "[ORDER_ID_1]" in result

    def test_pedido_keyword(self):
        tracker = PlaceholderTracker()
        text = "El pedido #MX-99001 no llegó"
        result = regex_anonymize(text, tracker)
        assert "MX-99001" not in result

    def test_folio_keyword(self):
        tracker = PlaceholderTracker()
        text = "Mi folio TKT-2024-001 está pendiente"
        result = regex_anonymize(text, tracker)
        assert "TKT-2024-001" not in result

    def test_caso_keyword(self):
        tracker = PlaceholderTracker()
        text = "Referente al caso#ABC12345"
        result = regex_anonymize(text, tracker)
        assert "ABC12345" not in result


# ---------------------------------------------------------------------------
# Account numbers
# ---------------------------------------------------------------------------


class TestAccountNumberAnonymization:
    def test_cuenta_keyword(self):
        tracker = PlaceholderTracker()
        text = "Mi cuenta 452188349912"
        result = regex_anonymize(text, tracker)
        assert "452188349912" not in result
        assert "[ACCOUNT_NUMBER_1]" in result

    def test_imei(self):
        tracker = PlaceholderTracker()
        text = "El IMEI es 356938035643809"
        result = regex_anonymize(text, tracker)
        assert "356938035643809" not in result

    def test_clabe(self):
        tracker = PlaceholderTracker()
        text = "CLABE 012345678901234567"
        result = regex_anonymize(text, tracker)
        assert "012345678901234567" not in result

    def test_standalone_long_number(self):
        tracker = PlaceholderTracker()
        text = "Número: 123456789012345"
        result = regex_anonymize(text, tracker)
        assert "123456789012345" not in result


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------


class TestAddressAnonymization:
    def test_calle_address(self):
        tracker = PlaceholderTracker()
        text = "Vivo en Calle Reforma 234, Colonia Centro"
        result = regex_anonymize(text, tracker)
        assert "Calle Reforma 234" not in result
        assert "[ADDRESS_1]" in result

    def test_avenida_address(self):
        tracker = PlaceholderTracker()
        text = "Está en Av. Insurgentes Sur 1234, Col. Del Valle"
        result = regex_anonymize(text, tracker)
        assert "Insurgentes Sur 1234" not in result

    def test_codigo_postal(self):
        tracker = PlaceholderTracker()
        text = "El C.P. 03100, Ciudad de México"
        result = regex_anonymize(text, tracker)
        assert "C.P. 03100" not in result

    @pytest.mark.parametrize(
        "text",
        [
            "Codigo postal; 94340",           # unaccented + semicolon
            "Código Postal: 93400",           # accented + colon
            "Codigo postal: 28019",           # line-final, nothing after
            "Codigo Postal 82139",            # no separator at all
            "codigo postal 94330, colonia: fraccionamiento las haciendas",
            "El C.P. 03100, Ciudad de México",
            "CP 06000 Centro",
        ],
    )
    def test_postal_codes_never_survive(self, text):
        """Regression: real postal codes leaked through the ADDRESS pattern.

        Two gaps combined. The keyword alternation required the accented
        "código", and the separator after it allowed only "." or whitespace —
        so ":" and ";" (the format the deployment's own address template emits)
        failed to match. 248 of 631 address-bearing messages in the production
        corpus still carried a bare 4-5 digit number as a result.
        """
        result = regex_anonymize(text, PlaceholderTracker())
        assert not re.search(r"\d{4,5}", result), f"postal code leaked: {result!r}"
        assert "[ADDRESS_" in result

    @pytest.mark.parametrize("sep", ["\n", "\r", "\r\n", "\v", "\f"])
    def test_address_does_not_cross_any_line_terminator(self, sep):
        """CR, VT and FF are line terminators too, not horizontal whitespace.

        Word/RTF exports use \\v as a soft break and old Mac exports use \\r;
        if either sits in the address character class, a line-final address
        swallows every following turn.
        """
        text = (
            f"Cliente: Vivo en Av. Insurgentes Sur 1234.{sep}"
            f"Agente: Gracias.{sep}"
            "Cliente: ok"
        )
        result = regex_anonymize(text, PlaceholderTracker())
        assert result.count("Agente:") == text.count("Agente:")
        assert result.count("Cliente:") == text.count("Cliente:")

    def test_address_survives_unicode_spaces(self):
        """NBSP/narrow-NBSP inside an address must not truncate the match."""
        text = "Av. Insurgentes Sur 1234 Ciudad de Mexico"
        result = regex_anonymize(text, PlaceholderTracker())
        assert "Ciudad de Mexico" not in result

    def test_address_does_not_cross_newline(self):
        """An address ending a line must not swallow the next turn's label.

        Regression: the ADDRESS character class used \\s, which matches newlines,
        so a line-final address consumed the following "Agente:" label and
        destroyed the conversation structure the downstream scorer relies on.
        """
        tracker = PlaceholderTracker()
        text = (
            "Cliente: Vivo en Av. Insurgentes Sur 1234, Ciudad de Mexico.\n"
            "Agente: Perfecto, gracias.\n"
            "Cliente: Otra cosa."
        )
        result = regex_anonymize(text, tracker)
        assert "Insurgentes Sur 1234" not in result
        assert result.count("Agente:") == text.count("Agente:")
        assert result.count("Cliente:") == text.count("Cliente:")
        assert result.count("\n") == text.count("\n")


# ---------------------------------------------------------------------------
# CURP and RFC
# ---------------------------------------------------------------------------


class TestMexicanIDAnonymization:
    def test_curp(self):
        tracker = PlaceholderTracker()
        text = "Mi CURP es GALO850315HDFRRL09"
        result = regex_anonymize(text, tracker)
        assert "GALO850315HDFRRL09" not in result
        assert "[CURP_1]" in result

    def test_rfc(self):
        tracker = PlaceholderTracker()
        text = "RFC: GALO850315AB1"
        result = regex_anonymize(text, tracker)
        assert "GALO850315AB1" not in result
        assert "[RFC_1]" in result


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------


class TestURLAnonymization:
    def test_url_with_user_path(self):
        tracker = PlaceholderTracker()
        text = "Mira https://support.tech_repair.com/mx/ticket/USR-78543-maria"
        result = regex_anonymize(text, tracker)
        assert "USR-78543-maria" not in result
        assert "[URL_1]" in result


# ---------------------------------------------------------------------------
# No false positives on non-PII
# ---------------------------------------------------------------------------


class TestNoFalsePositives:
    def test_short_numbers_not_caught(self):
        tracker = PlaceholderTracker()
        text = "Son 12 meses de garantía y cuesta $4999"
        result = regex_anonymize(text, tracker)
        assert result == text

    def test_conversational_text_preserved(self):
        tracker = PlaceholderTracker()
        text = "¡Hola! ¿En qué te puedo ayudar hoy? Tengo una pregunta sobre mi garantía."
        result = regex_anonymize(text, tracker)
        assert result == text

    def test_bare_10_digits_not_caught_after_keyword(self):
        """10-digit number preceded by account keyword should be ACCOUNT_NUMBER, not PHONE."""
        tracker = PlaceholderTracker()
        text = "cuenta 1234567890"
        result = regex_anonymize(text, tracker)
        assert "[ACCOUNT_NUMBER_1]" in result
