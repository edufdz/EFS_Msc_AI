"""
Production-Grounded Personas (Sprint E6).

Fits the 10-trait :class:`PersonaTraits` distributions and the
:class:`PersonaStyle` style distributions to *real* production conversations
(formality, typo rate, emoji use, verbosity, code-switching, language
proficiency, patience, emotional volatility, tech-savviness) and samples a new
persona population whose statistics match the observed user population. This
replaces hand-authored trait vectors with empirically grounded distributions
so the persona library reflects who actually talks to the agent.

Simulators overfitted to hand-written rules fail to transfer to real humans
(Gao et al., *Neural Approaches to Conversational AI*); grounding synthetic
users in production behaviour improves directional correlation with observed
human outcomes (SimGym, 2026).

Everything here is offline. Trace data is read from a Phase A
``TraceAnalysisResult``-like object, a ``trace_analysis`` dict embedded in an
agent map, or a JSON traces file on disk — no Langfuse credentials are
required. The per-conversation style extraction reuses
:func:`src.scenarios.seed_corpus.extract_persona_from_trace` (Sprint E1) so
E1 and E6 agree on how a conversation is read; loading reuses
:func:`src.scenarios.seed_corpus.load_trace_result`.
"""

from __future__ import annotations

import re
import statistics
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.personas.models import (
    Persona,
    PersonaEdgeBehaviors,
    PersonaStyle,
    PersonaTraits,
)

# Reuse the Sprint E1 trace-reading primitives so both sprints agree on how a
# conversation record is parsed (duck-typed dict/object access) and on the
# style lexicons.
from src.scenarios.seed_corpus import (  # noqa: F401  (re-exported for callers/tests)
    extract_persona_from_trace,
    load_trace_result,
    _EMOJI_RE,
    _POLITE_MARKERS,
    _RUDE_MARKERS,
    _SPANISH_MARKERS,
    _get,
    _messages,
)

# The 10 numeric PersonaTraits dimensions, in a fixed canonical order.
TRAIT_NAMES: List[str] = [
    "patience", "clarity", "tech_savviness", "politeness", "verbosity",
    "emotional_volatility", "trust_level", "detail_orientation",
    "decision_speed", "language_proficiency",
]

PRODUCTION_SOURCE = "production_grounded"

# ----------------------------------------------------------------------
# Lexicons / patterns for the additional trace signals (E6.1)
# ----------------------------------------------------------------------

# Three or more of the same character in a row → "holaaaa", "siii" (typo/noise)
_REPEAT_RE = re.compile(r"(.)\1\1", re.IGNORECASE)

# Common Spanish words frequently written WITHOUT their accent → typo signal
_MISSING_ACCENT_WORDS = (
    "codigo", "numero", "telefono", "informacion", "podria", "quisiera",
    "aqui", "asi", "esta pedido", "mas ", "tambien", "dias", "articulo",
    "direccion", "aun ", "envio", "peticion", "atencion",
)

# English markers (mirror of _SPANISH_MARKERS) for code-switching detection
_ENGLISH_MARKERS = (
    "the ", "please", "hello", "order", "need", "want", "help", "thanks",
    "where", "when", "what", "how", "my ", "your", "can you", "i have",
)

# Technical vocabulary / formats → tech-savviness signal
_TECH_TERMS = (
    "api", "http", "https", "url", "json", "config", "error 4", "error 5",
    "status code", "endpoint", "webhook", "código", "codigo", "tracking",
    "número de pedido", "numero de pedido", "order number", "sku", "imei",
    "modelo", "firmware", "app version", "screenshot", "captura",
)

# Order/reference-number formats (uppercase alnum tokens) → tech-savviness
_ORDER_RE = re.compile(r"\b(?=[A-Z0-9-]*[A-Z])(?=[A-Z0-9-]*\d)[A-Z0-9-]{6,}\b")

_WORD_RE = re.compile(r"\w+", re.UNICODE)
_UPPER_WORD_RE = re.compile(r"[A-Za-zÁÉÍÓÚÑ]{3,}")


