import re
from typing import Optional

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import SpacyNlpEngine

from config import SPACY_MODEL, PlaceholderTracker

# Lazy singleton
_analyzer: Optional[AnalyzerEngine] = None

# Map Presidio entity types to our placeholder categories
_ENTITY_MAP = {
    "PERSON": "PERSON",
    "LOCATION": "LOCATION",
    "PHONE_NUMBER": "PHONE",
    "EMAIL_ADDRESS": "EMAIL",
    "NRP": "PERSON",  # nationality / religious / political group
}

_PLACEHOLDER_RE = re.compile(r"\[.+?\]")

NER_SCORE_THRESHOLD = 0.4


def get_analyzer() -> AnalyzerEngine:
    global _analyzer
    if _analyzer is None:
        spacy_engine = SpacyNlpEngine(
            models=[{"lang_code": "es", "model_name": SPACY_MODEL}]
        )
        _analyzer = AnalyzerEngine(
            nlp_engine=spacy_engine, supported_languages=["es"]
        )
    return _analyzer


MAX_CHUNK_SIZE = 500_000  # chars per chunk for spaCy (well under 1M limit)


def _split_into_chunks(text: str) -> list[tuple[int, str]]:
    """Split text into chunks at newline boundaries. Returns (offset, chunk) pairs."""
    if len(text) <= MAX_CHUNK_SIZE:
        return [(0, text)]

    chunks = []
    start = 0
    while start < len(text):
        end = start + MAX_CHUNK_SIZE
        if end >= len(text):
            chunks.append((start, text[start:]))
            break
        # Find the last newline before the limit
        newline_pos = text.rfind("\n", start, end)
        if newline_pos == -1 or newline_pos == start:
            newline_pos = end  # no newline found, hard cut
        else:
            newline_pos += 1  # include the newline in this chunk
        chunks.append((start, text[start:newline_pos]))
        start = newline_pos
    return chunks


def _analyze_chunk(
    chunk: str,
    offset: int,
    analyzer: AnalyzerEngine,
    placeholder_positions: set[int],
) -> list[tuple[int, int, str, str]]:
    """Analyze a single chunk and return (start, end, category, raw_value) in original text coords."""
    results = analyzer.analyze(
        text=chunk,
        language="es",
        entities=list(_ENTITY_MAP.keys()),
        score_threshold=NER_SCORE_THRESHOLD,
    )

    hits = []
    for r in results:
        abs_start = r.start + offset
        abs_end = r.end + offset
        # Skip if overlaps with existing placeholders
        if set(range(abs_start, abs_end)) & placeholder_positions:
            continue
        if r.entity_type not in _ENTITY_MAP:
            continue
        category = _ENTITY_MAP[r.entity_type]
        raw_value = chunk[r.start:r.end]
        hits.append((abs_start, abs_end, category, raw_value))
    return hits


def ner_anonymize(
    text: str,
    tracker: PlaceholderTracker,
    analyzer: Optional[AnalyzerEngine] = None,
) -> str:
    analyzer = analyzer or get_analyzer()

    # Build a set of character positions that are inside existing placeholders
    placeholder_positions: set[int] = set()
    for m in _PLACEHOLDER_RE.finditer(text):
        for i in range(m.start(), m.end()):
            placeholder_positions.add(i)

    # Process in chunks to avoid spaCy max_length error
    chunks = _split_into_chunks(text)
    all_hits = []
    for offset, chunk in chunks:
        hits = _analyze_chunk(chunk, offset, analyzer, placeholder_positions)
        all_hits.extend(hits)

    # Sort by start position descending for right-to-left replacement
    all_hits.sort(key=lambda h: h[0], reverse=True)

    for start, end, category, raw_value in all_hits:
        placeholder = tracker.get_placeholder(category, raw_value)
        text = text[:start] + placeholder + text[end:]

    return text
