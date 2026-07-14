"""
Production-feedback loop (the project's central research contribution).

Closes the loop the Background Report describes: real production failures
(ground truth built by :mod:`src.production`) are converted into reproducible
``FailureSeed`` objects, injected into the Phase B generator's candidate pool,
and the generator is re-run at the same budget — producing a "feedback arm"
test suite directly comparable to a "blind arm" generated without seeds.

Leakage discipline: only TRAIN-split failures may reach the generator.  Every
seed records the production conversation it came from, and
:func:`verify_no_leakage` fails hard if any held-out conversation leaked into
suite generation.  Call it before trusting any RQ3 number.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from src.coverage.calculator import build_test_configuration
from src.evaluation.taxonomy import CATEGORY_SEVERITY, FailureCategory
from src.generator.models import TestSuite
from src.generator.test_suite import TestSuiteGenerator
from src.personas.builder import PersonaBuilder
from src.production.ground_truth import GroundTruthFailure
from src.scenarios.library import ScenarioLibrary
from src.scenarios.seed_corpus import (
    FailureSeed,
    SeedCorpus,
    _anonymise,
    _corpus_from_seeds,
    expand_seed_corpus,
    extract_persona_from_trace,
    seed_to_persona,
    seed_to_scenario,
)

_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}

_OUTCOME_BY_CATEGORY = {
    "resolution_failure": "escalation",
    "escalation_failure": "escalation",
    "infinite_loop": "loop",
    "delivery_failure": "timeout",
    "premature_exit": "timeout",
    "hallucination": "complaint",
    "comprehension_failure": "complaint",
    "data_gap": "escalation",
}


class LeakageError(RuntimeError):
    """Raised when held-out production data reached the generator."""


# ----------------------------------------------------------------------
# Conversation -> seed
# ----------------------------------------------------------------------


def _conv_to_turns(conv: Dict[str, Any]) -> List[Dict[str, str]]:
    """Convert production WhatsApp messages to [{role, content}] turns."""
    turns: List[Dict[str, str]] = []
    for m in conv.get("messages") or []:
        text = (m.get("text_body") or "").strip()
        if not text:
            continue
        source = m.get("source")
        if source == "customer":
            turns.append({"role": "user", "content": text})
        elif source in ("ai_agent", "human_agent"):
            turns.append({"role": "assistant", "content": text})
        # system/template messages carry no conversational signal for seeding
    return turns


def _primary_category(failure: GroundTruthFailure) -> str:
    """Highest-severity shared category of a ground-truth failure."""
    best, best_rank = failure.shared_categories[0], -1
    for value in failure.shared_categories:
        rank = _SEVERITY_RANK[CATEGORY_SEVERITY[FailureCategory(value)]]
        if rank > best_rank:
            best, best_rank = value, rank
    return best


def production_failure_to_seed(
    failure: GroundTruthFailure,
    conv: Dict[str, Any],
    anonymise: Callable[[str], str] = _anonymise,
    snippet_turns: int = 6,
) -> FailureSeed:
    """Convert one ground-truth production failure into a FailureSeed.

    The seed snippet and inferred goal pass through *anonymise* — by default
    the built-in regex redactor; the experiment runner swaps in the full
    anonymisation pipeline when it is importable.
    """
    turns = _conv_to_turns(conv)
    category = _primary_category(failure)

    first_user = next((t["content"] for t in turns if t["role"] == "user"), "")
    user_goal = anonymise(first_user)[:200] or "Resolve a customer-support issue"

    triggers: List[str] = []
    for prod_cat, detail in (failure.evidence or {}).items():
        triggers.append(f"production signal {prod_cat}: {anonymise(str(detail))[:140]}")
    if failure.escalated:
        triggers.append("conversation escalated to a human agent")

    snippet = [
        {"role": t["role"], "content": anonymise(t["content"])[:300]}
        for t in turns[:snippet_turns]
    ]

    return FailureSeed(
        seed_id=f"prod_{failure.conversation_id}",
        trace_id=failure.conversation_id,
        failure_category=category,
        tool_sequence=list(failure.tools_involved),
        user_goal_inferred=user_goal,
        persona_features=extract_persona_from_trace(turns),
        trigger_conditions=triggers or [f"structured failure score {failure.failure_score}"],
        outcome=_OUTCOME_BY_CATEGORY.get(category, "complaint"),
        conversation_snippet=snippet,
        severity=failure.severity,
        created_at=failure.timestamp or datetime.now(timezone.utc),
    )


# ----------------------------------------------------------------------
# Corpus construction (train split only)
# ----------------------------------------------------------------------


def build_feedback_corpus(
    train_failures: List[GroundTruthFailure],
    conversations: List[Dict[str, Any]],
    per_category_cap: int = 25,
    anonymise: Callable[[str], str] = _anonymise,
) -> Tuple[SeedCorpus, Dict[str, str]]:
    """Build the seed corpus from TRAIN-split failures.

    Rather than deduplicating on (category, tool_sequence) — production tool
    logging is mostly unnamed, which would collapse every category to one
    seed — we keep up to *per_category_cap* seeds per primary category,
    preferring the highest structured failure scores (the plan's "worst
    conversations first" ordering).

    Returns the corpus and a provenance map seed_id -> conversation_id used
    by the leakage guard.
    """
    convs_by_id = {str(c.get("id")): c for c in conversations}

    by_category: Dict[str, List[GroundTruthFailure]] = {}
    for failure in train_failures:
        by_category.setdefault(_primary_category(failure), []).append(failure)

    seeds: List[FailureSeed] = []
    provenance: Dict[str, str] = {}
    for category, failures in sorted(by_category.items()):
        failures.sort(key=lambda f: -f.failure_score)
        for failure in failures[:per_category_cap]:
            conv = convs_by_id.get(failure.conversation_id)
            if conv is None:
                continue
            seed = production_failure_to_seed(failure, conv, anonymise=anonymise)
            seeds.append(seed)
            provenance[seed.seed_id] = failure.conversation_id

    return _corpus_from_seeds(seeds), provenance


# ----------------------------------------------------------------------
# Suite generation (blind arm / feedback arm)
# ----------------------------------------------------------------------


def _base_personas_and_scenarios(agent_map: Dict, language: Optional[str]):
    detected = language or agent_map.get("metadata", {}).get("conversation_language", "English")
    persona_builder = PersonaBuilder(agent_map, language=detected)
    personas = list(persona_builder.load_templates())
    personas += persona_builder.generate_tool_attack_personas()

    scenario_lib = ScenarioLibrary(agent_map, language=detected)
    scenarios = list(scenario_lib.load_templates())
    return personas, scenarios


def generate_blind_suite(
    agent_map: Dict,
    target_count: int = 100,
    rng_seed: int = 42,
    language: Optional[str] = None,
) -> TestSuite:
    """Blind arm: offline template/structural generation, no production data."""
    random.seed(rng_seed)
    personas, scenarios = _base_personas_and_scenarios(agent_map, language)
    config = build_test_configuration(agent_map)
    generator = TestSuiteGenerator(
        agent_map=agent_map,
        personas=personas,
        scenarios=scenarios,
        coverage_goals=config.coverage_goals,
        sandbox_config=config.sandbox_config,
    )
    return generator.generate(target_count=target_count)


def generate_feedback_suite(
    agent_map: Dict,
    corpus: SeedCorpus,
    provenance: Dict[str, str],
    target_count: int = 100,
    mutations_per_seed: int = 2,
    rng_seed: int = 42,
    language: Optional[str] = None,
    seed_budget_fraction: float = 0.35,
) -> Tuple[TestSuite, Set[str]]:
    """Feedback arm: the SAME generator at the SAME budget, with the
    production seed corpus injected into the candidate pool.

    Returns the suite and the set of production conversation IDs whose data
    influenced generation (for the leakage guard).
    """
    random.seed(rng_seed)
    rng = random.Random(rng_seed)

    personas, scenarios = _base_personas_and_scenarios(agent_map, language)

    # Seed-derived scenarios and personas
    seed_scenarios = [seed_to_scenario(seed, agent_map) for seed in corpus.seeds]
    agent_type = agent_map.get("metadata", {}).get("type", "custom")
    seed_personas = [seed_to_persona(seed, agent_type=agent_type) for seed in corpus.seeds]

    # Mutation-expanded neighbours (explore around each seed)
    mutant_scenarios = expand_seed_corpus(
        corpus, mutations_per_seed=mutations_per_seed, agent_map=agent_map, rng=rng,
    )

    all_scenarios = scenarios + seed_scenarios + mutant_scenarios
    all_personas = personas + seed_personas

    config = build_test_configuration(agent_map)
    generator = TestSuiteGenerator(
        agent_map=agent_map,
        personas=all_personas,
        scenarios=all_scenarios,
        coverage_goals=config.coverage_goals,
        sandbox_config=config.sandbox_config,
        seed_budget_fraction=seed_budget_fraction,
    )
    suite = generator.generate(target_count=target_count)

    used_conversations = set(provenance.values())
    return suite, used_conversations


# ----------------------------------------------------------------------
# Leakage guard
# ----------------------------------------------------------------------


def verify_no_leakage(
    used_conversation_ids: Iterable[str],
    holdout_failures: List[GroundTruthFailure],
) -> None:
    """Assert no held-out conversation influenced generation.

    Raises LeakageError naming the offending conversation IDs.  Run this
    before computing any feedback-vs-blind comparison; a leak silently
    inflates feedback-arm recall and invalidates RQ3.
    """
    holdout_ids = {f.conversation_id for f in holdout_failures}
    leaked = sorted(holdout_ids & set(used_conversation_ids))
    if leaked:
        raise LeakageError(
            f"{len(leaked)} held-out conversation(s) leaked into generation: "
            f"{leaked[:5]}{'...' if len(leaked) > 5 else ''}"
        )
