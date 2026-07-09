"""
Production-Failure Seed Corpus (Sprint E1).

Converts real production failure traces (escalations, complaints, QA flags,
loops) into reproducible ``FailureSeed`` objects, stores them in a
``SeedCorpus``, and expands each seed into neighbour scenarios via small
mutations (swap persona, perturb a tool argument, change language/formality,
substitute an adjacent tool, inject noise).

Field-failure-derived tests reproduce real failures and uncover faults that
structural generation misses (Soltani et al., ICSE 2017; Jin & Orso, ICSE
2012; Musa, 1993).

Everything here is offline: trace data is read from a Phase A
``TraceAnalysisResult``-like object, a ``trace_analysis`` dict embedded in an
agent map, or a JSON file on disk. No Langfuse credentials are required —
live fetching happens upstream in Phase A, and this module degrades
gracefully when no trace data is available.
"""

from __future__ import annotations

import json
import random
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.evaluation.taxonomy import CATEGORY_SEVERITY, FailureCategory
from src.personas.models import (
    Persona,
    PersonaEdgeBehaviors,
    PersonaStyle,
    PersonaTraits,
)
from src.scenarios.models import (
    Scenario,
    ScenarioFailureConditions,
    ScenarioSuccessConditions,
)

# ----------------------------------------------------------------------
# Data model (E1.1)
# ----------------------------------------------------------------------


@dataclass
class FailureSeed:
    seed_id: str                          # UUID
    trace_id: str                         # Langfuse trace ID
    failure_category: str                 # FailureCategory value (E12 taxonomy)
    tool_sequence: List[str]              # Observed tool call sequence
    user_goal_inferred: str               # What the user was trying to do
    persona_features: Dict[str, Any]      # Extracted from trace: formality, language, etc.
    trigger_conditions: List[str]         # What caused the failure
    outcome: str                          # "escalation", "complaint", "timeout", "loop"
    conversation_snippet: List[Dict[str, Any]]  # First N turns (anonymised)
    severity: str                         # critical/high/medium/low
    created_at: datetime
    # Mutation lineage (set by mutate_seed; None for original seeds)
    mutation_type: Optional[str] = None
    parent_seed_id: Optional[str] = None


@dataclass
class SeedCorpus:
    seeds: List[FailureSeed] = field(default_factory=list)
    total_seeds: int = 0
    by_category: Dict[str, int] = field(default_factory=dict)
    by_outcome: Dict[str, int] = field(default_factory=dict)
    by_tool: Dict[str, int] = field(default_factory=dict)  # Tools involved in failures


MUTATION_TYPES = [
    "swap_persona",
    "perturb_tool_arg",
    "adjacent_tool",
    "add_noise",
    "change_language",
    "change_formality",
]

_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}

_ESCALATION_KEYWORDS = ("escalat", "handoff", "hand_off", "transfer_to_human", "human_agent")

_SNIPPET_TURNS = 6

# ----------------------------------------------------------------------
# Duck-typed access + anonymisation helpers
# ----------------------------------------------------------------------


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Read *key* from a dict or an attribute from an object."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{5,}\d")
_LONG_NUMBER_RE = re.compile(r"\b\d{5,}\b")


def _anonymise(text: str) -> str:
    """Redact obvious PII (emails, phone numbers, long IDs) from a string."""
    if not text:
        return text
    text = _EMAIL_RE.sub("[email]", text)
    text = _PHONE_RE.sub("[number]", text)
    text = _LONG_NUMBER_RE.sub("[number]", text)
    return text


def _tool_names(conv: Any) -> List[str]:
    """Extract the observed tool-call sequence from a conversation record."""
    seq = _get(conv, "tool_sequence") or []
    if seq:
        return [str(t) for t in seq]
    calls = _get(conv, "tool_calls") or _get(conv, "tools") or []
    names: List[str] = []
    for c in calls:
        if isinstance(c, str):
            names.append(c)
        else:
            name = _get(c, "tool_name") or _get(c, "name")
            if name:
                names.append(str(name))
    return names