def _clamp(value: float, lo: int = 1, hi: int = 10) -> int:
    return int(max(lo, min(hi, round(value))))


def _user_texts(conversation: Any) -> List[str]:
    """Return the list of user-message strings for a conversation record.

    Accepts the same shapes as Sprint E1: a bare list of ``{role, content}``
    turns, or a dict/object exposing ``messages``/``turns``/``conversation``.
    """
    if isinstance(conversation, list):
        messages = [
            {"role": str(_get(m, "role", "user")), "content": str(_get(m, "content", ""))}
            for m in conversation
        ]
    else:
        messages = _messages(conversation)
    return [m["content"] for m in messages if m.get("role") == "user" and m.get("content")]


# ----------------------------------------------------------------------
# E6.1 — Trace-to-trait analyser
# ----------------------------------------------------------------------


def _analyse_conversation(conversation: Any) -> Optional[Dict[str, Any]]:
    """Compute a per-conversation trait vector (the 10 numeric dimensions) plus
    style features from a single conversation's user messages.

    Returns ``None`` for conversations with no user text (nothing to fit).
    """
    texts = _user_texts(conversation)
    if not texts:
        return None

    # Reuse the Sprint E1 extractor for the shared style signals so the two
    # sprints read a conversation identically.
    base = extract_persona_from_trace(conversation)

    joined = " ".join(texts)
    joined_lower = joined.lower()
    words = _WORD_RE.findall(joined_lower)
    n_words = max(1, len(words))

    # --- Typo rate: repeated characters + missing accents, per word ---------
    repeated_hits = len(_REPEAT_RE.findall(joined_lower))
    missing_accent_hits = sum(joined_lower.count(w) for w in _MISSING_ACCENT_WORDS)
    typo_rate = min(1.0, (repeated_hits + missing_accent_hits) / n_words)

    # --- Code-switching: both Spanish and English markers present -----------
    spanish_hits = sum(joined_lower.count(m) for m in _SPANISH_MARKERS)
    english_hits = sum(joined_lower.count(m) for m in _ENGLISH_MARKERS)
    code_switch = spanish_hits > 0 and english_hits > 0

    # --- Language proficiency: grammar/typo ratio + code-switching ----------
    language_proficiency = _clamp(9 - typo_rate * 7 - (2 if code_switch else 0))

    # --- Tech savviness: technical terms + order-number formats -------------
    tech_hits = sum(joined_lower.count(t) for t in _TECH_TERMS)
    order_hits = len(_ORDER_RE.findall(joined))
    tech_savviness = _clamp(4 + tech_hits + order_hits)

    # --- Emotional volatility: sentiment variance across messages -----------
    sentiments: List[float] = []
    for t in texts:
        tl = t.lower()
        polite = sum(tl.count(m) for m in _POLITE_MARKERS)
        rude = sum(tl.count(m) for m in _RUDE_MARKERS)
        exclaim = tl.count("!")
        shouts = sum(1 for w in _UPPER_WORD_RE.findall(t) if w.isupper())
        sentiments.append(polite - rude - 0.5 * exclaim - 0.5 * shouts)
    if len(sentiments) > 1:
        emotional_volatility = _clamp(1 + statistics.pvariance(sentiments))
    else:
        emotional_volatility = 2

    # --- Patience: turns before escalation / abandonment --------------------
    n_turns = int(base.get("message_count", len(texts)) or len(texts))
    outcome = str(_get(conversation, "outcome", "") or "").lower()
    escalated = ("escalat" in outcome) or bool(_get(conversation, "escalated", False))
    if escalated:
        # Escalating after few turns → impatient; after many → patient
        patience = _clamp(n_turns)
    else:
        patience = _clamp(int(base.get("patience", 5)) + 2)

    verbosity = int(base.get("verbosity", 5))
    politeness = int(base.get("politeness", 5))

    # --- Derived proxies for dimensions with no direct textual signal -------
    # (documented in the module/README: grounded in the measured signals above)
    clarity = _clamp(8 - typo_rate * 6 - (2 if verbosity <= 3 else 0))
    detail_orientation = _clamp(2 + 0.7 * verbosity)
    trust_level = _clamp(2 + 0.6 * politeness)
    decision_speed = _clamp(10 - 0.5 * verbosity)

    return {
        "patience": patience,
        "clarity": clarity,
        "tech_savviness": tech_savviness,
        "politeness": politeness,
        "verbosity": verbosity,
        "emotional_volatility": emotional_volatility,
        "trust_level": trust_level,
        "detail_orientation": detail_orientation,
        "decision_speed": decision_speed,
        "language_proficiency": language_proficiency,
        # Style features (used by fit_trait_distributions)
        "_formality": base.get("formality", "casual"),
        "_typo_rate": round(typo_rate, 3),
        "_emoji_use": base.get("emoji_use", "none"),
        "_language": base.get("language", "English"),
    }


