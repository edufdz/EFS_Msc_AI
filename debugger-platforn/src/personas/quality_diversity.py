"""
Quality-Diversity persona selection (Sprint E7).

Replaces the old 0.85 cosine-similarity dedup in the PersonaBuilder with a
MAP-Elites archive over *behavioural descriptors*. MAP-Elites (Mouret &
Clune) optimises for behavioural coverage rather than mere deduplication: it
keeps the single most failure-revealing persona per behavioural cell, so the
retained set spans the descriptor space instead of just avoiding near-copies.

Two ingredients:

- ``MAPElitesArchive`` — an archive keyed by a persona's behavioural cell
  (formality x emotional-volatility x edge-behaviour-count x tech-savviness).
  Insertion keeps the higher-quality elite per cell.
- ``dpp_select`` — greedy determinantal-point-process MAP inference for a
  maximally diverse subset within a budget (Chen et al. 2018 fast greedy),
  the principled model for diverse subset selection (Kulesza & Taskar).

The low/mid/high trait bucketing (<=3 / <=7 / else) matches
``src/personas/metrics.py`` and ``src/evaluation/diversity.py`` so the
MAP-Elites cells align with the platform's 3-way trait grid.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Sequence, Tuple

import numpy as np

from src.personas.models import Persona

# The 5 boolean edge behaviours (see PersonaEdgeBehaviors).
_EDGE_BEHAVIORS = [
    "rage_quits", "changes_mind", "provides_incomplete_info",
    "asks_off_topic", "tests_boundaries",
]


def _edge_count(persona: Persona) -> int:
    """Number of active edge behaviours (0..5)."""
    e = persona.edge_behaviors
    return sum(bool(getattr(e, name, False)) for name in _EDGE_BEHAVIORS)


def _tri_bucket(value: int) -> int:
    """Low/mid/high -> 0/1/2 using the platform's <=3 / <=7 / else thresholds."""
    if value <= 3:
        return 0
    if value <= 7:
        return 1
    return 2


# Behavioural descriptors — the archive dimensions.
# Each entry is (name, extractor, cardinality). The extractor maps a Persona
# to that dimension's integer coordinate; cardinality is the number of
# distinct coordinates the dimension can take (used for total-cell counting).
#
# Archive cells: 3 (formality) x 3 (volatility) x 6 (edge count) x 3 (tech) = 162
DESCRIPTOR_DIMENSIONS: List[Tuple[str, Callable[[Persona], int], int]] = [
    ("formality_axis",
     lambda p: {"formal": 0, "casual": 1, "slang": 2}.get(p.style.formality, 1),
     3),
    ("volatility_axis",
     lambda p: _tri_bucket(p.traits.emotional_volatility),
     3),
    ("edge_count",
     _edge_count,
     6),
    ("tech_axis",
     lambda p: _tri_bucket(p.traits.tech_savviness),
     3),
]


def persona_quality(persona: Persona) -> float:
    """Failure-revealing quality of a persona (higher = better for testing).

    Per Sprint E7.2: sum of active edge behaviours + abs(5 - patience). More
    extreme personas (many edge behaviours, patience far from neutral) are more
    likely to surface agent faults, so they win their behavioural cell.
    """
    return float(_edge_count(persona) + abs(5 - persona.traits.patience))


def cell_of(
    persona: Persona,
    dimensions: Sequence[Tuple[str, Callable[[Persona], int], int]] = DESCRIPTOR_DIMENSIONS,
) -> Tuple[int, ...]:
    """Map a persona to its behavioural cell (tuple of dimension coordinates)."""
    return tuple(int(fn(persona)) for _name, fn, _size in dimensions)


class MAPElitesArchive:
    """MAP-Elites archive keeping the highest-quality persona per behavioural cell.

    ``grid`` maps a behavioural cell -> the elite Persona occupying it. Adding a
    persona whose cell is empty always succeeds; adding to an occupied cell only
    succeeds if the newcomer has strictly higher quality than the incumbent.
    """

    def __init__(
        self,
        dimensions: Sequence[Tuple[str, Callable[[Persona], int], int]] = DESCRIPTOR_DIMENSIONS,
    ):
        self.dimensions = list(dimensions)
        self.grid: Dict[Tuple[int, ...], Persona] = {}
        self._quality: Dict[Tuple[int, ...], float] = {}

    def _cell(self, persona: Persona) -> Tuple[int, ...]:
        return cell_of(persona, self.dimensions)

    def add(self, persona: Persona, quality: float | None = None) -> bool:
        """Insert a persona. Returns True if it becomes (or stays) the cell elite.

        The persona wins its cell iff the cell is empty or its quality strictly
        exceeds the incumbent's.
        """
        if quality is None:
            quality = persona_quality(persona)
        cell = self._cell(persona)
        if cell not in self.grid or quality > self._quality[cell]:
            self.grid[cell] = persona
            self._quality[cell] = quality
            return True
        return False

    def would_accept(self, persona: Persona, quality: float | None = None) -> bool:
        """Whether ``add`` would keep this persona, without mutating the archive."""
        if quality is None:
            quality = persona_quality(persona)
        cell = self._cell(persona)
        return cell not in self.grid or quality > self._quality[cell]

    def _total_cells(self) -> int:
        total = 1
        for _name, _fn, size in self.dimensions:
            total *= size
        return total

    def coverage(self) -> float:
        """Fraction of behavioural cells occupied (0.0-1.0)."""
        total = self._total_cells()
        return len(self.grid) / total if total else 0.0

    def elites(self) -> List[Persona]:
        """All current cell elites."""
        return list(self.grid.values())

    def select_diverse(self, n: int) -> List[Persona]:
        """Return up to ``n`` elites maximising behavioural coverage.

        Every elite already occupies a distinct cell, so any subset maximises
        distinct-cell coverage. When ``n`` is smaller than the number of elites
        we still want the *most spread out* subset, so we run greedy DPP over
        the elites' trait vectors; ties fall back to highest quality first.
        """
        elites = self.elites()
        if n <= 0:
            return []
        if n >= len(elites):
            return sorted(elites, key=persona_quality, reverse=True)
        return dpp_select(elites, persona_rbf_kernel, n)


