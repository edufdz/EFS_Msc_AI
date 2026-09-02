import json
import os
import re
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

SPACY_MODEL = os.getenv("SPACY_MODEL", "es_core_news_lg")
BRAND_CONFIG_PATH = os.getenv("BRAND_CONFIG_PATH", "brand_terms.json")

# Horizontal whitespace, for use *inside* character classes (where `[^\S\n]`
# cannot be nested). Plain " \t" is not enough: WhatsApp and iOS exports carry
# NBSP and narrow-NBSP inside addresses, and omitting them truncates the match
# and leaves the rest of the address in cleartext.
#
# Strictly horizontal: \r, \v and \f are line terminators and must stay out,
# or a line-final address swallows the following turn label -- the exact bug
# this pattern is shaped to avoid.
_H_SPACE = " \t\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f\u3000"

# ---------------------------------------------------------------------------
# Regex patterns — keyed by PII category, ordered by specificity
# ---------------------------------------------------------------------------

PII_PATTERNS: dict[str, list[re.Pattern]] = {
    "PHONE": [
        # Mexican mobile/landline with +52 prefix
        re.compile(r"\+?52[-\s]?1?[-\s]?\d{2,3}[-\s]?\d{3,4}[-\s]?\d{4}"),
        # Spanish mobile (+34)
        re.compile(r"(?:\+?34[-\s]?)?[6-9]\d{2}[-\s]?\d{3}[-\s]?\d{3}"),
        # Generic international with +
        re.compile(r"\+\d{1,3}[-\s]?\(?\d{1,4}\)?[-\s]?\d{2,4}[-\s]?\d{2,4}[-\s]?\d{0,4}"),
        # Bare 10-digit (Mexican standard)
        re.compile(r"\b\d{10}\b"),
    ],
    "EMAIL": [
        re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"),
    ],
    "CURP": [
        re.compile(r"\b[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d\b"),
    ],
    "RFC": [
        re.compile(r"\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}\b"),
    ],
    "ORDER_ID": [
        re.compile(
            r"(?i)(?:orden|pedido|ticket|folio|caso|número de orden|no\.\s*de pedido)"
            r"(?:\s+(?:es|fue|será|número))?"
            r"[\s#:\-]*([A-Z0-9\-]{5,20})",
        ),
    ],
    "ACCOUNT_NUMBER": [
        # Keyword-prefixed account numbers
        re.compile(
            r"(?i)(?:cuenta|número de cuenta|no\.\s*de cuenta|IMEI|CLABE)"
            r"[\s#:\-]*(\d{6,20})",
        ),
        # Standalone long digit sequences (likely IDs)
        re.compile(r"\b\d{12,20}\b"),
        # Dash-separated digit groups (card numbers, account numbers like 4521-8834-9912-0045)
        re.compile(r"\b\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}\b"),
    ],
    "ADDRESS": [
        # Horizontal whitespace only ([^\S\n]): an address must never run past the
        # end of its line, or it swallows the next turn's "Cliente:"/"Agente:" label
        # and destroys the conversation structure the scorer depends on.
        #
        # Two things this pattern must tolerate, because production WhatsApp text
        # does both constantly and missing either leaks a real address:
        #   * dropped accents — "codigo postal" is as common as "código postal";
        #   * ":" / ";" separators — "Código Postal: 93400" is the format the
        #     deployment's own address-collection template emits.
        re.compile(
            r"(?i)(?:calle|av(?:enida)?|blvd|boulevard|col(?:onia)?|c\.?[^\S\n]?p\.?|"
            r"c[oó]digo[^\S\n]*postal|paseo|camino|cerrada|privada|circuito)"
            r"[\.:;]?[^\S\n]+[A-ZÁÉÍÓÚÜÑa-záéíóúüñ0-9" + _H_SPACE + r",#\.:;°\-]{5,80}",
        ),
        # Bare Mexican postal code introduced by a keyword. The general pattern
        # above needs 5+ trailing characters, so a line ending "C.P. 03100" or
        # "Codigo postal: 28019" falls through it entirely.
        re.compile(
            r"(?i)(?:c\.?[^\S\n]?p\.?|c[oó]digo[^\S\n]*postal)"
            r"[\.:;]?[^\S\n]*\d{5}\b",
        ),
    ],
    "URL": [
        re.compile(r"https?://[^\s<>\"']{10,}"),
    ],
}

# The order in which categories are processed (specific → broad)
PII_CATEGORY_ORDER = [
    "CURP",
    "RFC",
    "ORDER_ID",
    "ACCOUNT_NUMBER",
    "EMAIL",
    "ADDRESS",
    "URL",
    "PHONE",  # Last: broad 10-digit pattern should not steal from specific categories
]

# ---------------------------------------------------------------------------
# Brand category → placeholder type mapping
# ---------------------------------------------------------------------------

BRAND_CATEGORY_MAP = {
    "brands": "BRAND",
    "devices": "DEVICE",
    "products": "PRODUCT",
    "services": "SERVICE",
}


# ---------------------------------------------------------------------------
# PlaceholderTracker — shared across all passes for consistent numbering
# ---------------------------------------------------------------------------


@dataclass
class PlaceholderTracker:
    _counters: dict[str, int] = field(default_factory=dict)
    _seen: dict[str, str] = field(default_factory=dict)

    def get_placeholder(self, category: str, raw_value: str) -> str:
        normalized = raw_value.strip().lower()
        key = f"{category}:{normalized}"
        if key in self._seen:
            return self._seen[key]
        count = self._counters.get(category, 0) + 1
        self._counters[category] = count
        placeholder = f"[{category}_{count}]"
        self._seen[key] = placeholder
        return placeholder

    def get_summary(self) -> dict[str, int]:
        return dict(self._counters)


# ---------------------------------------------------------------------------
# Brand terms loader
# ---------------------------------------------------------------------------


def load_brand_terms(path: str | None = None) -> dict[str, list[str]]:
    path = path or BRAND_CONFIG_PATH
    # Resolve relative to this file's directory
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(__file__), path)
    with open(path, encoding="utf-8") as f:
        return json.load(f)