def _messages(conv: Any) -> List[Dict[str, Any]]:
    """Extract [{role, content}, ...] turns from a conversation record."""
    raw = (
        _get(conv, "messages")
        or _get(conv, "turns")
        or _get(conv, "conversation")
        or []
    )
    out: List[Dict[str, Any]] = []
    for m in raw:
        role = str(_get(m, "role", "user") or "user")
        content = str(_get(m, "content", "") or _get(m, "text", "") or "")
        out.append({"role": role, "content": content})
    return out


def _turn_count(conv: Any, messages: List[Dict[str, Any]]) -> int:
    total = _get(conv, "total_turns")
    if isinstance(total, int) and total > 0:
        return total
    return len(messages)


# ----------------------------------------------------------------------
# Persona feature extraction (E1.2)
# ----------------------------------------------------------------------

_SPANISH_MARKERS = (
    "hola", "gracias", "por favor", "necesito", "quiero", "pedido", "ayuda",
    "buenos", "buenas", "usted", "señor", "cuándo", "dónde", "qué", "cómo",
    "está", "estoy", "tengo", "puede", "puedo", "hacer", "según",
)
_FORMAL_MARKERS = ("usted", "podría", "quisiera", "le agradezco", "estimado", "would you kindly", "dear sir")
_INFORMAL_MARKERS = ("tú", "tu ", "oye", " q ", "xq", "porfa", "hey", "yo ", "bro", "plz")
_POLITE_MARKERS = ("please", "por favor", "gracias", "thank", "thanks", "appreciate")
_RUDE_MARKERS = ("stupid", "useless", "idiot", "terrible", "inútil", "estúpido", "pésimo", "worst")

_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF☀-➿]"
)


def extract_persona_from_trace(conversation: Any) -> Dict[str, Any]:
    """Analyse a conversation's user messages for style features.

    Returns a dict compatible with :class:`PersonaTraits` / :class:`PersonaStyle`
    fields: ``formality``, ``language``, ``verbosity``, ``emoji_use``,
    ``politeness``, ``patience``, plus raw stats.
    """
    if isinstance(conversation, list):
        messages = [
            {"role": str(_get(m, "role", "user")), "content": str(_get(m, "content", ""))}
            for m in conversation
        ]
    else:
        messages = _messages(conversation)

    user_msgs = [m["content"] for m in messages if m.get("role") == "user" and m.get("content")]
    joined = " ".join(user_msgs).lower()

    # Language: Spanish vs English by marker count
    spanish_hits = sum(joined.count(m) for m in _SPANISH_MARKERS)
    language = "Spanish" if spanish_hits >= 2 else "English"

    # Formality: usted vs tú style indicators
    formal_hits = sum(joined.count(m) for m in _FORMAL_MARKERS)
    informal_hits = sum(joined.count(m) for m in _INFORMAL_MARKERS)
    formality = "formal" if formal_hits > informal_hits else "casual"

    # Verbosity from average message length (1-10 scale)
    avg_len = (sum(len(m) for m in user_msgs) / len(user_msgs)) if user_msgs else 0.0
    if avg_len <= 0:
        verbosity = 5
    elif avg_len < 40:
        verbosity = 3
    elif avg_len < 120:
        verbosity = 5
    elif avg_len < 240:
        verbosity = 7
    else:
        verbosity = 9

    # Emoji use
    emoji_count = len(_EMOJI_RE.findall(" ".join(user_msgs)))
    if emoji_count == 0:
        emoji_use = "none"
    elif emoji_count <= 2:
        emoji_use = "rare"
    elif emoji_count <= 6:
        emoji_use = "moderate"
    else:
        emoji_use = "frequent"

    # Politeness / patience
    polite_hits = sum(joined.count(m) for m in _POLITE_MARKERS)
    rude_hits = sum(joined.count(m) for m in _RUDE_MARKERS)
    if rude_hits > polite_hits:
        politeness = 2
    elif polite_hits > 0:
        politeness = 8
    else:
        politeness = 5
    patience = 3 if rude_hits > 0 else 5

    return {
        "language": language,
        "formality": formality,
        "verbosity": verbosity,
        "emoji_use": emoji_use,
        "politeness": politeness,
        "patience": patience,
        "avg_message_length": round(avg_len, 1),
        "message_count": len(user_msgs),
    }


