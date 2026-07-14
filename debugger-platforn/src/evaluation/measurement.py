"""
Measurement engine for the predictive-validity study (RQ1-RQ4).

Builds on :mod:`src.evaluation.predictive_validity` (signal matching) and adds
everything the research questions need:

  RQ1  per-category precision/recall/F1 of synthetic failures against
       production ground truth over the shared taxonomy
  RQ2  characterisation of the categories synthetic testing misses
  RQ3  paired significance testing (sign-flip permutation over per-signal
       coverage) + bootstrap confidence intervals for arm comparison
  RQ4  recall-versus-budget curves for ranking generation methods

Everything is pure computation over already-collected artefacts — no LLM and
no network access anywhere in this module.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Sequence

from src.evaluation.predictive_validity import (
    ProductionSignal,
    _matches,
    compute_predictive_validity,
)
from src.evaluation.taxonomy import CATEGORY_SEVERITY, FailureCategory

# ----------------------------------------------------------------------
# RQ1: per-category breakdown
# ----------------------------------------------------------------------


def signal_coverage(
    synthetic_failures: List[Dict[str, Any]],
    signals: Sequence[ProductionSignal],
) -> List[bool]:
    """Per-signal binary coverage: was each production signal matched by at
    least one synthetic failure?  Order follows *signals*."""
    return [any(_matches(s, sig) for s in synthetic_failures) for sig in signals]


def per_category_validity(
    synthetic_failures: List[Dict[str, Any]],
    signals: Sequence[ProductionSignal],
) -> Dict[str, Dict[str, Any]]:
    """Precision/recall/F1 broken down by shared-taxonomy category."""
    out: Dict[str, Dict[str, Any]] = {}
    for category in FailureCategory:
        cat_signals = [s for s in signals if s.failure_category == category]
        cat_synth = [
            s for s in synthetic_failures
            if str(s.get("failure_category")) == category.value
        ]
        if not cat_signals and not cat_synth:
            continue
        result = compute_predictive_validity(cat_synth, list(cat_signals))
        out[category.value] = {
            "severity": CATEGORY_SEVERITY[category],
            "n_production_signals": len(cat_signals),
            "n_synthetic_failures": len(cat_synth),
            "precision": result["precision"],
            "recall": result["recall"],
            "f1": result["f1"],
        }
    return out


# ----------------------------------------------------------------------
# RQ2: coverage-gap characterisation
# ----------------------------------------------------------------------


def coverage_gaps(
    synthetic_failures: List[Dict[str, Any]],
    signals: Sequence[ProductionSignal],
    ground_truth_failures: Optional[List[Any]] = None,
    recall_threshold: float = 0.25,
) -> List[Dict[str, Any]]:
    """Identify and characterise the failure categories synthetic testing
    systematically misses (recall below *recall_threshold*).

    When *ground_truth_failures* (GroundTruthFailure objects) are provided,
    each gap is enriched with descriptive statistics of the underlying
    conversations — the "what characterises them" half of RQ2.
    """
    per_cat = per_category_validity(synthetic_failures, signals)
    gaps: List[Dict[str, Any]] = []
    for value, stats in per_cat.items():
        if stats["n_production_signals"] == 0 or stats["recall"] >= recall_threshold:
            continue
        gap: Dict[str, Any] = {
            "category": value,
            "severity": stats["severity"],
            "n_production_signals": stats["n_production_signals"],
            "recall": stats["recall"],
        }
        if ground_truth_failures:
            related = [
                f for f in ground_truth_failures
                if value in getattr(f, "shared_categories", [])
            ]
            if related:
                msg_counts = [f.message_count for f in related]
                gap["characterisation"] = {
                    "n_conversations": len(related),
                    "avg_message_count": round(sum(msg_counts) / len(msg_counts), 1),
                    "max_message_count": max(msg_counts),
                    "long_horizon_share": round(
                        sum(1 for m in msg_counts if m > 40) / len(msg_counts), 3
                    ),
                    "escalated_share": round(
                        sum(1 for f in related if f.escalated) / len(related), 3
                    ),
                    "avg_failure_score": round(
                        sum(f.failure_score for f in related) / len(related), 2
                    ),
                }
        gaps.append(gap)
    gaps.sort(key=lambda g: (-g["n_production_signals"], g["recall"]))
    return gaps


# ----------------------------------------------------------------------
# RQ4: recall-versus-budget curves
# ----------------------------------------------------------------------


def recall_vs_budget(
    failures_per_test: Sequence[List[Dict[str, Any]]],
    signals: Sequence[ProductionSignal],
    budget_points: Optional[Sequence[int]] = None,
) -> List[Dict[str, Any]]:
    """Recall achieved by the first *k* tests, for increasing k.

    Args:
        failures_per_test: synthetic failures grouped by test, in suite
            execution order (element i = failures test i can surface / did
            surface).  The unit of budget is one test conversation.
        signals: production signals to cover.
        budget_points: budgets to report; defaults to every test count from
            1..N (plus 0).

    Returns:
        list of {"budget": k, "recall": r, "n_matched": m} points.
    """
    n_tests = len(failures_per_test)
    if budget_points is None:
        budget_points = range(0, n_tests + 1)

    # Incrementally accumulate coverage per signal to keep this O(N*S)
    covered = [False] * len(signals)
    recall_at: Dict[int, float] = {}
    matched_at: Dict[int, int] = {}

    def _record(k: int) -> None:
        m = sum(covered)
        matched_at[k] = m
        recall_at[k] = round(m / len(signals), 4) if signals else 0.0

    _record(0)
    for i, failures in enumerate(failures_per_test, start=1):
        for j, sig in enumerate(signals):
            if not covered[j] and any(_matches(s, sig) for s in failures):
                covered[j] = True
        _record(i)

    points = []
    for k in budget_points:
        k = min(k, n_tests)
        points.append({"budget": k, "recall": recall_at[k], "n_matched": matched_at[k]})
    return points


# ----------------------------------------------------------------------
# RQ3: uncertainty + significance
# ----------------------------------------------------------------------


def bootstrap_recall_ci(
    coverage: Sequence[bool],
    n_boot: int = 2000,
    confidence: float = 0.95,
    seed: int = 42,
) -> Dict[str, float]:
    """Percentile bootstrap CI for recall from per-signal coverage."""
    if not coverage:
        return {"recall": 0.0, "ci_low": 0.0, "ci_high": 0.0}
    rng = random.Random(seed)
    n = len(coverage)
    stats = sorted(
        sum(coverage[rng.randrange(n)] for _ in range(n)) / n
        for _ in range(n_boot)
    )
    alpha = (1 - confidence) / 2
    return {
        "recall": round(sum(coverage) / n, 4),
        "ci_low": round(stats[int(alpha * n_boot)], 4),
        "ci_high": round(stats[min(int((1 - alpha) * n_boot), n_boot - 1)], 4),
    }


def paired_permutation_test(
    coverage_a: Sequence[bool],
    coverage_b: Sequence[bool],
    n_permutations: int = 10000,
    seed: int = 42,
) -> Dict[str, Any]:
    """Sign-flip permutation test on paired per-signal coverage.

    Tests H0: arm A and arm B are equally likely to cover any given
    production signal.  Signals covered by both or by neither carry no
    information and are ignored (as in McNemar's test); for the rest the
    per-signal difference is +-1 and its sign is flipped uniformly at random
    under H0.

    Returns observed recall delta (A - B) and the two-sided p-value.
    """
    if len(coverage_a) != len(coverage_b):
        raise ValueError("coverage vectors must be paired (same signals, same order)")
    n = len(coverage_a)
    if n == 0:
        return {"delta": 0.0, "p_value": 1.0, "n_signals": 0, "n_discordant": 0}

    diffs = [int(a) - int(b) for a, b in zip(coverage_a, coverage_b)]
    observed = sum(diffs) / n
    discordant = [d for d in diffs if d != 0]

    if not discordant:
        return {"delta": 0.0, "p_value": 1.0, "n_signals": n, "n_discordant": 0}

    rng = random.Random(seed)
    extreme = 0
    for _ in range(n_permutations):
        stat = sum(d if rng.random() < 0.5 else -d for d in discordant) / n
        if abs(stat) >= abs(observed) - 1e-12:
            extreme += 1
    return {
        "delta": round(observed, 4),
        "p_value": round((extreme + 1) / (n_permutations + 1), 5),
        "n_signals": n,
        "n_discordant": len(discordant),
    }


def compare_arms(
    arm_failures: Dict[str, List[Dict[str, Any]]],
    signals: Sequence[ProductionSignal],
    baseline_arm: Optional[str] = None,
) -> Dict[str, Any]:
    """Compare generation arms on the same held-out signal set.

    Args:
        arm_failures: arm name -> synthetic failures produced by that arm.
        signals: held-out production signals (identical for every arm).
        baseline_arm: arm to test the others against (defaults to the first).

    Returns per-arm recall + CI, per-category breakdowns, and paired
    permutation tests of every other arm against the baseline.
    """
    arm_names = list(arm_failures)
    if baseline_arm is None and arm_names:
        baseline_arm = arm_names[0]

    coverages = {
        name: signal_coverage(failures, signals)
        for name, failures in arm_failures.items()
    }

    report: Dict[str, Any] = {"baseline_arm": baseline_arm, "arms": {}, "tests": {}}
    for name, failures in arm_failures.items():
        overall = compute_predictive_validity(failures, list(signals))
        report["arms"][name] = {
            "recall": overall["recall"],
            "precision": overall["precision"],
            "f1": overall["f1"],
            "recall_ci": bootstrap_recall_ci(coverages[name]),
            "per_category": per_category_validity(failures, signals),
        }
    for name in arm_names:
        if name == baseline_arm:
            continue
        report["tests"][f"{name}_vs_{baseline_arm}"] = paired_permutation_test(
            coverages[name], coverages[baseline_arm]
        )
    return report
