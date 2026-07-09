"""
APFD-Weighted Test Prioritiser (Sprint E8).

Replaces the fixed-phase allocation's random final ordering with a greedy,
APFD-optimising prioritiser.  All the existing phase methods of
:class:`~src.generator.test_suite.TestSuiteGenerator` become candidate
*generators* that feed a single pool; this module orders that pool so that
early tests maximise marginal predicted-fault coverage, weighted by
fault-proneness (risk, operational profile, failure history, oracle density).

Design notes
------------
- **Fault-proneness** (:func:`estimate_fault_proneness`) is a *static* per-test
  score combining tool risk, inverse production trace frequency (rarely-called
  tools are less exercised, hence more fault-prone — Musa's operational
  profile), a failure-history boost, oracle density, and the number of
  taxonomy faults the test can surface.
- **Marginal coverage** is computed inside the greedy loop (:func:`prioritise_suite`)
  because "how many *new* faults / tool-pairs does this test add" is only
  defined relative to the tests already selected.  The fault IDs are derived
  the same way the measurement harness builds its fault-detection matrix
  (:func:`src.evaluation.harness.infer_detectable_failures` + tool scoping),
  so greedily maximising new faults directly maximises the reported APFD.
- **Preserved priority** (Sprint E1/E3/E5 contract): production-seed tests are
  ordered first and always survive a top-N cut, then coverage-forced tests
  (interaction / transition / adversarial), then everything else.  Within each
  tier the greedy APFD ordering applies, with the covered-fault set carried
  across tiers so the tail never re-detects already-covered faults early.

APFD itself is reused from :mod:`src.evaluation.apfd`; severity weights from
:mod:`src.evaluation.taxonomy`.
"""

from __future__ import annotations

from itertools import combinations
from typing import Any, Dict, List, Optional, Set, Tuple

from src.evaluation.harness import infer_detectable_failures
from src.evaluation.taxonomy import FailureCategory

from .models import TestCase

# Risk-level -> numeric weight (matches taxonomy.SEVERITY_WEIGHTS / calculator).
_RISK_WEIGHTS: Dict[str, int] = {"critical": 4, "high": 3, "medium": 2, "low": 1}

# Failure categories whose faults are scoped per tool (mirrors the harness's
# build_fault_matrix, so prioritiser marginal coverage matches reported APFD).
_TOOL_SCOPED_CATEGORIES: Set[FailureCategory] = {
    FailureCategory.WRONG_TOOL,
    FailureCategory.MISSED_TOOL,
    FailureCategory.TOOL_MISUSE,
    FailureCategory.PII_LEAK,
    FailureCategory.EXCESSIVE_AGENCY,
}

# Coverage goals that must not be silently dropped by a budget cut (Sprint
# E3 interaction/transition targets, Sprint E5 adversarial handled separately).
_PRIORITY_GOALS: Set[str] = {
    "interaction_coverage", "tool_coverage", "tool_combination",
    "transition_coverage", "transition_pair", "round_trip",
}

# Weight of a newly-covered tool-pair relative to a newly-covered fault when
# breaking ties in the greedy selection (faults dominate; pairs refine).
_PAIR_WEIGHT = 0.25


# ----------------------------------------------------------------------
# Agent-map / trace-result accessors
# ----------------------------------------------------------------------

def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Attribute-or-key access (trace results may be objects or dicts)."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _tool_risk_map(agent_map: Dict[str, Any]) -> Dict[str, str]:
    """tool name -> risk_level from the agent map's tool inventory."""
    risk: Dict[str, str] = {}
    for tool in (agent_map or {}).get("components", {}).get("tools", []) or []:
        name = tool.get("name")
        if name:
            risk[name] = str(tool.get("risk_level", "low") or "low").lower()
    return risk


def _tool_frequency(trace_result: Any) -> Dict[str, float]:
    """tool name -> observed production call frequency (empty when unknown)."""
    freq = _get(trace_result, "tool_frequency", None)
    if isinstance(freq, dict):
        out: Dict[str, float] = {}
        for k, v in freq.items():
            try:
                out[str(k)] = float(v)
            except (TypeError, ValueError):
                continue
        return out
    return {}


def _failure_tools(trace_result: Any) -> Set[str]:
    """Tools appearing in any production failure pattern sequence."""
    tools: Set[str] = set()
    for pattern in _get(trace_result, "failure_patterns", []) or []:
        if isinstance(pattern, (list, tuple)):
            tools.update(str(t) for t in pattern)
        elif isinstance(pattern, dict):
            tools.update(str(t) for t in (pattern.get("sequence") or []))
            if pattern.get("tool"):
                tools.add(str(pattern["tool"]))
        else:
            seq = _get(pattern, "sequence", []) or []
            tools.update(str(t) for t in seq)
    return tools


# ----------------------------------------------------------------------
# Per-test derived sets (fault IDs, tool-pairs) — aligned with the harness
# ----------------------------------------------------------------------

def _test_tools(test_case: TestCase) -> Set[str]:
    tools: Set[str] = set(test_case.scenario.required_tools)
    if test_case.target_tool:
        tools.update(test_case.target_tool.split("+"))
    return {t for t in tools if t}


def _tool_pairs(test_case: TestCase) -> Set[Tuple[str, str]]:
    return set(combinations(sorted(_test_tools(test_case)), 2))