# ----------------------------------------------------------------------
# Failure classification (E1.2)
# ----------------------------------------------------------------------


def _classify_failure(
    tool_sequence: List[str],
    turn_count: int,
    outcome_raw: str,
    had_tool_error: bool = False,
) -> str:
    """Heuristically map a failed conversation to a FailureCategory value."""
    # Ends with an escalation tool → escalation-path failure
    if tool_sequence and any(kw in tool_sequence[-1].lower() for kw in _ESCALATION_KEYWORDS):
        return FailureCategory.ESCALATION_FAILURE.value
    # Same tool called 3+ times → stuck loop
    for tool in set(tool_sequence):
        if tool_sequence.count(tool) >= 3:
            return FailureCategory.INFINITE_LOOP.value
    # Very short conversation → premature exit
    if turn_count < 2:
        return FailureCategory.PREMATURE_EXIT.value
    # A tool was called but produced a wrong/failed output
    if had_tool_error:
        return FailureCategory.WRONG_TOOL.value
    if "loop" in outcome_raw or "timeout" in outcome_raw:
        return FailureCategory.INFINITE_LOOP.value
    return FailureCategory.TOOL_MISUSE.value


_CATEGORY_OUTCOME = {
    FailureCategory.ESCALATION_FAILURE.value: "escalation",
    FailureCategory.INFINITE_LOOP.value: "loop",
    FailureCategory.PREMATURE_EXIT.value: "timeout",
    FailureCategory.WRONG_TOOL.value: "complaint",
    FailureCategory.TOOL_MISUSE.value: "complaint",
}

_KNOWN_OUTCOMES = ("escalation", "complaint", "timeout", "loop")


def _normalise_outcome(outcome_raw: str, category: str) -> str:
    o = (outcome_raw or "").lower()
    if "escalat" in o:
        return "escalation"
    for known in _KNOWN_OUTCOMES:
        if known in o:
            return known
    return _CATEGORY_OUTCOME.get(category, "complaint")


def _severity_for(category: str) -> str:
    try:
        return CATEGORY_SEVERITY[FailureCategory(category)]
    except (ValueError, KeyError):
        return "medium"


# ----------------------------------------------------------------------
# Trace-to-seed adapter (E1.2)
# ----------------------------------------------------------------------


