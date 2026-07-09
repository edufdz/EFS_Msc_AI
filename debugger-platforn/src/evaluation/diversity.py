"""
Behaviour-Space Diversity Metric (Sprint E12.4).

Measures how much of the reachable behaviour space a test suite exercises:
persona trait-space cells, scenario type x variant combinations, tool pairs,
and persona archetypes.  Archive-style coverage, in the spirit of
quality-diversity methods (MAP-Elites).
"""

from __future__ import annotations

from itertools import combinations
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

from src.generator.models import TestSuite

# The 10 numeric persona trait dimensions (see src/personas/models.py)
_TRAIT_NAMES = [
    "patience", "clarity", "tech_savviness", "politeness", "verbosity",
    "emotional_volatility", "trust_level", "detail_orientation",
    "decision_speed", "language_proficiency",
]

# Scenario types and variant types (None = base scenario, no variant)
_SCENARIO_TYPES = ["happy_path", "error_path", "edge_case"]
_VARIANT_TYPES = [
    None, "ambiguity", "missing_info", "interruption", "error",
    "adversarial", "constraint", "multi_step",
]

# Broad persona archetypes (see Persona.archetype)
_ARCHETYPES = [
    "adversarial", "demanding_expert", "confused_novice",
    "rambler", "ideal_customer", "general",
]


def _bucket(value: int) -> str:
    """Classify a 1-10 trait value into low/mid/high (same as personas.metrics)."""
    if value <= 3:
        return "low"
    if value <= 7:
        return "mid"
    return "high"


def _trait_cell(persona) -> Tuple[str, ...]:
    """Map a persona to its cell in the 3^10 low/mid/high trait grid."""
    return tuple(_bucket(getattr(persona.traits, t, 5)) for t in _TRAIT_NAMES)


def _test_tools(test_case) -> Set[str]:
    """All tools a test case exercises (scenario tools + coverage target)."""
    tools: Set[str] = set(test_case.scenario.required_tools)
    if test_case.target_tool:
        tools.update(test_case.target_tool.split("+"))
    return tools


def compute_suite_diversity(
    test_suite: TestSuite,
    agent_map: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute behaviour-space diversity for a test suite.

    Args:
        test_suite: the generated TestSuite.
        agent_map: optional agent map; when given, the tool-pair universe is
            all pairs of tools the agent exposes, otherwise it falls back to
            the tools referenced by the suite itself.

    Returns:
        dict with ``trait_coverage``, ``scenario_coverage``,
        ``tool_pair_coverage``, ``archetype_coverage``, and
        ``overall_diversity`` (mean of the four), plus supporting counts.
    """
    test_cases = test_suite.test_cases

    # --- Trait-space coverage (3^10 low/mid/high cells) ---
    trait_cells: Set[Tuple[str, ...]] = {_trait_cell(tc.persona) for tc in test_cases}
    total_trait_cells = 3 ** len(_TRAIT_NAMES)
    trait_coverage = len(trait_cells) / total_trait_cells

    # --- Scenario-type x variant-type coverage ---
    scenario_cells: Set[Tuple[str, Optional[str]]] = {
        (tc.scenario.type, tc.scenario.variant_type) for tc in test_cases
    }
    # Only count cells inside the known grid
    known_cells = {
        cell for cell in scenario_cells
        if cell[0] in _SCENARIO_TYPES and cell[1] in _VARIANT_TYPES
    }
    total_scenario_cells = len(_SCENARIO_TYPES) * len(_VARIANT_TYPES)
    scenario_coverage = len(known_cells) / total_scenario_cells

    # --- Tool-pair coverage ---
    if agent_map is not None:
        universe_tools = sorted(
            t.get("name", "")
            for t in agent_map.get("components", {}).get("tools", [])
            if t.get("name")
        )
    else:
        universe_tools = sorted({t for tc in test_cases for t in _test_tools(tc)})

    all_pairs: Set[FrozenSet[str]] = {
        frozenset(pair) for pair in combinations(universe_tools, 2)
    }
    exercised_pairs: Set[FrozenSet[str]] = set()
    for tc in test_cases:
        tools = _test_tools(tc) & set(universe_tools)
        exercised_pairs.update(frozenset(p) for p in combinations(sorted(tools), 2))
    exercised_pairs &= all_pairs
    tool_pair_coverage = len(exercised_pairs) / len(all_pairs) if all_pairs else 1.0

    # --- Archetype coverage ---
    archetypes_used = {tc.persona.archetype for tc in test_cases}
    archetype_coverage = len(archetypes_used & set(_ARCHETYPES)) / len(_ARCHETYPES)

    components = [trait_coverage, scenario_coverage, tool_pair_coverage, archetype_coverage]
    overall = sum(components) / len(components)

    return {
        "trait_coverage": round(trait_coverage, 6),
        "trait_cells_filled": len(trait_cells),
        "trait_cells_total": total_trait_cells,
        "scenario_coverage": round(scenario_coverage, 4),
        "scenario_cells_filled": len(known_cells),
        "scenario_cells_total": total_scenario_cells,
        "tool_pair_coverage": round(tool_pair_coverage, 4),
        "tool_pairs_exercised": len(exercised_pairs),
        "tool_pairs_total": len(all_pairs),
        "archetype_coverage": round(archetype_coverage, 4),
        "archetypes_used": sorted(archetypes_used),
        "overall_diversity": round(overall, 4),
    }
