"""
Persona-Scenario affinity scoring.

Replaces random persona assignment with weighted selection based on
how well a persona's traits and behaviors match a scenario's demands.
"""

from __future__ import annotations

import random
from typing import List

from src.personas.models import Persona
from src.scenarios.models import Scenario


def compute_affinity(persona: Persona, scenario: Scenario) -> float:
    """Score 0.0-1.0 measuring how well *persona* matches *scenario*.

    Components (max total = 1.0):
      +0.20  edge behavior matches scenario variant type
      +0.15  difficulty alignment (hard + adversarial persona)
      +0.25  tool targeting match
      +0.15  stressor scenario + volatile/impatient persona
      +0.15  edge-case scenario + edge-behavior-rich persona
      +0.10  baseline (every pairing gets a small base score)
    """
    score = 0.10  # baseline

    edge = persona.edge_behaviors

    # 1. Edge behavior ↔ variant type alignment (+0.20)
    _variant_behavior_map = {
        "interruption": "changes_mind",
        "missing_info": "provides_incomplete_info",
        "ambiguity": "provides_incomplete_info",
        "adversarial": "tests_boundaries",
        "constraint": "tests_boundaries",
    }
    if scenario.variant_type:
        matching_behavior = _variant_behavior_map.get(scenario.variant_type)
        if matching_behavior and getattr(edge, matching_behavior, False):
            score += 0.20

    # 2. Difficulty alignment (+0.15)
    archetype = persona.archetype
    if scenario.difficulty == "hard" and archetype in ("adversarial", "demanding_expert"):
        score += 0.15
    elif scenario.difficulty == "easy" and archetype == "ideal_customer":
        score += 0.15
    elif scenario.difficulty == "medium" and archetype in ("general", "confused_novice", "rambler"):
        score += 0.10

    # 3. Tool targeting match (+0.25)
    if persona.target_tool and persona.target_tool in scenario.required_tools:
        score += 0.25

    # 4. Stressor scenario + volatile/impatient persona (+0.15)
    if scenario.type == "error_path":
        volatility = persona.traits.emotional_volatility
        patience = persona.traits.patience
        if volatility >= 7 or patience <= 3:
            score += 0.15

    # 5. Edge-case scenario + edge-behavior-rich persona (+0.15)
    if scenario.type == "edge_case":
        active_edges = sum([
            edge.rage_quits, edge.changes_mind, edge.provides_incomplete_info,
            edge.asks_off_topic, edge.tests_boundaries,
        ])
        if active_edges >= 3:
            score += 0.15
        elif active_edges >= 2:
            score += 0.08

    return min(1.0, score)


def select_persona_weighted(
    personas: List[Persona],
    scenario: Scenario,
    top_k: int = 5,
) -> Persona:
    """Select a persona using affinity-weighted random from the top-k matches.

    Falls back to random.choice if the persona list is smaller than top_k.
    """
    if not personas:
        raise ValueError("No personas available for selection")

    scored = [(p, compute_affinity(p, scenario)) for p in personas]
    scored.sort(key=lambda x: x[1], reverse=True)

    # Pick from top-k candidates weighted by their score
    candidates = scored[:top_k]
    weights = [max(s, 0.01) for _, s in candidates]  # avoid zero weights
    selected = random.choices([p for p, _ in candidates], weights=weights, k=1)[0]
    return selected