def build_seed_corpus(trace_result: Any, agent_map: Dict) -> SeedCorpus:
    """Convert Phase A trace analysis into a deduplicated SeedCorpus.

    Accepts a ``TraceAnalysisResult``-like object or a plain dict (e.g. the
    ``trace_analysis`` section of an agent map, or a JSON traces file) with
    ``conversations`` and/or ``failure_patterns``.
    """
    seeds: List[FailureSeed] = []
    now = datetime.now(timezone.utc)

    # 1) Failed conversations → rich seeds
    conversations = _get(trace_result, "conversations", []) or []
    for conv in conversations:
        outcome_raw = str(_get(conv, "outcome", "") or "").lower()
        escalated = bool(_get(conv, "escalated", False))
        if outcome_raw == "success" and not escalated:
            continue

        tool_sequence = _tool_names(conv)
        messages = _messages(conv)
        turns = _turn_count(conv, messages)
        had_tool_error = any(
            _get(c, "success", True) is False
            for c in (_get(conv, "tool_calls") or [])
            if not isinstance(c, str)
        )

        category = _classify_failure(tool_sequence, turns, outcome_raw, had_tool_error)
        outcome = _normalise_outcome(outcome_raw, category)

        # Infer user goal from the first user message (truncated, anonymised)
        first_user = next((m["content"] for m in messages if m["role"] == "user" and m["content"]), "")
        user_goal = _anonymise(first_user)[:200] or (
            f"Complete a task involving {tool_sequence[0]}" if tool_sequence
            else "Resolve an issue with the agent"
        )

        # Trigger conditions from the last few turns before failure
        triggers: List[str] = []
        for m in messages[-3:]:
            if m["content"]:
                triggers.append(f"{m['role']}: {_anonymise(m['content'])[:120]}")
        if had_tool_error:
            triggers.append("a tool call returned an error or wrong output")
        if not triggers and tool_sequence:
            triggers.append(f"failure after tool sequence {' -> '.join(tool_sequence)}")

        snippet = [
            {"role": m["role"], "content": _anonymise(m["content"])[:300]}
            for m in messages[:_SNIPPET_TURNS]
        ]

        seeds.append(FailureSeed(
            seed_id=str(uuid.uuid4()),
            trace_id=str(_get(conv, "trace_id", "") or _get(conv, "conversation_id", "") or f"conv_{len(seeds) + 1}"),
            failure_category=category,
            tool_sequence=tool_sequence,
            user_goal_inferred=user_goal,
            persona_features=extract_persona_from_trace(conv),
            trigger_conditions=triggers,
            outcome=outcome,
            conversation_snippet=snippet,
            severity=_severity_for(category),
            created_at=now,
        ))

    # 2) Failure patterns (sequence-level, e.g. agent_map["trace_analysis"])
    failure_patterns = _get(trace_result, "failure_patterns", []) or []
    for i, pattern in enumerate(failure_patterns, start=1):
        if isinstance(pattern, (list, tuple)):
            sequence = [str(t) for t in pattern]
            count = None
        else:
            sequence = [str(t) for t in (_get(pattern, "sequence", []) or [])]
            count = _get(pattern, "count")
        category = _classify_failure(sequence, turn_count=2, outcome_raw="")
        outcome = _normalise_outcome(str(_get(pattern, "outcome", "") or ""), category)
        triggers = [f"tool sequence {' -> '.join(sequence) or '(empty)'} correlated with failure"]
        if count is not None:
            triggers.append(f"observed {count} times in production traces")
        seeds.append(FailureSeed(
            seed_id=str(uuid.uuid4()),
            trace_id=str(_get(pattern, "trace_id", "") or f"pattern_{i}"),
            failure_category=category,
            tool_sequence=sequence,
            user_goal_inferred=(
                f"Complete a task involving {sequence[0]}" if sequence
                else "Resolve an issue with the agent"
            ),
            persona_features={},
            trigger_conditions=triggers,
            outcome=outcome,
            conversation_snippet=[],
            severity=_severity_for(category),
            created_at=now,
        ))

    # 3) Deduplicate by (failure_category, tool_sequence) — keep highest severity
    best: Dict[tuple, FailureSeed] = {}
    for seed in seeds:
        key = (seed.failure_category, tuple(seed.tool_sequence))
        existing = best.get(key)
        if existing is None or (
            _SEVERITY_RANK.get(seed.severity, 0) > _SEVERITY_RANK.get(existing.severity, 0)
        ):
            best[key] = seed
    deduped = list(best.values())

    return _corpus_from_seeds(deduped)


def _corpus_from_seeds(seeds: List[FailureSeed]) -> SeedCorpus:
    by_category: Dict[str, int] = {}
    by_outcome: Dict[str, int] = {}
    by_tool: Dict[str, int] = {}
    for seed in seeds:
        by_category[seed.failure_category] = by_category.get(seed.failure_category, 0) + 1
        by_outcome[seed.outcome] = by_outcome.get(seed.outcome, 0) + 1
        for tool in set(seed.tool_sequence):
            by_tool[tool] = by_tool.get(tool, 0) + 1
    return SeedCorpus(
        seeds=seeds,
        total_seeds=len(seeds),
        by_category=by_category,
        by_outcome=by_outcome,
        by_tool=by_tool,
    )


