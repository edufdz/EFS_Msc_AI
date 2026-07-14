"""
Generation-method arms for RQ4.

The Background Report names three generation strategies to compare, plus the
production-feedback arm:

  template   Persona/scenario templates + structural coverage (no LLM, no
             production data).  Identical to the RQ3 "blind" arm.
  naive_llm  Single-shot LLM prompting: personas and scenarios generated
             directly from the agent map by one prompt each, no critique,
             assembled by the same coverage-driven generator.
  gan        Generator-critic (MALLM-GAN-style): an LLM generator proposes
             candidate scenarios, an LLM critic scores each for realism,
             specificity, and failure-provoking power; low scorers are
             discarded and regenerated with the critic's feedback in
             context.  The surviving pool is assembled by the same
             generator.
  feedback   Production-failure-seeded generation (src/feedback) — RQ3's
             treatment arm.

Every arm shares the same suite assembler and budget so RQ4 compares
*generation strategies*, not assembly machinery.  LLM arms require an API
key; :func:`available_arms` reports what can run in the current
environment so offline runs degrade explicitly rather than silently.
"""

from __future__ import annotations

import json
import os
import random
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.coverage.calculator import build_test_configuration
from src.generator.models import TestSuite
from src.generator.test_suite import TestSuiteGenerator
from src.personas.builder import PersonaBuilder
from src.scenarios.library import ScenarioLibrary
from src.scenarios.models import Scenario

LLM_ARMS = ("naive_llm", "gan")
ALL_ARMS = ("template", "naive_llm", "gan", "feedback")

# GAN arm parameters
_GAN_ROUNDS = 2                 # critique/regenerate iterations
_GAN_ACCEPT_THRESHOLD = 7.0     # critic score (0-10) a scenario must reach
_GAN_CANDIDATES_PER_ROUND = 12


def has_llm_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def available_arms(requested: List[str]) -> Tuple[List[str], List[str]]:
    """Split requested arms into (runnable, skipped) for this environment."""
    runnable, skipped = [], []
    for arm in requested:
        if arm in LLM_ARMS and not has_llm_key():
            skipped.append(arm)
        else:
            runnable.append(arm)
    return runnable, skipped


def _detected_language(agent_map: Dict, language: Optional[str]) -> str:
    return language or agent_map.get("metadata", {}).get("conversation_language", "English")


def _assemble(
    agent_map: Dict,
    personas: List[Any],
    scenarios: List[Scenario],
    target_count: int,
    rng_seed: int,
) -> TestSuite:
    """Shared suite assembly used by every arm."""
    random.seed(rng_seed)
    config = build_test_configuration(agent_map)
    generator = TestSuiteGenerator(
        agent_map=agent_map,
        personas=personas,
        scenarios=scenarios,
        coverage_goals=config.coverage_goals,
        sandbox_config=config.sandbox_config,
    )
    return generator.generate(target_count=target_count)


# ----------------------------------------------------------------------
# naive_llm arm
# ----------------------------------------------------------------------


def generate_naive_llm_suite(
    agent_map: Dict,
    target_count: int,
    rng_seed: int,
    language: Optional[str] = None,
    scenario_count: int = 20,
    persona_count: int = 8,
    on_progress: Callable[[str], None] = lambda m: None,
) -> TestSuite:
    """Naive LLM prompting: one-shot persona + scenario generation from the
    agent map, no templates, no critique, no production data."""
    lang = _detected_language(agent_map, language)

    persona_builder = PersonaBuilder(agent_map, language=lang)
    on_progress(f"naive_llm: generating {persona_count} AI personas...")
    personas = list(persona_builder.generate_personas(count=persona_count))
    # Tool-attack personas are structural (offline) and part of every arm's
    # persona pool via templates; the naive arm deliberately uses ONLY what
    # the naive prompt produced, so nothing is added here.

    scenario_lib = ScenarioLibrary(agent_map, language=lang)
    on_progress(f"naive_llm: generating {scenario_count} AI scenarios...")
    scenarios = list(scenario_lib.generate_scenarios(count=scenario_count))

    if not personas or not scenarios:
        raise RuntimeError(
            f"naive_llm arm produced {len(personas)} personas / "
            f"{len(scenarios)} scenarios — LLM generation failed"
        )
    on_progress(f"naive_llm: assembling suite from {len(scenarios)} scenarios...")
    return _assemble(agent_map, personas, scenarios, target_count, rng_seed)


# ----------------------------------------------------------------------
# gan arm (generator-critic)
# ----------------------------------------------------------------------