def _summarise(values: List[float]) -> Dict[str, float]:
    """Mean/std/percentiles for a list of numeric values."""
    if not values:
        return {"mean": 5.0, "std": 0.0, "p25": 5.0, "p50": 5.0, "p75": 5.0,
                "min": 5.0, "max": 5.0}
    mean = statistics.fmean(values)
    std = statistics.pstdev(values) if len(values) > 1 else 0.0
    ordered = sorted(values)

    def _pct(p: float) -> float:
        if len(ordered) == 1:
            return ordered[0]
        idx = p * (len(ordered) - 1)
        lo = int(idx)
        frac = idx - lo
        hi = min(lo + 1, len(ordered) - 1)
        return ordered[lo] + frac * (ordered[hi] - ordered[lo])

    return {
        "mean": round(mean, 3),
        "std": round(std, 3),
        "p25": round(_pct(0.25), 3),
        "p50": round(_pct(0.50), 3),
        "p75": round(_pct(0.75), 3),
        "min": float(ordered[0]),
        "max": float(ordered[-1]),
    }


def _pct_distribution(labels: List[str]) -> Dict[str, float]:
    """Turn a list of categorical labels into a {label: fraction} distribution."""
    if not labels:
        return {}
    total = len(labels)
    counts: Dict[str, int] = {}
    for lab in labels:
        counts[lab] = counts.get(lab, 0) + 1
    return {k: round(v / total, 3) for k, v in counts.items()}


def analyse_user_traits(conversations: List[Any]) -> Dict[str, Any]:
    """Analyse the user messages of *conversations* and return distribution
    statistics (mean, std, percentiles) for each of the 10 trait dimensions,
    plus categorical style distributions (formality, emoji use, language) and
    the typo-rate mean.

    Conversations with no user text are skipped. Returns a stable structure
    even for an empty input (``n_conversations == 0``).
    """
    per_conversation: List[Dict[str, Any]] = []
    for conv in conversations or []:
        vec = _analyse_conversation(conv)
        if vec is not None:
            per_conversation.append(vec)

    traits: Dict[str, Dict[str, float]] = {}
    for name in TRAIT_NAMES:
        traits[name] = _summarise([float(v[name]) for v in per_conversation])

    formality_labels = [v["_formality"] for v in per_conversation]
    emoji_labels = [v["_emoji_use"] for v in per_conversation]
    language_labels = [v["_language"] for v in per_conversation]
    typo_values = [float(v["_typo_rate"]) for v in per_conversation]

    style = {
        "formality": _pct_distribution(formality_labels),
        "emoji_use": _pct_distribution(emoji_labels),
        "language": _pct_distribution(language_labels),
        "typo_rate_mean": round(statistics.fmean(typo_values), 3) if typo_values else 0.05,
        "typo_rate_std": round(statistics.pstdev(typo_values), 3) if len(typo_values) > 1 else 0.0,
    }

    return {
        "n_conversations": len(per_conversation),
        "traits": traits,
        "style": style,
        "per_conversation": per_conversation,
    }


