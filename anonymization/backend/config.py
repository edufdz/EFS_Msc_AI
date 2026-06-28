import json
import os
import re
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

SPACY_MODEL = os.getenv("SPACY_MODEL", "es_core_news_lg")
BRAND_CONFIG_PATH = os.getenv("BRAND_CONFIG_PATH", "brand_terms.json")

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
        re.compile(
            r"(?i)(?:calle|av(?:enida)?|blvd|boulevard|col(?:onia)?|c\.?\s?p\.?|"
            r"código\s*postal|paseo|camino|cerrada|privada|circuito)"
            r"\.?\s+[A-ZÁÉÍÓÚÜÑa-záéíóúüñ0-9\s,#\.°\-]{5,80}",
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