def _fault_ids(test_case: TestCase) -> Set[str]:
    """Potential fault IDs this test can detect.

    Mirrors :func:`src.evaluation.harness.build_fault_matrix`: global category
    IDs plus ``category@tool`` for tool-scoped categories.
    """
    faults: Set[str] = set()
    tools = sorted(_test_tools(test_case))
    for category in infer_detectable_failures(test_case):
        if category in _TOOL_SCOPED_CATEGORIES and tools:
            faults.update(f"{category.value}@{tool}" for tool in tools)
        else:
            faults.add(category.value)
    return faults


# ----------------------------------------------------------------------
# E8.1 Fault-proneness estimator
# ----------------------------------------------------------------------

def estimate_fault_proneness(
    test_case: TestCase,
    agent_map: Dict[str, Any],
    trace_result: Any = None,
) -> float:
    """Static fault-proneness score for a test case (higher = test earlier).

    Combines:
      - **risk weight**: sum of required/target tool risk levels
        (critical=4, high=3, medium=2, low=1);
      - **trace frequency weight**: inverse production call frequency — rarely
        exercised tools are more fault-prone (operational profile, Musa 1993);
      - **failure-history boost**: 2x when a tool appears in a production
        failure pattern;
      - **oracle density**: more attached oracles = more detection chances;
      - **taxonomy breadth**: number of failure categories/faults the test can
        surface (half-weighted so it informs but does not dominate).
    """
    tools = _test_tools(test_case)
    risk_map = _tool_risk_map(agent_map)

    risk_weight = sum(_RISK_WEIGHTS.get(risk_map.get(t, "low"), 1) for t in tools) if tools else 1

    freq = _tool_frequency(trace_result)
    trace_weight = sum(1.0 / (1.0 + freq.get(t, 0.0)) for t in tools) if freq else 0.0

    fail_tools = _failure_tools(trace_result)
    failure_multiplier = 2.0 if (fail_tools and tools & fail_tools) else 1.0

    oracle_density = len(getattr(test_case, "oracles", []) or [])
    n_faults = len(_fault_ids(test_case))

    base = risk_weight + trace_weight + oracle_density + 0.5 * n_faults
    return (base + 1.0) * failure_multiplier


# ----------------------------------------------------------------------
# E8.2 Greedy APFD-maximising ordering
# ----------------------------------------------------------------------

class _Candidate:
    __slots__ = ("tc", "idx", "faults", "pairs", "score", "tier")

    def __init__(self, tc: TestCase, idx: int, faults: Set[str],
                 pairs: Set[Tuple[str, str]], score: float, tier: int):
        self.tc = tc
        self.idx = idx
        self.faults = faults
        self.pairs = pairs
        self.score = score
        self.tier = tier


def _priority_tier(coverage_goal: str) -> int:
    """0 = production seed (never dropped), 1 = coverage-forced /
    adversarial, 2 = edge/stressor/fill."""
    if coverage_goal == "production_seed":
        return 0
    if coverage_goal in _PRIORITY_GOALS or coverage_goal.startswith("adversarial"):
        return 1
    return 2


def prioritise_suite(
    test_cases: List[TestCase],
    agent_map: Dict[str, Any],
    trace_result: Any = None,
    preserve_priority: bool = True,
) -> List[TestCase]:
    """Order candidate tests to maximise marginal predicted-fault coverage.

    Greedy additional-coverage prioritisation (near-optimal for APFD): at each
    step pick the unselected test that adds the most *new* faults (and, as a
    tie-break, new tool-pairs), preferring higher fault-proneness among ties.
    The covered-fault set persists across the whole ordering.

    When *preserve_priority* is True the candidates are partitioned into three
    tiers (seed, coverage-forced, other); the greedy runs tier-by-tier so a
    later top-N cut drops fill before coverage before seeds, honouring the
    Sprint E1/E3/E5 preservation contract.  Set it False for a pure,
    tier-agnostic APFD ordering.
    """
    if not test_cases:
        return []

    candidates: List[_Candidate] = []
    for idx, tc in enumerate(test_cases):
        candidates.append(_Candidate(
            tc=tc,
            idx=idx,
            faults=_fault_ids(tc),
            pairs=_tool_pairs(tc),
            score=estimate_fault_proneness(tc, agent_map, trace_result),
            tier=_priority_tier(tc.coverage_goal) if preserve_priority else 0,
        ))

    tiers: Dict[int, List[_Candidate]] = {0: [], 1: [], 2: []}
    for cand in candidates:
        tiers[cand.tier].append(cand)

    covered_faults: Set[str] = set()
    covered_pairs: Set[Tuple[str, str]] = set()
    ordered: List[TestCase] = []

    for tier in (0, 1, 2):
        remaining = tiers[tier]
        while remaining:
            best: Optional[_Candidate] = None
            best_key: Optional[Tuple[float, float, int]] = None
            for cand in remaining:
                new_faults = len(cand.faults - covered_faults)
                new_pairs = len(cand.pairs - covered_pairs)
                marginal = new_faults + _PAIR_WEIGHT * new_pairs
                # Higher marginal first; ties -> higher fault-proneness; then
                # lower original index (stable, deterministic).
                key = (marginal, cand.score, -cand.idx)
                if best_key is None or key > best_key:
                    best_key = key
                    best = cand
            assert best is not None
            remaining.remove(best)
            ordered.append(best.tc)
            covered_faults |= best.faults
            covered_pairs |= best.pairs

    return ordered
