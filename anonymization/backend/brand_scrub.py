import re

from config import BRAND_CATEGORY_MAP, PlaceholderTracker, load_brand_terms

_PLACEHOLDER_RE = re.compile(r"\[.+?\]")

# Cache loaded brand terms
_brand_terms: dict[str, list[str]] | None = None


def _get_brand_terms() -> dict[str, list[str]]:
    global _brand_terms
    if _brand_terms is None:
        _brand_terms = load_brand_terms()
    return _brand_terms


def brand_anonymize(
    text: str,
    tracker: PlaceholderTracker,
    brand_terms: dict[str, list[str]] | None = None,
) -> str:
    terms = brand_terms or _get_brand_terms()

    # Collect all (term, category) pairs across all categories, then sort
    # globally by length descending so "Galaxy S24" matches before "Galaxy"
    all_terms: list[tuple[str, str]] = []
    for json_key, placeholder_category in BRAND_CATEGORY_MAP.items():
        for term in terms.get(json_key, []):
            all_terms.append((term, placeholder_category))
    all_terms.sort(key=lambda t: len(t[0]), reverse=True)

    for term, placeholder_category in all_terms:
        pattern = re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE)
        matches = list(pattern.finditer(text))
        for m in reversed(matches):
            # Check if match falls inside an existing placeholder
            preceding = text[: m.start()]
            open_brackets = preceding.count("[") - preceding.count("]")
            if open_brackets > 0:
                continue
            placeholder = tracker.get_placeholder(placeholder_category, m.group())
            text = text[: m.start()] + placeholder + text[m.end() :]

    return text