def fit_trait_distributions(conversations: List[Any]) -> Dict[str, Any]:
    """Fit (mean, std) for each of the 10 PersonaTraits dimensions plus the
    style distribution from *conversations*.

    Returns a structured dict::

        {
            "traits": {trait_name: (mean, std), ...},   # all 10 dimensions
            "style": {
                "formality": {"formal": 0.6, "casual": 0.4, ...},
                "typo_rate": <mean>,
                "typo_rate_std": <std>,
                "emoji_use": {"none": 0.7, "rare": 0.3, ...},
                "language": {"Spanish": 0.9, "English": 0.1},
            },
            "dominant_language": "Spanish",
            "n_conversations": <N>,
        }

    NOTE (deviation from the spec's ``dict[str, tuple[float, float]]`` hint):
    the return is a structured dict rather than a bare ``trait -> (mean, std)``
    mapping, because the style distribution and conversation count cannot be
    expressed as ``(float, float)`` tuples. The trait means/stds live under the
    ``"traits"`` key as the spec's tuples. :func:`sample_production_personas`
    consumes this structure (and also tolerates the bare mapping).
    """
    analysis = analyse_user_traits(conversations)

    trait_ms: Dict[str, Tuple[float, float]] = {}
    for name in TRAIT_NAMES:
        s = analysis["traits"][name]
        trait_ms[name] = (s["mean"], s["std"])

    style = analysis["style"]
    language_dist = style.get("language", {})
    dominant_language = (
        max(language_dist, key=language_dist.get) if language_dist else "English"
    )

    return {
        "traits": trait_ms,
        "style": {
            "formality": style.get("formality", {}),
            "typo_rate": style.get("typo_rate_mean", 0.05),
            "typo_rate_std": style.get("typo_rate_std", 0.0),
            "emoji_use": style.get("emoji_use", {}),
            "language": language_dist,
        },
        "dominant_language": dominant_language,
        "n_conversations": analysis["n_conversations"],
    }


# ----------------------------------------------------------------------
# E6.2 — Production-distribution persona generator
# ----------------------------------------------------------------------

# Culturally-appropriate names by dominant language. TechRepair's WhatsApp
# support runs in Mexican Spanish, so Spanish traces get Mexican-Spanish names.
_MX_SPANISH_NAMES = [
    "María González", "José Hernández", "Guadalupe Martínez", "Juan Pérez",
    "Alejandra Ramírez", "Luis García", "Fernanda López", "Miguel Ángel Torres",
    "Ximena Flores", "Carlos Sánchez", "Regina Cruz", "Diego Morales",
    "Valentina Reyes", "Ricardo Jiménez", "Daniela Ortega", "Emiliano Vázquez",
    "Sofía Mendoza", "Ángel Domínguez", "Renata Castillo", "Santiago Rueda",
    "Mariana Aguilar", "Fernando Guerrero", "Paola Núñez", "Andrés Rojas",
]

_GENERIC_NAMES = [
    "Alex Morgan", "Jordan Lee", "Taylor Brooks", "Sam Rivera", "Casey Nguyen",
    "Jamie Fisher", "Morgan Reyes", "Riley Cooper", "Avery Mitchell",
    "Quinn Sullivan", "Dakota Price", "Harper Wells", "Rowan Clarke",
    "Sydney Barnes", "Emerson Hale", "Peyton Cole", "Skyler Dawson",
]


def _mean_std(entry: Any) -> Tuple[float, float]:
    """Normalise a trait distribution entry to ``(mean, std)``.

    Accepts the fit-output tuple ``(mean, std)`` or the analyse-output dict
    ``{"mean": .., "std": ..}``.
    """
    if isinstance(entry, dict):
        return float(entry.get("mean", 5.0)), float(entry.get("std", 0.0))
    if isinstance(entry, (tuple, list)) and len(entry) >= 2:
        return float(entry[0]), float(entry[1])
    return 5.0, 0.0