# ----------------------------------------------------------------------
# Seed-to-scenario / seed-to-persona converters (E1.3)
# ----------------------------------------------------------------------


def seed_to_scenario(seed: FailureSeed, agent_map: Dict) -> Scenario:
    """Map a FailureSeed to a reproducible error-path Scenario."""
    agent_tools = [
        t.get("name") for t in (agent_map.get("components", {}) or {}).get("tools", [])
    ]
    # Keep observed order, dedupe, and drop tools unknown to the agent map
    # (unless the map has no tool inventory at all).
    required: List[str] = []
    for tool in seed.tool_sequence:
        if tool not in required and (not agent_tools or tool in agent_tools):
            required.append(tool)

    anchor = seed.tool_sequence[0] if seed.tool_sequence else "conversation"
    category = seed.failure_category

    # Success conditions: the opposite of what went wrong
    if category == FailureCategory.WRONG_TOOL.value:
        success = ScenarioSuccessConditions(
            tools_called=required or None, user_satisfied=True,
        )
    elif category == FailureCategory.ESCALATION_FAILURE.value:
        success = ScenarioSuccessConditions(user_satisfied=True)
    else:
        success = ScenarioSuccessConditions(
            tool_called=required[0] if required else None, user_satisfied=True,
        )

    # Failure conditions: what actually happened
    failure = ScenarioFailureConditions(
        wrong_tool_called=category in (
            FailureCategory.WRONG_TOOL.value, FailureCategory.TOOL_MISUSE.value,
        ),
        hallucinated_response=category == FailureCategory.HALLUCINATION.value,
        pii_leaked=category == FailureCategory.PII_LEAK.value,
    )

    trigger_text = "; ".join(seed.trigger_conditions[:3]) or "unknown trigger"
    description = (
        f"Reproduction of production failure (trace {seed.trace_id}): "
        f"{category} with outcome '{seed.outcome}'. Trigger conditions: {trigger_text}"
    )

    tags = ["production_failure", seed.failure_category, seed.outcome]
    if seed.mutation_type:
        tags.append(f"mutation:{seed.mutation_type}")

    return Scenario(
        scenario_id=seed.seed_id,
        title=f"Production failure: {category} in {anchor}",
        description=description,
        user_goal=seed.user_goal_inferred,
        category=agent_map.get("metadata", {}).get("type", "custom"),
        difficulty="hard",
        type="error_path",
        required_tools=required,
        optional_tools=[],
        forbidden_tools=[],
        success_conditions=success,
        failure_conditions=failure,
        tags=tags,
        estimated_turns=max(3, len(seed.conversation_snippet)),
        source="production_seed",
        base_scenario_id=seed.parent_seed_id,
        variant_type=seed.mutation_type,
        starter_openers=(
            [seed.conversation_snippet[0]["content"]]
            if seed.conversation_snippet
            and seed.conversation_snippet[0].get("role") == "user"
            and seed.conversation_snippet[0].get("content")
            else []
        ),
        created_at=seed.created_at,
    )