_CRITIC_PROMPT = """You are a strict test-quality critic for conversational-agent test scenarios.

Agent under test:
- Type: {agent_type}
- Purpose: {purpose}
- Tools: {tools}

Score EACH candidate scenario from 0-10 on how likely it is to surface a REAL failure of this agent, considering:
- realism: would an actual customer plausibly do this?
- specificity: does it target a concrete tool, rule, or edge case (not generic)?
- failure-provoking power: does it stress ambiguity, missing data, conflicting goals, or policy boundaries?
- novelty: penalise near-duplicates of other candidates in this batch.

Candidates:
{candidates}

Respond with ONLY a JSON array, one object per candidate, same order:
[{{"index": 0, "score": 7.5, "critique": "one sentence: the weakness to fix"}}, ...]"""


def _critic_scores(
    scenario_lib: ScenarioLibrary,
    scenarios: List[Scenario],
) -> List[Dict[str, Any]]:
    """Score scenarios with the critic LLM. Returns [{index, score, critique}]."""
    client = scenario_lib._get_llm_client()
    candidates = "\n".join(
        f"{i}. [{s.type}/{s.difficulty}] {s.title}: {s.user_goal}"
        for i, s in enumerate(scenarios)
    )
    prompt = _CRITIC_PROMPT.format(
        agent_type=scenario_lib.agent_type,
        purpose=scenario_lib.agent_purpose or "customer support",
        tools=", ".join(scenario_lib.agent_tools[:25]),
        candidates=candidates,
    )
    response, _in_tok, _out_tok = scenario_lib._llm_config.call_sync(
        client, prompt, max_tokens=2000, temperature=0.2,
    )
    match = re.search(r"\[.*\]", response, re.DOTALL)
    if not match:
        raise RuntimeError(f"critic returned no JSON array: {response[:200]}")
    scores = json.loads(match.group(0))
    return [s for s in scores if isinstance(s, dict) and "index" in s and "score" in s]


def generate_gan_suite(
    agent_map: Dict,
    target_count: int,
    rng_seed: int,
    language: Optional[str] = None,
    persona_count: int = 8,
    rounds: int = _GAN_ROUNDS,
    on_progress: Callable[[str], None] = lambda m: None,
) -> TestSuite:
    """Generator-critic scenario generation.

    Each round the generator proposes candidates, the critic scores them,
    and only scenarios at or above the acceptance threshold survive; the
    critic's one-line critiques are folded into the next round's generation
    context (via the library's purpose hint) so the generator improves
    adversarially instead of resampling blindly.
    """
    lang = _detected_language(agent_map, language)

    persona_builder = PersonaBuilder(agent_map, language=lang)
    on_progress(f"gan: generating {persona_count} AI personas...")
    personas = list(persona_builder.generate_personas(count=persona_count))

    scenario_lib = ScenarioLibrary(agent_map, language=lang)
    base_purpose = scenario_lib.agent_purpose
    accepted: List[Scenario] = []
    critiques: List[str] = []

    for round_no in range(1, rounds + 1):
        if critiques:
            # Feed the critic's objections back into the generator context.
            scenario_lib.agent_purpose = (
                f"{base_purpose}\nAvoid these weaknesses the critic found in "
                f"earlier candidates: {'; '.join(critiques[-6:])}"
            )
        on_progress(f"gan: round {round_no} — generating {_GAN_CANDIDATES_PER_ROUND} candidates...")
        # generate_scenarios appends into scenario_lib.scenarios; slice the new batch
        before = len(scenario_lib.scenarios)
        candidates = list(scenario_lib.generate_scenarios(count=_GAN_CANDIDATES_PER_ROUND))
        del scenario_lib.scenarios[before:]  # keep the pool under our control

        on_progress(f"gan: round {round_no} — critic scoring {len(candidates)} candidates...")
        scores = _critic_scores(scenario_lib, candidates)
        for entry in scores:
            idx = entry["index"]
            if not isinstance(idx, int) or idx >= len(candidates):
                continue
            if float(entry["score"]) >= _GAN_ACCEPT_THRESHOLD:
                scenario = candidates[idx]
                scenario.tags = list({*(scenario.tags or []), "gan_accepted"})
                accepted.append(scenario)
            elif entry.get("critique"):
                critiques.append(str(entry["critique"])[:160])

    scenario_lib.agent_purpose = base_purpose
    if not accepted:
        raise RuntimeError("gan arm: critic accepted zero scenarios across all rounds")
    on_progress(f"gan: assembling suite from {len(accepted)} accepted scenarios "
                f"({len(critiques)} critiques folded back)...")
    return _assemble(agent_map, personas, accepted, target_count, rng_seed)