# ---------------------------------------------------------------------------
# Determinantal point process — diverse subset selection (E7.4)
# ---------------------------------------------------------------------------

_TRAIT_NAMES = [
    "patience", "clarity", "tech_savviness", "politeness", "verbosity",
    "emotional_volatility", "trust_level", "detail_orientation",
    "decision_speed", "language_proficiency",
]


def _trait_vector(persona: Persona) -> np.ndarray:
    """Normalised (0-1) 10-dim trait vector for kernel similarity."""
    return np.array(
        [(getattr(persona.traits, t, 5) - 1) / 9.0 for t in _TRAIT_NAMES],
        dtype=float,
    )


def persona_rbf_kernel(a: Persona, b: Persona, gamma: float = 2.0) -> float:
    """Quality-weighted RBF similarity between two personas.

    L_ij = q_i * q_j * exp(-gamma * ||x_i - x_j||^2). The quality weighting
    biases the DPP toward high-quality (failure-revealing) items while the RBF
    term rewards behavioural spread.
    """
    xa, xb = _trait_vector(a), _trait_vector(b)
    dist2 = float(np.sum((xa - xb) ** 2))
    sim = math.exp(-gamma * dist2)
    qa = 1.0 + persona_quality(a)
    qb = 1.0 + persona_quality(b)
    return qa * qb * sim


def dpp_select(
    items: Sequence[Any],
    kernel_fn: Callable[[Any, Any], float],
    budget: int,
    epsilon: float = 1e-10,
) -> List[Any]:
    """Greedy determinantal-point-process selection of a diverse subset.

    Fast greedy MAP inference (Chen, Zhang & Zhou, NeurIPS 2018): iteratively
    adds the item with the largest marginal gain in log-determinant of the
    kernel sub-matrix, i.e. the item least redundant with those already chosen.

    Args:
        items: candidate items.
        kernel_fn: PSD similarity kernel; ``kernel_fn(x, x)`` is the item's own
            quality mass and ``kernel_fn(x, y)`` its similarity to ``y``.
        budget: maximum number of items to return.
        epsilon: stop once no remaining item adds meaningful volume.

    Returns:
        A list of up to ``budget`` items, ordered by selection (most
        representative first).
    """
    n = len(items)
    if budget <= 0 or n == 0:
        return []
    if budget >= n:
        return list(items)

    # Kernel (Gram) matrix L.
    L = np.empty((n, n), dtype=float)
    for i in range(n):
        for j in range(i, n):
            v = float(kernel_fn(items[i], items[j]))
            L[i, j] = v
            L[j, i] = v

    cis = np.zeros((budget, n), dtype=float)
    di2s = np.copy(np.diag(L))
    selected: List[int] = []

    j = int(np.argmax(di2s))
    selected.append(j)

    while len(selected) < budget:
        k = len(selected) - 1
        di2_j = di2s[j]
        if di2_j <= epsilon:
            break
        di_j = math.sqrt(di2_j)
        # Marginal gains (Cholesky-style update) for every candidate.
        eis = (L[j, :] - cis[:k, j].dot(cis[:k, :])) / di_j
        cis[k, :] = eis
        di2s = di2s - np.square(eis)
        di2s[j] = -math.inf  # never reselect
        j = int(np.argmax(di2s))
        if di2s[j] <= epsilon:
            break
        selected.append(j)

    return [items[i] for i in selected]


# ---------------------------------------------------------------------------
# Convenience helpers used by PersonaBuilder / diversity reporting
# ---------------------------------------------------------------------------

def build_archive(personas: Sequence[Persona]) -> MAPElitesArchive:
    """Build a MAP-Elites archive from a set of personas (best per cell)."""
    archive = MAPElitesArchive()
    for p in personas:
        archive.add(p)
    return archive


def archive_coverage(personas: Sequence[Persona]) -> Dict[str, Any]:
    """MAP-Elites coverage summary for a persona set (for diversity reports)."""
    archive = build_archive(personas)
    return {
        "map_elites_coverage": round(archive.coverage(), 4),
        "map_elites_cells_filled": len(archive.grid),
        "map_elites_cells_total": archive._total_cells(),
    }