def _sample_categorical(rng, distribution: Dict[str, float], default: str) -> str:
    """Sample a label from a {label: probability} distribution."""
    if not distribution:
        return default
    labels = list(distribution.keys())
    weights = [max(0.0, float(distribution[k])) for k in labels]
    total = sum(weights)
    if total <= 0:
        return default
    probs = [w / total for w in weights]
    return str(rng.choice(labels, p=probs))


def sample_production_personas(
    distributions: Dict[str, Any],
    count: int,
    seed: int = 42,
    agent_type: str = "custom",
) -> List[Persona]:
    """Sample *count* personas whose trait/style statistics match the fitted
    production ``distributions`` (from :func:`fit_trait_distributions`).

    Each trait is drawn from a truncated normal (the fitted mean/std, clipped
    to 1–10 and rounded). Style is sampled from the fitted categorical
    distributions. ``source`` is set to ``"production_grounded"`` and names are
    drawn from the cultural distribution implied by the dominant language.
    Deterministic given *seed*.
    """
    import numpy as np  # local import: keeps module import cheap/safe

    if count <= 0:
        return []

    rng = np.random.default_rng(seed)

    trait_dist = distributions.get("traits", distributions) or {}
    style_dist = distributions.get("style", {}) or {}
    dominant_language = distributions.get("dominant_language", "English")

    names = _MX_SPANISH_NAMES if dominant_language == "Spanish" else _GENERIC_NAMES
    name_pool = list(names)
    rng.shuffle(name_pool)

    now = datetime.now(timezone.utc)
    personas: List[Persona] = []

    for i in range(count):
        trait_values: Dict[str, int] = {}
        for name in TRAIT_NAMES:
            mean, std = _mean_std(trait_dist.get(name, (5.0, 0.0)))
            if std <= 0:
                sampled = mean
            else:
                sampled = rng.normal(mean, std)
            trait_values[name] = _clamp(sampled)

        traits = PersonaTraits(**trait_values)

        # Style: sampled from the fitted categorical distributions
        formality = _sample_categorical(rng, style_dist.get("formality", {}), "casual")
        emoji_use = _sample_categorical(rng, style_dist.get("emoji_use", {}), "none")

        typo_mean = float(style_dist.get("typo_rate", 0.05))
        typo_std = float(style_dist.get("typo_rate_std", 0.0))
        typo_rate = typo_mean if typo_std <= 0 else float(rng.normal(typo_mean, typo_std))
        typo_rate = round(max(0.0, min(1.0, typo_rate)), 3)

        # Tone derived from sampled politeness + volatility (keeps style
        # internally consistent with the sampled traits).
        if trait_values["politeness"] <= 3:
            tone = "angry" if trait_values["emotional_volatility"] >= 7 else "frustrated"
        elif trait_values["politeness"] >= 7:
            tone = "polite"
        else:
            tone = "neutral"

        if formality == "slang":
            abbreviation_use = "high"
        elif formality == "casual":
            abbreviation_use = "medium"
        else:
            abbreviation_use = "low"

        style = PersonaStyle(
            tone=tone,
            formality=formality,
            typo_rate=typo_rate,
            abbreviation_use=abbreviation_use,
            emoji_use=emoji_use,
        )

        # Edge behaviours derived from the sampled traits
        edge = PersonaEdgeBehaviors(
            rage_quits=trait_values["patience"] <= 3 and trait_values["emotional_volatility"] >= 7,
            changes_mind=trait_values["decision_speed"] <= 3,
            provides_incomplete_info=trait_values["clarity"] <= 3,
            asks_off_topic=trait_values["verbosity"] >= 8 and trait_values["clarity"] <= 4,
            tests_boundaries=trait_values["trust_level"] <= 2 and trait_values["politeness"] <= 3,
        )

        name = name_pool[i % len(name_pool)] if name_pool else f"Production User {i + 1}"

        personas.append(Persona(
            persona_id=str(uuid.uuid4()),
            name=name,
            agent_type=agent_type,
            source=PRODUCTION_SOURCE,
            traits=traits,
            style=style,
            edge_behaviors=edge,
            sample_messages=[],
            created_at=now,
            tags=["production_grounded"],
        ))

    return personas
