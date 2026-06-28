import re

from config import PII_CATEGORY_ORDER, PII_PATTERNS, PlaceholderTracker


def _collect_matches(text: str) -> list[tuple[int, int, str, str]]:
    """Return (start, end, category, matched_text) for every PII hit."""
    matches: list[tuple[int, int, str, str]] = []
    for category in PII_CATEGORY_ORDER:
        for pattern in PII_PATTERNS[category]:
            for m in pattern.finditer(text):
                # Some patterns use a capture group for the actual ID
                if m.lastindex and category in ("ORDER_ID", "ACCOUNT_NUMBER"):
                    matches.append((m.start(1), m.end(1), category, m.group(1)))
                else:
                    matches.append((m.start(), m.end(), category, m.group()))
    return matches


def _resolve_overlaps(
    matches: list[tuple[int, int, str, str]],
) -> list[tuple[int, int, str, str]]:
    """Keep the longest match when spans overlap."""
    # Sort by start position, then by length descending
    matches.sort(key=lambda m: (m[0], -(m[1] - m[0])))
    resolved: list[tuple[int, int, str, str]] = []
    last_end = -1
    for start, end, category, text in matches:
        if start >= last_end:
            resolved.append((start, end, category, text))
            last_end = end
    return resolved


def regex_anonymize(text: str, tracker: PlaceholderTracker) -> str:
    matches = _collect_matches(text)
    matches = _resolve_overlaps(matches)
    # Replace right-to-left to preserve character positions
    for start, end, category, matched_text in reversed(matches):
        placeholder = tracker.get_placeholder(category, matched_text)
        text = text[:start] + placeholder + text[end:]
    return text
