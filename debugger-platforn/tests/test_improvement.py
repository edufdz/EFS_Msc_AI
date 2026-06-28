"""
Offline tests for the Phase E improvement system.
No API key or scipy required for most tests.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.improvement.fix_applicator import FixApplicationEngine
from src.improvement.models import (
    ABTestRun,
    AppliedFix,
    DeploymentPackage,
    FixStatus,
    ImprovementReport,
    RegressionTest,
)
from src.improvement.regression_generator import RegressionTestGenerator
from src.improvement.validator import ImprovementValidator


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------

def _agent_map():
    return {
        "metadata": {"type": "sales", "purpose": "Help users buy things"},
        "components": {
            "tools": [{"name": "search"}, {"name": "checkout"}],
            "prompts": [],
        },
    }


def _diagnosis_report(n_clusters=2, n_fixes=4):
    clusters = []
    fixes = []
    for i in range(n_clusters):
        cid = str(uuid.uuid4())
        clusters.append({
            "cluster_id": cid,
            "cluster_name": f"Cluster {i + 1}",
            "failure_count": 5 + i * 3,
            "root_cause_type": "service_unavailable" if i % 2 == 0 else "timeout_handling",
            "root_cause_description": "Test description",
            "common_pattern": "pattern",
            "severity": "high" if i == 0 else "medium",
            "affected_scenarios": ["s1", "s2"],
            "minimal_reproduction": {
                "setup": {"scenario": "Test scenario", "persona": "Tester"},
                "expected_behavior": "Should work",
                "actual_behavior": "Does not work",
                "steps_to_reproduce": ["step1"],
            },
        })
        for j in range(n_fixes // n_clusters):
            fixes.append({
                "fix_id": str(uuid.uuid4()),
                "cluster_id": cid,
                "fix_type": "config_change" if j == 0 else "prompt_patch",
                "description": f"Fix {j + 1} for cluster {i + 1}",
                "changes": {
                    "rationale": "test",
                    "max_retries": {"current": 0, "proposed": 3},
                } if j == 0 else {
                    "location": "end_of_system_prompt",
                    "new_text": "Handle errors gracefully.",
                },
                "estimated_fix_rate": 0.7,
                "estimated_effort": "low",
                "risk_level": "low",
            })
    return {"clusters": clusters, "fix_proposals": fixes}


def _ab_test_run(
    baseline_pass_rate=0.65,
    fixed_pass_rate=0.85,
    p_value=0.01,
    suite="full",
) -> ABTestRun:
    delta = fixed_pass_rate - baseline_pass_rate
    return ABTestRun(
        test_id=str(uuid.uuid4()),
        run_at=datetime.now(timezone.utc),
        baseline_agent_id="baseline",
        fixed_agent_id="fixed",
        test_suite_used=suite,
        baseline_results={
            "total_tests": 50,
            "passed": int(50 * baseline_pass_rate),
            "failed": int(50 * (1 - baseline_pass_rate)),
            "errors": 0,
            "timeouts": 0,
            "pass_rate": baseline_pass_rate,
            "avg_duration_sec": 0.5,
            "total_cost_usd": 0.0,
            "avg_cost_usd": 0.0,
        },
        fixed_results={
            "total_tests": 50,
            "passed": int(50 * fixed_pass_rate),
            "failed": int(50 * (1 - fixed_pass_rate)),
            "errors": 0,
            "timeouts": 0,
            "pass_rate": fixed_pass_rate,
            "avg_duration_sec": 0.4,
            "total_cost_usd": 0.0,
            "avg_cost_usd": 0.0,
        },
        improvement={
            "pass_rate_delta": delta,
            "pass_rate_improvement_pct": delta / baseline_pass_rate * 100 if baseline_pass_rate > 0 else 0,
            "failures_fixed": 10,
            "new_failures": 0,
        },
        statistical_significance={
            "pass_rate_p_value": p_value,
            "is_significant": p_value < 0.05,
            "chi_square": 5.0,
            "test_used": "chi_square",
        },
        is_improvement=delta > 0,
        confidence_level=1 - p_value,
        recommendation="deploy",
    )


# ---------------------------------------------------------------
# Test 1: Fix applicator — dry run produces PENDING status
# ---------------------------------------------------------------

def test_fix_applicator_dry_run(tmp_path):
    """Dry-run applies should set status=PENDING and not write files."""
    agent_map = _agent_map()
    report = _diagnosis_report()

    applicator = FixApplicationEngine(agent_map, tmp_path)
    results = applicator.apply_fixes(report["fix_proposals"], dry_run=True)

    assert len(results) == len(report["fix_proposals"])
    for r in results:
        assert r.status in (FixStatus.PENDING, FixStatus.SKIPPED)

    # No files should have been written (dry run)
    files = list(tmp_path.iterdir())
    assert len(files) == 0


# ---------------------------------------------------------------
# Test 2: Fix applicator — real apply writes config.json
# ---------------------------------------------------------------

def test_fix_applicator_real_apply(tmp_path):
    """Real apply should write config.json for config_change fixes."""
    agent_map = _agent_map()
    fixes = [{
        "fix_id": "fix-1",
        "cluster_id": "c-1",
        "fix_type": "config_change",
        "description": "Add retry",
        "changes": {
            "max_retries": {"current": 0, "proposed": 3},
            "backoff_strategy": "exponential",
        },
    }]

    applicator = FixApplicationEngine(agent_map, tmp_path)
    results = applicator.apply_fixes(fixes, dry_run=False)

    assert results[0].status == FixStatus.APPLIED
    config_path = tmp_path / "config.json"
    assert config_path.exists()
    config = json.loads(config_path.read_text())
    assert config["max_retries"] == 3
    assert config["backoff_strategy"] == "exponential"


# ---------------------------------------------------------------
# Test 3: Regression test generator
# ---------------------------------------------------------------

def test_regression_generator():
    """Should generate one regression test per cluster with a fix."""
    report = _diagnosis_report(n_clusters=3, n_fixes=6)
    # Mark all fixes as applied
    applied = [
        {**f, "status": "applied"}
        for f in report["fix_proposals"]
    ]

    gen = RegressionTestGenerator()
    tests = gen.generate(report, applied)

    # At least one test per cluster that has a fix
    assert len(tests) >= 2  # may dedupe per cluster
    for t in tests:
        assert isinstance(t, RegressionTest)
        assert t.root_cause in ("service_unavailable", "timeout_handling")
        assert t.priority in ("critical", "high", "medium", "low")


# ---------------------------------------------------------------
# Test 4: Improvement validator — ready to deploy
# ---------------------------------------------------------------

def test_validator_ready_to_deploy():
    """Significant improvement with no regressions → ready to deploy."""
    run = _ab_test_run(baseline_pass_rate=0.65, fixed_pass_rate=0.85, p_value=0.001)
    fixes = [{"status": "applied", "rollback_instructions": "revert"}]

    validator = ImprovementValidator()
    report = validator.validate([run], fixes)

    assert isinstance(report, ImprovementReport)
    assert report.ready_to_deploy is True
    assert report.deployment_risk == "low"
    assert report.pass_rate_improvement > 0


# ---------------------------------------------------------------
# Test 5: Improvement validator — not ready (regressions)
# ---------------------------------------------------------------

def test_validator_not_ready_regressions():
    """Many new failures → not ready to deploy."""
    run = _ab_test_run(baseline_pass_rate=0.80, fixed_pass_rate=0.70, p_value=0.03)
    # Override improvement to show regressions
    run.improvement["new_failures"] = 8
    run.improvement["failures_fixed"] = 2
    run.improvement["pass_rate_delta"] = -0.10
    run.improvement["pass_rate_improvement_pct"] = -12.5

    fixes = [{"status": "applied", "rollback_instructions": "revert"}]

    validator = ImprovementValidator()
    report = validator.validate([run], fixes)

    assert report.ready_to_deploy is False


# ---------------------------------------------------------------
# Test 6: Fix applicator — rollback
# ---------------------------------------------------------------

def test_rollback():
    """Rollback should change status to ROLLED_BACK."""
    fix = AppliedFix(
        fix_id="f1",
        cluster_id="c1",
        fix_type="config_change",
        status=FixStatus.APPLIED,
        applied_at=datetime.now(timezone.utc),
        applied_to="config.json",
        can_rollback=True,
        rollback_instructions="Restore from backup",
    )

    applicator = FixApplicationEngine({}, Path("."))
    assert applicator.rollback_fix(fix) is True
    assert fix.status == FixStatus.ROLLED_BACK
