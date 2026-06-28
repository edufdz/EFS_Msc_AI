"""Tests for certification scoring and certifier."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.certification.scorer import (
    score_safety_trust,
    score_reliability,
    score_tool_competency,
    score_conversation_quality,
    score_efficiency,
)
from src.certification.certifier import Certifier
from src.certification.engine import CertificationEngine
from src.certification.models import CertificationTier


# ── Scorer Tests ──


class TestScoreSafetyTrust:
    def test_perfect_score_no_clusters(self):
        result = score_safety_trust([], 100)
        assert result.score == 100.0
        assert result.weight == 0.30

    def test_hallucination_penalty(self):
        clusters = [{"root_cause_type": "hallucination", "severity": "critical", "failure_count": 5}]
        result = score_safety_trust(clusters, 100)
        assert result.score < 100
        assert result.breakdown["hallucination_penalty"] > 0

    def test_guardrail_penalty(self):
        clusters = [{"root_cause_type": "missing_guardrail", "severity": "critical", "failure_count": 2}]
        result = score_safety_trust(clusters, 100)
        assert result.score < 100
        assert result.breakdown["guardrail_penalty"] == 30  # 2 critical failures * 15

    def test_score_clamps_to_zero(self):
        clusters = [
            {"root_cause_type": "hallucination", "severity": "critical", "failure_count": 50},
            {"root_cause_type": "missing_guardrail", "severity": "critical", "failure_count": 10},
        ]
        result = score_safety_trust(clusters, 50)
        assert result.score >= 0


class TestScoreReliability:
    def test_perfect_pass_rate(self):
        result = score_reliability(100.0, 0, 100, [])
        assert result.score == 100.0
        assert result.weight == 0.25

    def test_timeout_penalty(self):
        result = score_reliability(80.0, 10, 100, [])
        assert result.score < 80
        assert result.breakdown["timeout_penalty"] > 0

    def test_error_handling_clusters(self):
        clusters = [{"root_cause_type": "error_handling"}]
        result = score_reliability(90.0, 0, 100, clusters)
        assert result.score < 90


class TestScoreToolCompetency:
    def test_full_coverage(self):
        result = score_tool_competency(100.0, [])
        assert result.score == 100.0
        assert result.weight == 0.20

    def test_tool_selection_penalty(self):
        clusters = [{"root_cause_type": "tool_selection_error"}]
        result = score_tool_competency(80.0, clusters)
        assert result.score == 70.0  # 80 - 10


class TestScoreConversationQuality:
    def test_basic_scoring(self):
        result = score_conversation_quality(90.0, {}, 10.0)
        assert result.score == 72.0  # 90 * 0.8
        assert result.weight == 0.15

    def test_difficulty_bonus(self):
        by_diff = {"hard": {"passed": 10, "failed": 0}}
        result = score_conversation_quality(90.0, by_diff, 10.0)
        assert result.score > 72.0  # base + difficulty bonus


class TestScoreEfficiency:
    def test_zero_cost(self):
        result = score_efficiency(0.0, 100, 5.0)
        assert result.score == 100.0  # cost_score=100, duration_score=100
        assert result.weight == 0.10

    def test_high_cost(self):
        result = score_efficiency(50.0, 100, 5.0)
        assert result.score < 100  # high cost per test


# ── Certifier Tests ──


class TestCertifier:
    def _make_test_report(self, **overrides):
        defaults = {
            "total_tests": 100,
            "passed": 95,
            "failed": 3,
            "errors": 1,
            "timeouts": 1,
            "pass_rate": 95.0,
            "coverage_pct": 85.0,
            "avg_duration_sec": 5.0,
            "total_cost_usd": 0.0,
            "by_difficulty": {"easy": {"passed": 40}, "medium": {"passed": 30}, "hard": {"passed": 25}},
        }
        defaults.update(overrides)
        return defaults

    def _make_agent_map(self):
        return {"metadata": {"agent_name": "TestAgent", "framework": "langchain"}}

    def test_certify_returns_report(self):
        c = Certifier()
        report = c.certify(self._make_test_report(), None, self._make_agent_map())
        assert report.certification_id.startswith("cert-")
        assert report.agent_name == "TestAgent"
        assert 0 <= report.overall_score <= 100
        assert len(report.category_scores) == 5
        assert report.issued_at is not None
        assert report.expires_at is not None

    def test_high_score_gets_gold_or_better(self):
        c = Certifier()
        report = c.certify(
            self._make_test_report(total_tests=100, passed=95, pass_rate=95.0),
            None,
            self._make_agent_map(),
        )
        assert report.tier in (CertificationTier.gold, CertificationTier.platinum)

    def test_low_pass_rate_blocks_certification(self):
        c = Certifier()
        report = c.certify(
            self._make_test_report(total_tests=50, passed=20, pass_rate=40.0, failed=30),
            None,
            self._make_agent_map(),
        )
        assert report.tier == CertificationTier.not_certified

    def test_hallucination_creates_blocker(self):
        c = Certifier()
        diag = {
            "clusters": [{
                "root_cause_type": "hallucination",
                "severity": "critical",
                "failure_count": 5,
                "failure_examples": [],
            }]
        }
        report = c.certify(self._make_test_report(), diag, self._make_agent_map())
        blocker_types = [b.blocker_type for b in report.hard_blockers]
        assert "critical_hallucination" in blocker_types

    def test_radar_chart_data(self):
        c = Certifier()
        report = c.certify(self._make_test_report(), None, self._make_agent_map())
        assert len(report.radar_chart_data) == 5
        assert "Safety & Trust" in report.radar_chart_data

    def test_confidence_metrics(self):
        c = Certifier()
        report = c.certify(self._make_test_report(), None, self._make_agent_map())
        assert report.confidence.total_simulations == 100
        assert report.confidence.sample_sufficient is True

    def test_insufficient_sims_blocks_platinum(self):
        c = Certifier()
        report = c.certify(
            self._make_test_report(total_tests=30, passed=29, pass_rate=96.7),
            None,
            self._make_agent_map(),
        )
        # 30 simulations is enough for silver but not platinum (needs 100)
        assert report.tier != CertificationTier.platinum


# ── Engine Tests ──


class TestCertificationEngine:
    def test_engine_saves_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = CertificationEngine()
            test_report = {
                "total_tests": 50,
                "passed": 45,
                "failed": 3,
                "errors": 1,
                "timeouts": 1,
                "pass_rate": 90.0,
                "coverage_pct": 80.0,
                "avg_duration_sec": 8.0,
                "total_cost_usd": 0.5,
                "by_difficulty": {},
            }
            result = engine.run(Path(tmpdir), test_report, None, {})

            assert result["tier"] in ("platinum", "gold", "silver", "not_certified")
            report_path = Path(tmpdir) / "certification_report.json"
            assert report_path.exists()

            with open(report_path) as f:
                saved = json.load(f)
            assert saved["certification_id"] == result["certification_id"]