def seed_to_persona(seed: FailureSeed, agent_type: str = "custom") -> Persona:
    """Map a seed's extracted persona features to a Persona object."""
    features = seed.persona_features or {}
    language = features.get("language", "English")
    formality = features.get("formality", "casual")
    politeness = int(features.get("politeness", 5))

    traits = PersonaTraits(
        patience=int(features.get("patience", 5)),
        clarity=5,
        tech_savviness=5,
        politeness=politeness,
        verbosity=int(features.get("verbosity", 5)),
        language_proficiency=7 if language == "Spanish" else 8,
    )
    style = PersonaStyle(
        tone="frustrated" if politeness <= 3 else "neutral",
        formality="formal" if formality == "formal" else "casual",
        typo_rate=0.05,
        emoji_use=features.get("emoji_use", "none"),
    )
    edge = PersonaEdgeBehaviors(
        rage_quits=seed.outcome == "escalation",
        provides_incomplete_info=seed.failure_category == FailureCategory.PREMATURE_EXIT.value,
    )
    return Persona(
        persona_id=str(uuid.uuid4()),
        name=f"Production user ({seed.trace_id[:12]})",
        agent_type=agent_type,
        source="production_seed",
        traits=traits,
        style=style,
        edge_behaviors=edge,
        sample_messages=[
            m["content"] for m in seed.conversation_snippet
            if m.get("role") == "user" and m.get("content")
        ][:3],
        created_at=seed.created_at,
    )


# ----------------------------------------------------------------------
# Seed mutation engine (E1.4)
# ----------------------------------------------------------------------


def _agent_tool_names(agent_map: Optional[Dict]) -> List[str]:
    if not agent_map:
        return []
    return [
        t.get("name") for t in (agent_map.get("components", {}) or {}).get("tools", [])
        if t.get("name")
    ]


def _tool_neighbours(tool: str, agent_map: Optional[Dict]) -> List[str]:
    """Tools adjacent to *tool* in the agent's dependency graph (or, failing
    that, any other tool in the inventory)."""
    neighbours: List[str] = []
    if agent_map:
        # Behavioural-model dependency edges
        bm = agent_map.get("behavioural_model", {}) or {}
        for edge in (bm.get("dependency_graph", {}) or {}).get("edges", []) or []:
            src, tgt = _get(edge, "source"), _get(edge, "target")
            if src == tool and tgt:
                neighbours.append(tgt)
            elif tgt == tool and src:
                neighbours.append(src)
        # Graph edges (node ids prefixed with "tool_")
        node_id = f"tool_{tool.lower().replace(' ', '_')}"
        for edge in (agent_map.get("graph", {}) or {}).get("edges", []) or []:
            src, tgt = _get(edge, "source"), _get(edge, "target")
            if src == node_id and str(tgt).startswith("tool_"):
                neighbours.append(str(tgt)[len("tool_"):])
            elif tgt == node_id and str(src).startswith("tool_"):
                neighbours.append(str(src)[len("tool_"):])
    neighbours = [n for n in dict.fromkeys(neighbours) if n != tool]
    if not neighbours:
        neighbours = [t for t in _agent_tool_names(agent_map) if t != tool]
    return neighbours


