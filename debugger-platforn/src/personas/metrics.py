"""
Diversity metrics for persona libraries.

Provides coverage reports showing how well a set of personas spans
the trait space, edge behaviors, archetypes, and sources.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

from src.personas.models import Persona


_TRAIT_NAMES = [
    "patience", "clarity", "tech_savviness", "politeness", "verbosity",
    "emotional_volatility", "trust_level", "detail_orientation",
    "decision_speed", "language_proficiency",
]

_EDGE_BEHAVIOR_NAMES = [
    "rage_quits", "changes_mind", "provides_incomplete_info",
    "asks_off_topic", "tests_boundaries",
]


def _bucket(value: int) -> str:
    """Classify a 1-10 trait value into low/mid/high."""
    if value <= 3:
        return "low"
    if value <= 7:
        return "mid"
    return "high"


def trait_coverage_report(personas: List[Persona]) -> Dict[str, Any]:
    """Compute a diversity report for a list of personas.

    Returns a dict with:
      - trait_ranges: per-trait counts across low/mid/high buckets
      - gaps: list of (trait, bucket) pairs with zero representation
      - diversity_score: 0.0-1.0 coverage ratio
      - archetype_distribution: count per archetype
      - edge_behavior_coverage: count per edge behavior
      - source_distribution: count per source
    """
    # Trait ranges
    trait_ranges: Dict[str, Dict[str, int]] = {}
    for trait in _TRAIT_NAMES:
        buckets = {"low": 0, "mid": 0, "high": 0}
        for p in personas:
            val = getattr(p.traits, trait, 5)
            buckets[_bucket(val)] += 1
        trait_ranges[trait] = buckets

    # Gaps
    gaps: List[str] = []
    total_buckets = 0
    filled_buckets = 0
    for trait, buckets in trait_ranges.items():
        for bucket_name, count in buckets.items():
            total_buckets += 1
            if count > 0:
                filled_buckets += 1
            else:
                gaps.append(f"{trait}:{bucket_name}")

    # Diversity score
    diversity_score = filled_buckets / total_buckets if total_buckets > 0 else 0.0

    # Archetype distribution
    archetype_dist: Dict[str, int] = defaultdict(int)
    for p in personas:
        archetype_dist[p.archetype] += 1

    # Edge behavior coverage
    edge_coverage: Dict[str, int] = defaultdict(int)
    for p in personas:
        for behavior in _EDGE_BEHAVIOR_NAMES:
            if getattr(p.edge_behaviors, behavior, False):
                edge_coverage[behavior] += 1

    # Source distribution
    source_dist: Dict[str, int] = defaultdict(int)
    for p in personas:
        source_dist[p.source] += 1

    return {
        "total_personas": len(personas),
        "trait_ranges": trait_ranges,
        "gaps": gaps,
        "diversity_score": round(diversity_score, 3),
        "archetype_distribution": dict(archetype_dist),
        "edge_behavior_coverage": dict(edge_coverage),
        "source_distribution": dict(source_dist),
    }
