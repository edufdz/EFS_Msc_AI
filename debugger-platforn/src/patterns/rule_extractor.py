"""
Guardrail / Policy Rule Extraction (Sprint 6).

Extracts explicit rules from system prompts and policy documents so each
rule becomes a testable assertion in Phase B.  Supports English and Spanish.

Pattern-based extraction runs offline (no LLM).  AI-enhanced extraction is
handled by ``src/ai_analyzer/analyzer.py:analyze_guardrails()``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class PolicyRule:
    rule_id: str                          # "R001", "R002", …
    text: str                             # original rule text
    category: str                         # constraint | requirement | prohibition | fallback | escalation
    complexity: int                       # 1–5
    scope: str                            # always | conditional | tool_specific
    target_tools: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    source_prompt: str = ""
    source_location: dict = field(default_factory=dict)
    language: str = "English"


@dataclass
class PolicyGraph:
    rules: list[PolicyRule] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    total_complexity: int = 0


# ---------------------------------------------------------------------------
# Category keywords (English + Spanish)
# ---------------------------------------------------------------------------

_PROHIBITION_KW = [
    "never", "do not", "don't", "must not", "mustn't", "forbidden",
    "prohibited", "shall not", "cannot", "may not", "under no circumstances",
    # Spanish
    "nunca", "no debes", "no debe", "prohibido", "jamás", "no se permite",
    "está prohibido", "no puedes", "no puede",
]

_REQUIREMENT_KW = [
    "must", "always", "required", "shall", "you are required",
    "is mandatory", "it is essential",
    # Spanish
    "debes", "debe", "siempre", "es obligatorio", "es necesario",
    "se requiere", "tienes que", "tiene que",
]

_CONSTRAINT_KW = [
    "only", "limited to", "maximum", "no more than", "at most",
    "restricted to", "exclusively", "up to",
    # Spanish
    "solo", "solamente", "limitado a", "máximo", "no más de",
    "restringido a", "exclusivamente", "hasta",
]

_ESCALATION_KW = [
    "escalate", "transfer", "human agent", "supervisor",
    "hand off", "handoff", "refer to",
    # Spanish
    "escalar", "transferir", "agente humano", "supervisor",
    "derivar", "pasar a un agente",
]

_FALLBACK_KW = [
    "if unsure", "when in doubt", "default to", "otherwise",
    "if you cannot", "if unable", "as a last resort",
    # Spanish
    "si no estás seguro", "si no está seguro", "en caso de duda",
    "por defecto", "de lo contrario", "si no puedes", "si no puede",
]


def _classify_category(text_lower: str) -> str:
    """Return the most specific category for a rule sentence."""
    for kw in _PROHIBITION_KW:
        if kw in text_lower:
            return "prohibition"
    for kw in _ESCALATION_KW:
        if kw in text_lower:
            return "escalation"
    for kw in _FALLBACK_KW:
        if kw in text_lower:
            return "fallback"
    for kw in _CONSTRAINT_KW:
        if kw in text_lower:
            return "constraint"
    for kw in _REQUIREMENT_KW:
        if kw in text_lower:
            return "requirement"
    return "requirement"  # default


# ---------------------------------------------------------------------------
# Complexity scoring
# ---------------------------------------------------------------------------

_CONDITION_MARKERS = [
    "if ", "when ", "unless ", "except ", "provided that", "as long as",
    "in case", "only if", "only when",
    # Spanish
    "si ", "cuando ", "a menos que", "excepto ", "siempre que",
    "en caso de", "solo si", "solo cuando",
]

_CONJUNCTION_MARKERS = [" and ", " or ", " but ", " y ", " o ", " pero "]
_EXCEPTION_MARKERS = [
    "except", "unless", "however", "but not",
    "excepto", "a menos que", "sin embargo", "pero no",
]
_SEQUENTIAL_MARKERS = [
    "first", "then", "after", "before", "next", "finally",
    "primero", "luego", "después", "antes", "finalmente",
]


def _score_complexity(text: str) -> int:
    """Rate rule complexity from 1 (simple boolean) to 5 (multi-step + state)."""
    lower = text.lower()
    score = 1

    # Conditions bump to at least 2
    n_conditions = sum(1 for m in _CONDITION_MARKERS if m in lower)
    if n_conditions >= 1:
        score = max(score, 2)

    # Multiple conditions / conjunctions → 3
    n_conj = sum(1 for m in _CONJUNCTION_MARKERS if m in lower)
    if n_conditions >= 2 or (n_conditions >= 1 and n_conj >= 1):
        score = max(score, 3)

    # Exceptions → 4
    if any(m in lower for m in _EXCEPTION_MARKERS):
        score = max(score, 4)

    # Sequential / stateful → 5
    n_seq = sum(1 for m in _SEQUENTIAL_MARKERS if m in lower)
    if n_seq >= 2:
        score = max(score, 5)

    return min(score, 5)


# ---------------------------------------------------------------------------
# Scope & tool detection
# ---------------------------------------------------------------------------

def _detect_scope(text_lower: str, tool_names: list[str]) -> tuple[str, list[str]]:
    """Return (scope, target_tools)."""
    matched_tools = [t for t in tool_names if t.lower() in text_lower]
    if matched_tools:
        return "tool_specific", matched_tools
    if any(m in text_lower for m in _CONDITION_MARKERS):
        return "conditional", []
    return "always", []


# ---------------------------------------------------------------------------
# Condition extraction
# ---------------------------------------------------------------------------

_CONDITION_PATTERNS = [
    re.compile(r"(?:if|when|si|cuando)\s+(.+?)(?:,|\bthen\b|\bentonces\b)", re.IGNORECASE),
    re.compile(r"(?:unless|a menos que|except when|excepto cuando)\s+(.+?)(?:\.|,|$)", re.IGNORECASE),
]


def _extract_conditions(text: str) -> list[str]:
    conditions = []
    for pat in _CONDITION_PATTERNS:
        for m in pat.finditer(text):
            cond = m.group(1).strip().rstrip(".,;")
            if len(cond) > 5:
                conditions.append(cond)
    return conditions


# ---------------------------------------------------------------------------
# Language detection (lightweight)
# ---------------------------------------------------------------------------

_SPANISH_INDICATORS = [
    "debes", "debe", "nunca", "siempre", "prohibido", "obligatorio",
    "usuario", "cliente", "agente", "si no", "cuando",
]


def _detect_rule_language(text: str) -> str:
    lower = text.lower()
    spanish_hits = sum(1 for kw in _SPANISH_INDICATORS if kw in lower)
    return "Spanish" if spanish_hits >= 2 else "English"


# ---------------------------------------------------------------------------
# Text → sentence splitting
# ---------------------------------------------------------------------------

# Patterns that start a rule line
_RULE_LINE_RE = re.compile(
    r"(?:^|\n)\s*"
    r"(?:"
    r"\d+[\.\)]\s*"                     # 1. or 1)
    r"|[-•*]\s*"                         # - or • or *
    r"|(?:Rule|Regla)\s*#?\d+[:\.]?\s*"  # Rule #1: or Regla 1.
    r")"
    r"(.+)",
    re.IGNORECASE,
)

_IMPERATIVE_START_RE = re.compile(
    r"(?:^|\n)\s*[-•*]\s*"
    r"((?:Never|Always|Do not|Don't|Must|Should|You must|You should"
    r"|Nunca|Siempre|No debes|No debe|Debes|Debe|Es obligatorio"
    r"|If |When |Si |Cuando )"
    r".+)",
    re.IGNORECASE,
)


def _split_rules(text: str) -> list[str]:
    """Extract individual rule sentences from prompt text."""
    rules: list[str] = []
    seen: set[str] = set()

    def _add(sentence: str):
        s = sentence.strip().rstrip(".")
        if len(s) < 10 or s in seen:
            return
        seen.add(s)
        rules.append(s)

    # Pass 1: numbered / bulleted lines
    for m in _RULE_LINE_RE.finditer(text):
        _add(m.group(1))

    # Pass 2: imperative-start lines (- Never …, - Always …)
    for m in _IMPERATIVE_START_RE.finditer(text):
        _add(m.group(1))

    # Pass 3: sentence-level scan for rule keywords in remaining text
    # Split by sentence-ending punctuation
    for sentence in re.split(r'(?<=[.!?])\s+', text):
        sentence = sentence.strip()
        if len(sentence) < 10:
            continue
        lower = sentence.lower()
        is_rule = any(kw in lower for kw in (
            _PROHIBITION_KW[:6] + _REQUIREMENT_KW[:4]
            + _ESCALATION_KW[:4] + _FALLBACK_KW[:3]
        ))
        if is_rule:
            _add(sentence)

    return rules


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_rules_from_text(
    text: str,
    source_prompt: str = "",
    source_location: dict | None = None,
    tool_names: list[str] | None = None,
    start_id: int = 1,
) -> list[PolicyRule]:
    """Extract policy rules from a single prompt/document text.

    Returns a list of ``PolicyRule`` objects numbered from *start_id*.
    """
    if not text or len(text.strip()) < 15:
        return []

    tool_names = tool_names or []
    raw_rules = _split_rules(text)
    result: list[PolicyRule] = []

    for i, rule_text in enumerate(raw_rules):
        lower = rule_text.lower()
        category = _classify_category(lower)
        complexity = _score_complexity(rule_text)
        scope, target_tools = _detect_scope(lower, tool_names)
        conditions = _extract_conditions(rule_text)
        language = _detect_rule_language(rule_text)

        result.append(PolicyRule(
            rule_id=f"R{start_id + i:03d}",
            text=rule_text,
            category=category,
            complexity=complexity,
            scope=scope,
            target_tools=target_tools,
            conditions=conditions,
            source_prompt=source_prompt,
            source_location=source_location or {},
            language=language,
        ))

    return result


def extract_rules_from_prompts(
    prompts: list,
    tool_names: list[str] | None = None,
) -> PolicyGraph:
    """Extract rules from all prompt definitions.

    *prompts* is a list of ``PromptDefinition`` objects (from detector.py).
    Returns a ``PolicyGraph`` with sequentially numbered rules.
    """
    all_rules: list[PolicyRule] = []
    next_id = 1

    for prompt in prompts:
        content = getattr(prompt, "content", "") or ""
        name = getattr(prompt, "name", "")
        location = getattr(prompt, "location", {})

        rules = extract_rules_from_text(
            text=content,
            source_prompt=name,
            source_location=location,
            tool_names=tool_names,
            start_id=next_id,
        )
        all_rules.extend(rules)
        next_id += len(rules)

    total_complexity = sum(r.complexity for r in all_rules)

    return PolicyGraph(
        rules=all_rules,
        edges=[],
        total_complexity=total_complexity,
    )