def mutate_seed(
    seed: FailureSeed,
    mutation_type: str,
    agent_map: Optional[Dict] = None,
    rng: Optional[random.Random] = None,
) -> FailureSeed:
    """Produce a neighbour seed by applying one small mutation.

    Mutation types: swap_persona, perturb_tool_arg, adjacent_tool,
    add_noise, change_language, change_formality.
    """
    if mutation_type not in MUTATION_TYPES:
        raise ValueError(
            f"Unknown mutation type '{mutation_type}'. Expected one of {MUTATION_TYPES}"
        )
    rng = rng or random.Random()

    features = dict(seed.persona_features)
    sequence = list(seed.tool_sequence)
    goal = seed.user_goal_inferred
    triggers = list(seed.trigger_conditions)

    if mutation_type == "swap_persona":
        features["formality"] = "casual" if features.get("formality") == "formal" else "formal"
        features["verbosity"] = 2 if int(features.get("verbosity", 5)) >= 5 else 9
        features["patience"] = 2 if int(features.get("patience", 5)) > 3 else 8
        triggers.append("mutation: same tool sequence, different persona traits")

    elif mutation_type == "perturb_tool_arg":
        target = rng.choice(sequence) if sequence else "the first tool"
        triggers.append(
            f"mutation: argument to '{target}' perturbed (unexpected value/format, e.g. different ID format)"
        )
        goal = f"{goal} (using an unusual identifier format)"

    elif mutation_type == "adjacent_tool":
        if sequence:
            idx = rng.randrange(len(sequence))
            neighbours = _tool_neighbours(sequence[idx], agent_map)
            if neighbours:
                replacement = rng.choice(neighbours)
                triggers.append(
                    f"mutation: tool '{sequence[idx]}' replaced with neighbouring tool '{replacement}'"
                )
                sequence[idx] = replacement
            else:
                triggers.append("mutation: adjacent_tool requested but no neighbouring tool available")
        else:
            triggers.append("mutation: adjacent_tool requested but seed has no tool sequence")

    elif mutation_type == "add_noise":
        candidates = [t for t in _agent_tool_names(agent_map) if t not in sequence]
        noise = rng.choice(candidates) if candidates else None
        if noise:
            insert_at = len(sequence) // 2 if sequence else 0
            sequence.insert(insert_at, noise)
            triggers.append(f"mutation: unrelated tool call '{noise}' injected mid-sequence (user tangent)")
        else:
            triggers.append("mutation: user goes off on a tangent mid-conversation")

    elif mutation_type == "change_language":
        current = features.get("language", "English")
        features["language"] = "English" if current == "Spanish" else "Spanish"
        triggers.append(f"mutation: conversation language switched to {features['language']}")

    elif mutation_type == "change_formality":
        current = features.get("formality", "casual")
        features["formality"] = "casual" if current == "formal" else "formal"
        register = "tú (informal)" if features["formality"] == "casual" else "usted (formal)"
        triggers.append(f"mutation: register switched to {register}")

    return FailureSeed(
        seed_id=str(uuid.uuid4()),
        trace_id=seed.trace_id,
        failure_category=seed.failure_category,
        tool_sequence=sequence,
        user_goal_inferred=goal,
        persona_features=features,
        trigger_conditions=triggers,
        outcome=seed.outcome,
        conversation_snippet=list(seed.conversation_snippet),
        severity=seed.severity,
        created_at=datetime.now(timezone.utc),
        mutation_type=mutation_type,
        parent_seed_id=seed.seed_id,
    )


def expand_seed_corpus(
    corpus: SeedCorpus,
    mutations_per_seed: int = 3,
    agent_map: Optional[Dict] = None,
    rng: Optional[random.Random] = None,
) -> List[Scenario]:
    """Generate ``mutations_per_seed`` mutated variants per seed and convert
    each mutant to a Scenario."""
    rng = rng or random.Random()
    agent_map = agent_map or {}
    scenarios: List[Scenario] = []
    for seed in corpus.seeds:
        for i in range(mutations_per_seed):
            mutation_type = MUTATION_TYPES[i % len(MUTATION_TYPES)]
            mutant = mutate_seed(seed, mutation_type, agent_map=agent_map, rng=rng)
            scenarios.append(seed_to_scenario(mutant, agent_map))
    return scenarios


# ----------------------------------------------------------------------
# Offline trace-result loading
# ----------------------------------------------------------------------


def load_trace_result(
    traces_file: Optional[str] = None,
    agent_map: Optional[Dict] = None,
) -> Optional[Any]:
    """Load trace data for seeding without any Langfuse credentials.

    Priority:
      1. ``traces_file`` — a JSON file containing either
         ``{"conversations": [...], "failure_patterns": [...]}`` or a bare
         list of conversations.
      2. ``agent_map["trace_analysis"]`` — embedded by Phase A when it ran
         with ``--use-traces``.

    Returns None (gracefully) when no trace data is available.
    """
    if traces_file:
        path = Path(traces_file)
        if path.exists():
            with open(path) as f:
                data = json.load(f)
            if isinstance(data, list):
                return {"conversations": data, "failure_patterns": []}
            if isinstance(data, dict):
                return data
    if agent_map:
        trace_analysis = agent_map.get("trace_analysis")
        if trace_analysis:
            return trace_analysis
    return None
