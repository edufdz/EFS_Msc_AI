from dataclasses import dataclass

from brand_scrub import brand_anonymize
from config import PlaceholderTracker, load_brand_terms
from ner_pass import get_analyzer, ner_anonymize
from regex_pass import regex_anonymize

# Cache brand terms after first load
_brand_terms: dict | None = None


def _get_brand_terms() -> dict:
    global _brand_terms
    if _brand_terms is None:
        _brand_terms = load_brand_terms()
    return _brand_terms


@dataclass
class AnonymizationResult:
    original_text: str
    anonymized_text: str
    replacement_counts: dict[str, int]


def anonymize(text: str) -> AnonymizationResult:
    tracker = PlaceholderTracker()

    # Pass 1: Regex-based PII detection
    result = regex_anonymize(text, tracker)

    # Pass 2: NER-based PII detection (catches names/locations regex missed)
    result = ner_anonymize(result, tracker, get_analyzer())

    # Pass 3: Brand term replacement
    result = brand_anonymize(result, tracker, _get_brand_terms())

    return AnonymizationResult(
        original_text=text,
        anonymized_text=result,
        replacement_counts=tracker.get_summary(),
    )


def anonymize_text(text: str) -> str:
    """Convenience function that returns just the anonymized string."""
    return anonymize(text).anonymized_text
