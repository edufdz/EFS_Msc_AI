"""
Tests for Sprint E7 quality-diversity persona selection.

Covers the MAP-Elites archive, quality metric, greedy DPP selection, and the
replacement of the cosine dedup in PersonaBuilder.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.personas.builder import PersonaBuilder
from src.personas.models import (
    Persona, PersonaTraits, PersonaStyle, PersonaEdgeBehaviors,
)
from src.personas.quality_diversity import (
    DESCRIPTOR_DIMENSIONS,
    MAPElitesArchive,
    archive_coverage,
    build_archive,
    cell_of,
    dpp_select,
    persona_quality,
    persona_rbf_kernel,
)


def _persona(
    name="P",
    *,
    formality="casual",
    volatility=5,
    tech=5,
    patience=5,
    edges=None,
) -> Persona:
    edges = edges or {}
    return Persona(
        persona_id=name,
        name=name,
        agent_type="support",
        source="template",
        traits=PersonaTraits(
            patience=patience, clarity=5, tech_savviness=tech, politeness=5,
            verbosity=5, emotional_volatility=volatility, trust_level=5,
            detail_orientation=5, decision_speed=5, language_proficiency=8,
        ),
        style=PersonaStyle(
            tone="neutral", formality=formality, typo_rate=0.0,
            abbreviation_use="low", emoji_use="none",
        ),
        edge_behaviors=PersonaEdgeBehaviors(**edges),
        sample_messages=[],
        created_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Descriptors / cells
# ---------------------------------------------------------------------------

def test_total_cells_is_162():
    total = 1
    for _name, _fn, size in DESCRIPTOR_DIMENSIONS:
        total *= size
    assert total == 162
    assert MAPElitesArchive()._total_cells() == 162


def test_cell_reflects_all_four_axes():
    base = _persona(formality="formal", volatility=1, tech=1, patience=5)
    assert cell_of(base) == (0, 0, 0, 0)

    slang = _persona(formality="slang", volatility=10, tech=10,
                     edges={"rage_quits": True, "changes_mind": True})
    # formality=2, volatility high=2, edge_count=2, tech high=2
    assert cell_of(slang) == (2, 2, 2, 2)


def test_edge_count_axis_ranges_zero_to_five():
    p0 = _persona()
    p5 = _persona(edges={
        "rage_quits": True, "changes_mind": True,
        "provides_incomplete_info": True, "asks_off_topic": True,
        "tests_boundaries": True,
    })
    assert cell_of(p0)[2] == 0
    assert cell_of(p5)[2] == 5


def test_unknown_formality_defaults_to_mid_bucket():
    p = _persona(formality="mumble")
    assert cell_of(p)[0] == 1  # falls back to "casual" bucket, no KeyError


# ---------------------------------------------------------------------------
# Quality metric
# ---------------------------------------------------------------------------

def test_quality_rewards_extremity():
    neutral = _persona(patience=5)
    extreme = _persona(patience=1, edges={"rage_quits": True, "tests_boundaries": True})
    assert persona_quality(neutral) == 0.0
    # 2 edges + abs(5-1)=4 -> 6
    assert persona_quality(extreme) == 6.0
    assert persona_quality(extreme) > persona_quality(neutral)


# ---------------------------------------------------------------------------
# MAP-Elites archive
# ---------------------------------------------------------------------------

def test_archive_keeps_higher_quality_per_cell():
    archive = MAPElitesArchive()
    low = _persona("low", patience=5)                      # quality 0
    high = _persona("high", patience=1,                    # same cell, quality 4
                    edges={})
    assert cell_of(low) == cell_of(high)
    assert archive.add(low) is True
    assert archive.add(high) is True                       # beats incumbent
    assert archive.grid[cell_of(high)].name == "high"
    # A weaker persona in the same cell is rejected.
    weaker = _persona("weak", patience=5)
    assert archive.add(weaker) is False
    assert len(archive.grid) == 1


def test_archive_coverage_increases_with_distinct_cells():
    archive = MAPElitesArchive()
    archive.add(_persona("a", formality="formal", volatility=1, tech=1))
    c1 = archive.coverage()
    archive.add(_persona("b", formality="slang", volatility=10, tech=10))
    c2 = archive.coverage()
    assert c2 > c1
    assert c2 == 2 / 162


def test_would_accept_does_not_mutate():
    archive = MAPElitesArchive()
    p = _persona("a")
    archive.add(p)
    before = len(archive.grid)
    # Weaker same-cell persona would not be accepted.
    assert archive.would_accept(_persona("b", patience=5)) is False
    # Stronger same-cell persona would be accepted, but not inserted.
    assert archive.would_accept(_persona("c", patience=1)) is True
    assert len(archive.grid) == before


def test_select_diverse_returns_subset_within_budget():
    personas = [
        _persona(f"p{i}", formality=f, volatility=v, tech=t)
        for i, (f, v, t) in enumerate([
            ("formal", 1, 1), ("casual", 5, 5), ("slang", 10, 10),
            ("formal", 10, 5), ("slang", 1, 10),
        ])
    ]
    archive = build_archive(personas)
    chosen = archive.select_diverse(3)
    assert len(chosen) == 3
    assert len({cell_of(p) for p in chosen}) == 3  # distinct cells
    # Budget >= elites returns everything.
    assert len(archive.select_diverse(99)) == len(archive.grid)
    assert archive.select_diverse(0) == []


# ---------------------------------------------------------------------------
# DPP selection
# ---------------------------------------------------------------------------

def test_dpp_select_budget_bounds():
    personas = [_persona(f"p{i}", tech=1 + i) for i in range(6)]
    assert dpp_select(personas, persona_rbf_kernel, 0) == []
    assert len(dpp_select(personas, persona_rbf_kernel, 3)) == 3
    assert len(dpp_select(personas, persona_rbf_kernel, 10)) == 6  # budget >= n


def test_dpp_prefers_spread_over_near_duplicates():
    # Three near-identical low-tech personas + one very different high-tech one.
    cluster = [_persona(f"c{i}", tech=1, patience=5) for i in range(3)]
    outlier = _persona("outlier", tech=10, patience=1,
                       edges={"tests_boundaries": True})
    items = cluster + [outlier]
    chosen = dpp_select(items, persona_rbf_kernel, 2)
    names = {p.name for p in chosen}
    # The diverse pair should include the outlier rather than two clones.
    assert "outlier" in names


# ---------------------------------------------------------------------------
# Builder integration — dedup replacement
# ---------------------------------------------------------------------------

def _agent_map():
    return {"metadata": {"type": "support", "purpose": "help"}, "components": {"tools": []}}


def test_insert_map_elites_replaces_weaker_incumbent():
    builder = PersonaBuilder(_agent_map())
    weak = _persona("weak", patience=5)
    strong = _persona("strong", patience=1)  # same cell, higher quality (|5-1|=4)
    assert cell_of(weak) == cell_of(strong)

    assert builder._insert_persona_map_elites(weak) is True
    assert builder._insert_persona_map_elites(strong) is True  # replaces weak
    names = {p.name for p in builder.personas}
    assert names == {"strong"}                                  # weak evicted
    assert len(builder.personas) == 1


def test_insert_map_elites_fills_new_cells():
    builder = PersonaBuilder(_agent_map())
    a = _persona("a", formality="formal", volatility=1, tech=1)
    b = _persona("b", formality="slang", volatility=10, tech=10)
    assert builder._insert_persona_map_elites(a) is True
    assert builder._insert_persona_map_elites(b) is True
    assert len(builder.personas) == 2


def test_is_duplicate_predicate_backward_compatible():
    builder = PersonaBuilder(_agent_map())
    p = _persona("a", patience=5)
    builder.personas.append(p)
    # Same-cell, not more failure-revealing -> duplicate.
    assert builder._is_duplicate(_persona("b", patience=5)) is True
    # Same-cell but strictly higher quality -> not a duplicate (adds value).
    assert builder._is_duplicate(_persona("c", patience=1)) is False
    # Different cell -> not a duplicate.
    assert builder._is_duplicate(
        _persona("d", formality="slang", volatility=10, tech=10)
    ) is False


def test_report_diversity_includes_map_elites_coverage():
    builder = PersonaBuilder(_agent_map())
    builder.personas.extend([
        _persona("a", formality="formal", volatility=1, tech=1),
        _persona("b", formality="slang", volatility=10, tech=10),
    ])
    report = builder.report_diversity()
    # Existing keys preserved.
    assert "diversity_score" in report
    assert "trait_ranges" in report
    # New MAP-Elites keys added.
    assert report["map_elites_cells_total"] == 162
    assert report["map_elites_cells_filled"] == 2
    assert report["map_elites_coverage"] == round(2 / 162, 4)


def test_map_elites_beats_cosine_baseline_diversity():
    """The MAP-Elites archive spans more behavioural cells than a naive set of
    near-duplicate personas the old cosine dedup would have let through."""
    # Old dedup only rejected exact-name near-duplicates, so distinct-name but
    # behaviourally-identical personas all survived (1 occupied cell).
    clones = [_persona(f"clone{i}", patience=5) for i in range(6)]
    cov_clones = archive_coverage(clones)["map_elites_coverage"]

    # MAP-Elites-selected set spans distinct cells.
    builder = PersonaBuilder(_agent_map())
    for i, (f, v, t) in enumerate([
        ("formal", 1, 1), ("casual", 5, 5), ("slang", 10, 10),
        ("formal", 10, 10), ("slang", 1, 1), ("casual", 10, 1),
    ]):
        builder._insert_persona_map_elites(
            _persona(f"m{i}", formality=f, volatility=v, tech=t)
        )
    cov_map = archive_coverage(builder.personas)["map_elites_coverage"]

    assert cov_map > cov_clones
