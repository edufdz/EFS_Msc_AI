"""Tests for the measurement engine (RQ1-RQ4 computations)."""

from __future__ import annotations

from src.evaluation.measurement import (
    bootstrap_recall_ci,
    compare_arms,
    coverage_gaps,
    paired_permutation_test,
    per_category_validity,
    recall_vs_budget,
    signal_coverage,
)
from src.evaluation.predictive_validity import ProductionSignal
from src.evaluation.taxonomy import FailureCategory


def _signal(i, category, tool=None):
    return ProductionSignal(
        signal_id=f"sig_{i}",
        trace_id=f"trace_{i}",
        failure_category=category,
        description="test",
        tool_involved=tool,
    )


def _failure(category, tool=None):
    return {"failure_category": category.value, "tool_involved": tool}


class TestSignalCoverage:
    def test_basic(self):
        signals = [
            _signal(1, FailureCategory.HALLUCINATION),
            _signal(2, FailureCategory.INFINITE_LOOP),
        ]
        synth = [_failure(FailureCategory.HALLUCINATION)]
        assert signal_coverage(synth, signals) == [True, False]

    def test_tool_scoping(self):
        signals = [_signal(1, FailureCategory.WRONG_TOOL, tool="book_slot")]
        assert signal_coverage([_failure(FailureCategory.WRONG_TOOL, tool="other")], signals) == [False]
        assert signal_coverage([_failure(FailureCategory.WRONG_TOOL, tool="book_slot")], signals) == [True]


class TestPerCategory:
    def test_breakdown(self):
        signals = [
            _signal(1, FailureCategory.HALLUCINATION),
            _signal(2, FailureCategory.HALLUCINATION),
            _signal(3, FailureCategory.DATA_GAP),
        ]
        synth = [_failure(FailureCategory.HALLUCINATION)]
        per_cat = per_category_validity(synth, signals)
        assert per_cat["hallucination"]["recall"] == 1.0
        assert per_cat["data_gap"]["recall"] == 0.0
        assert per_cat["data_gap"]["n_production_signals"] == 1
        # Categories absent on both sides do not appear
        assert "pii_leak" not in per_cat


class TestCoverageGaps:
    def test_gap_detection(self):
        signals = [_signal(i, FailureCategory.DATA_GAP) for i in range(4)]
        gaps = coverage_gaps([], signals)
        assert len(gaps) == 1
        assert gaps[0]["category"] == "data_gap"
        assert gaps[0]["recall"] == 0.0

    def test_covered_category_not_a_gap(self):
        signals = [_signal(1, FailureCategory.HALLUCINATION)]
        synth = [_failure(FailureCategory.HALLUCINATION)]
        assert coverage_gaps(synth, signals) == []


class TestRecallVsBudget:
    def test_monotone_curve(self):
        signals = [
            _signal(1, FailureCategory.HALLUCINATION),
            _signal(2, FailureCategory.INFINITE_LOOP),
            _signal(3, FailureCategory.DATA_GAP),
        ]
        failures_per_test = [
            [_failure(FailureCategory.HALLUCINATION)],
            [],
            [_failure(FailureCategory.INFINITE_LOOP)],
        ]
        curve = recall_vs_budget(failures_per_test, signals)
        recalls = [p["recall"] for p in curve]
        assert recalls == sorted(recalls)  # monotone non-decreasing
        assert curve[0] == {"budget": 0, "recall": 0.0, "n_matched": 0}
        assert curve[-1]["n_matched"] == 2

    def test_explicit_budget_points(self):
        signals = [_signal(1, FailureCategory.HALLUCINATION)]
        failures_per_test = [[_failure(FailureCategory.HALLUCINATION)]] * 5
        curve = recall_vs_budget(failures_per_test, signals, budget_points=[0, 2, 10])
        assert [p["budget"] for p in curve] == [0, 2, 5]  # clamped to n_tests
        assert curve[1]["recall"] == 1.0


class TestStatistics:
    def test_bootstrap_ci_brackets_recall(self):
        coverage = [True] * 30 + [False] * 70
        ci = bootstrap_recall_ci(coverage)
        assert ci["ci_low"] <= ci["recall"] <= ci["ci_high"]
        assert abs(ci["recall"] - 0.3) < 1e-9

    def test_bootstrap_empty(self):
        assert bootstrap_recall_ci([])["recall"] == 0.0

    def test_permutation_identical_arms(self):
        cov = [True, False] * 20
        result = paired_permutation_test(cov, cov)
        assert result["delta"] == 0.0
        assert result["p_value"] == 1.0

    def test_permutation_detects_large_difference(self):
        a = [True] * 40 + [False] * 10
        b = [False] * 40 + [False] * 10
        result = paired_permutation_test(a, b)
        assert result["delta"] == 0.8
        assert result["p_value"] < 0.01
        assert result["n_discordant"] == 40

    def test_permutation_requires_pairing(self):
        import pytest
        with pytest.raises(ValueError):
            paired_permutation_test([True], [True, False])


class TestCompareArms:
    def test_full_report(self):
        signals = [
            _signal(1, FailureCategory.HALLUCINATION),
            _signal(2, FailureCategory.INFINITE_LOOP),
            _signal(3, FailureCategory.DATA_GAP),
            _signal(4, FailureCategory.RESOLUTION_FAILURE),
        ]
        arms = {
            "blind": [_failure(FailureCategory.HALLUCINATION)],
            "feedback": [
                _failure(FailureCategory.HALLUCINATION),
                _failure(FailureCategory.INFINITE_LOOP),
                _failure(FailureCategory.RESOLUTION_FAILURE),
            ],
        }
        report = compare_arms(arms, signals, baseline_arm="blind")
        assert report["arms"]["blind"]["recall"] == 0.25
        assert report["arms"]["feedback"]["recall"] == 0.75
        test = report["tests"]["feedback_vs_blind"]
        assert test["delta"] == 0.5
        assert test["n_discordant"] == 2
