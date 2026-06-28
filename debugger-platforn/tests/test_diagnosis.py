"""
Offline tests for the Phase D diagnosis system.
No API key required — all AI calls are bypassed or mocked.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.diagnosis.clustering import FailureClusterer
from src.diagnosis.models import (
    FailureCluster,
    FailureExample,
    RootCauseType,
    Severity,
)
from src.diagnosis.minimal_reproducer import MinimalReproducer
from src.diagnosis.priority_ranker import PriorityRanker
from src.diagnosis.root_cause_analyzer import RootCauseAnalyzer


# ---------------------------------------------------------------
# Helpers to build synthetic failures
# ---------------------------------------------------------------

def _make_failure(
    reason: str,
    scenario: str = "Product inquiry",
    persona: str = "Tester",
    turns: int = 3,
    difficulty: str = "medium",
    coverage_goal: str = "tool_coverage",
    chaos_events: list | None = None,
) -> dict:
    return {
        "test_id": str(uuid.uuid4()),
        "test_number": 1,
        "scenario": scenario,
        "persona": persona,
        "difficulty": difficulty,
        "coverage_goal": coverage_goal,
        "status": "failed",
        "failure_reason": reason,
        "total_turns": turns,
        "duration_sec": 0.5,
        "cost_usd": 0.0,
        "chaos_events": chaos_events or [],
        "trace_file": "",
    }


# ---------------------------------------------------------------
# Test 1: Clustering determinism
# ---------------------------------------------------------------

@patch("src.diagnosis.clustering._load_trace", return_value=None)
def test_clustering_determinism(_mock_trace):
    """25 failures with 3 distinct patterns should cluster consistently."""
    failures = []
    # Pattern A: service_unavailable (10 failures)
    for _ in range(10):
        failures.append(_make_failure(
            "Agent error: Mock agent error: service unavailable",
            scenario="Purchase decision (boundary testing)",
        ))
    # Pattern B: max turns exceeded (10 failures)
    for _ in range(10):
        failures.append(_make_failure(
            "Max turns exceeded (20)",
            scenario="Product inquiry (boundary testing)",
            turns=40,
        ))
    # Pattern C: timeout (5 failures)
    for _ in range(5):
        failures.append(_make_failure(
            "Agent error: timeout waiting for response",
            scenario="Comparison shopping (tool failure)",
            coverage_goal="stressor:timeout",
        ))

    clusterer = FailureClusterer(use_embeddings=False)
    groups_a = clusterer.cluster_failures(failures)
    groups_b = clusterer.cluster_failures(failures)

    # Same number of clusters
    assert len(groups_a) == len(groups_b)

    # Same cluster sizes (sorted)
    sizes_a = sorted(len(g) for g in groups_a)
    sizes_b = sorted(len(g) for g in groups_b)
    assert sizes_a == sizes_b

    # At least 2 clusters (the patterns are quite distinct)
    assert len(groups_a) >= 2


# ---------------------------------------------------------------
# Test 2: Root-cause heuristic (parametrized)
# ---------------------------------------------------------------

@pytest.mark.parametrize(
    "reason, expected_type",
    [
        ("Agent error: Mock agent error: service unavailable", "service_unavailable"),
        ("Max turns exceeded (20)", "timeout_handling"),
        ("Agent error: internal failure in tool call", "error_handling"),
    ],
)
@patch("src.diagnosis.root_cause_analyzer._load_trace", return_value=None)
def test_root_cause_heuristic(_mock_trace, reason, expected_type):
    """Heuristic root-cause analysis should detect well-known patterns."""
    failures = [_make_failure(reason) for _ in range(6)]
    analyzer = RootCauseAnalyzer(use_ai=False)
    root_type, description, pattern, indicators = analyzer.analyze_cluster(failures)

    assert root_type == expected_type
    assert len(description) > 10
    assert len(pattern) > 5
    assert isinstance(indicators, list)


# ---------------------------------------------------------------
# Test 3: Minimal reproducer (offline)
# ---------------------------------------------------------------

@patch("src.diagnosis.minimal_reproducer._load_trace", return_value=None)
def test_minimal_reproducer_offline(_mock_trace):
    """Offline reproducer picks shortest failure and produces valid structure."""
    examples = [
        FailureExample(
            test_id="a",
            test_number=1,
            scenario="Product inquiry",
            persona="Tester",
            failure_reason="service unavailable",
            turn_count=10,
            tools_expected=["search"],
        ),
        FailureExample(
            test_id="b",
            test_number=2,
            scenario="Product inquiry",
            persona="Tester",
            failure_reason="service unavailable",
            turn_count=3,
            tools_expected=["search"],
        ),
    ]

    cluster = FailureCluster(
        cluster_id="c1",
        cluster_name="Test Cluster",
        failure_count=2,
        failure_examples=examples,
        root_cause_type=RootCauseType.SERVICE_UNAVAILABLE,
        root_cause_description="Service errors",
        common_pattern="service unavailable",
        severity=Severity.HIGH,
    )

    reproducer = MinimalReproducer(use_ai=False)
    result = reproducer.generate(cluster)

    assert "minimal_conversation" in result
    assert "setup" in result
    assert "expected_behavior" in result
    assert "actual_behavior" in result
    assert "steps_to_reproduce" in result
    assert isinstance(result["steps_to_reproduce"], list)


# ---------------------------------------------------------------
# Test 4: Priority ranker ordering
# ---------------------------------------------------------------

def test_priority_ranker():
    """CRITICAL clusters should rank above MEDIUM, which rank above LOW."""
    clusters = [
        FailureCluster(
            cluster_id="low",
            cluster_name="Low",
            failure_count=2,
            failure_examples=[],
            root_cause_type=RootCauseType.TOOL_SCHEMA_MISMATCH,
            root_cause_description="Schema issue",
            common_pattern="schema",
            severity=Severity.LOW,
            affected_scenarios=["s1"],
            affected_tools=["t1"],
        ),
        FailureCluster(
            cluster_id="critical",
            cluster_name="Critical",
            failure_count=10,
            failure_examples=[],
            root_cause_type=RootCauseType.HALLUCINATION,
            root_cause_description="Hallucination",
            common_pattern="made up data",
            severity=Severity.CRITICAL,
            affected_scenarios=["s1", "s2", "s3"],
            affected_tools=["t1", "t2"],
        ),
        FailureCluster(
            cluster_id="medium",
            cluster_name="Medium",
            failure_count=5,
            failure_examples=[],
            root_cause_type=RootCauseType.TIMEOUT_HANDLING,
            root_cause_description="Timeouts",
            common_pattern="max turns",
            severity=Severity.MEDIUM,
            affected_scenarios=["s1", "s2"],
            affected_tools=["t1"],
        ),
    ]

    ranker = PriorityRanker()
    ranking = ranker.rank(clusters, total_tests=100)

    assert ranking[0] == "critical"
    assert ranking[1] == "medium"
    assert ranking[2] == "low"
