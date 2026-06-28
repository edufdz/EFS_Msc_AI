"""
ABTestingFramework: runs the same test suite against a baseline and a
fixed agent, collects metrics, and applies statistical significance tests.

Uses Phase C's TestExecutionEngine + MockAgentConnector under the hood.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from .models import ABTestRun


class ABTestingFramework:
    """Compare baseline vs fixed agent on a set of test cases."""

    def __init__(
        self,
        test_suite: Dict[str, Any],
        agent_map: Dict[str, Any],
        baseline_fail_rate: float = 0.05,
        fixed_fail_rate: float = 0.01,
        max_workers: int = 10,
        language: str = "English",
    ):
        self.test_suite = test_suite
        self.agent_map = agent_map
        self.baseline_fail_rate = baseline_fail_rate
        self.fixed_fail_rate = fixed_fail_rate
        self.max_workers = max_workers
        self.language = language

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def run_smoke_test(
        self,
        affected_test_ids: List[str] | None = None,
        limit: int = 10,
    ) -> ABTestRun:
        """Run a small smoke test on critical test cases."""
        tests = self._select_tests(affected_test_ids, limit)
        return await self._run_ab(tests, suite_label="smoke")

    async def run_full_test(
        self,
        affected_test_ids: List[str] | None = None,
        limit: int = 50,
    ) -> ABTestRun:
        """Run the full test suite."""
        tests = self._select_tests(affected_test_ids, limit)
        return await self._run_ab(tests, suite_label="full")

    # ------------------------------------------------------------------
    # Core A/B runner
    # ------------------------------------------------------------------

    async def _run_ab(
        self,
        tests: List[Dict],
        suite_label: str,
    ) -> ABTestRun:
        from src.execution.agent_connector import MockAgentConnector
        from src.execution.aggregator import ResultsAggregator
        from src.execution.runner import TestExecutionEngine

        suite = {"test_cases": tests, **{k: v for k, v in self.test_suite.items() if k != "test_cases"}}

        # --- baseline ---
        baseline_connector = MockAgentConnector(
            self.agent_map,
            fail_rate=self.baseline_fail_rate,
        )
        baseline_engine = TestExecutionEngine(
            test_suite=suite,
            agent_connector=baseline_connector,
            max_workers=self.max_workers,
            use_ai_personas=False,
            language=self.language,
        )
        baseline_results = await baseline_engine.run_all()
        # drain the event queue so it doesn't block
        _drain(baseline_engine.event_queue)

        baseline_agg = ResultsAggregator(suite, baseline_results)
        baseline_report = baseline_agg.generate_report(datetime.now(timezone.utc))
        baseline_inbox = baseline_agg.generate_failure_inbox()

        # --- fixed ---
        fixed_connector = MockAgentConnector(
            self.agent_map,
            fail_rate=self.fixed_fail_rate,
        )
        fixed_engine = TestExecutionEngine(
            test_suite=suite,
            agent_connector=fixed_connector,
            max_workers=self.max_workers,
            use_ai_personas=False,
            language=self.language,
        )
        fixed_results = await fixed_engine.run_all()
        _drain(fixed_engine.event_queue)

        fixed_agg = ResultsAggregator(suite, fixed_results)
        fixed_report = fixed_agg.generate_report(datetime.now(timezone.utc))
        fixed_inbox = fixed_agg.generate_failure_inbox()

        # --- metrics ---
        baseline_metrics = _metrics(baseline_report)
        fixed_metrics = _metrics(fixed_report)
        improvement = _improvement(baseline_metrics, fixed_metrics)
        significance = _significance(baseline_metrics, fixed_metrics)

        is_improvement = improvement["pass_rate_delta"] > 0
        recommendation = _recommendation(improvement, significance)

        return ABTestRun(
            test_id=str(uuid.uuid4()),
            run_at=datetime.now(timezone.utc),
            baseline_agent_id="baseline",
            fixed_agent_id="fixed",
            test_suite_used=suite_label,
            baseline_results=baseline_metrics,
            fixed_results=fixed_metrics,
            improvement=improvement,
            statistical_significance=significance,
            is_improvement=is_improvement,
            confidence_level=max(0.0, 1.0 - significance.get("pass_rate_p_value", 1.0)),
            recommendation=recommendation,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _select_tests(
        self,
        affected_test_ids: List[str] | None,
        limit: int,
    ) -> List[Dict]:
        cases = self.test_suite.get("test_cases", [])
        if affected_test_ids:
            selected = [c for c in cases if c.get("test_id") in affected_test_ids]
            rest = [c for c in cases if c.get("test_id") not in affected_test_ids]
            selected.extend(rest[: max(0, limit - len(selected))])
            return selected[:limit]
        return cases[:limit]


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _drain(q: asyncio.Queue) -> None:
    while not q.empty():
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            break


def _metrics(report) -> Dict[str, Any]:
    return {
        "total_tests": report.total_tests,
        "passed": report.passed,
        "failed": report.failed,
        "errors": report.errors,
        "timeouts": report.timeouts,
        "pass_rate": report.pass_rate / 100.0,  # normalize to 0-1
        "avg_duration_sec": report.avg_duration_sec,
        "total_cost_usd": report.total_cost_usd,
        "avg_cost_usd": report.total_cost_usd / max(report.total_tests, 1),
    }


def _improvement(baseline: Dict, fixed: Dict) -> Dict[str, Any]:
    b_rate = baseline["pass_rate"]
    f_rate = fixed["pass_rate"]
    return {
        "pass_rate_delta": f_rate - b_rate,
        "pass_rate_improvement_pct": (
            (f_rate - b_rate) / b_rate * 100 if b_rate > 0 else 0.0
        ),
        "duration_delta_sec": fixed["avg_duration_sec"] - baseline["avg_duration_sec"],
        "cost_delta_usd": fixed["avg_cost_usd"] - baseline["avg_cost_usd"],
        "failures_fixed": max(0, baseline["failed"] - fixed["failed"]),
        "new_failures": max(0, fixed["failed"] - baseline["failed"]),
    }


def _significance(baseline: Dict, fixed: Dict) -> Dict[str, Any]:
    """Chi-square test for pass-rate difference."""
    try:
        from scipy import stats

        table = [
            [baseline["passed"], baseline["failed"] + baseline.get("errors", 0) + baseline.get("timeouts", 0)],
            [fixed["passed"], fixed["failed"] + fixed.get("errors", 0) + fixed.get("timeouts", 0)],
        ]
        # Guard: chi2_contingency needs non-zero marginals
        if all(sum(row) > 0 for row in table) and all(
            table[0][c] + table[1][c] > 0 for c in range(2)
        ):
            chi2, p_value, _, _ = stats.chi2_contingency(table)
            return {
                "pass_rate_p_value": float(p_value),
                "is_significant": bool(p_value < 0.05),
                "chi_square": float(chi2),
                "test_used": "chi_square",
            }
    except ImportError:
        pass

    # Fallback: no scipy available
    return {
        "pass_rate_p_value": 1.0,
        "is_significant": False,
        "chi_square": 0.0,
        "test_used": "none (scipy not installed)",
    }


def _recommendation(improvement: Dict, significance: Dict) -> str:
    if improvement.get("new_failures", 0) > improvement.get("failures_fixed", 0):
        return "rollback"
    if not significance.get("is_significant", False):
        return "need_more_data"
    if improvement.get("pass_rate_improvement_pct", 0) > 10:
        return "deploy"
    if improvement.get("pass_rate_improvement_pct", 0) > 5:
        return "deploy_with_monitoring"
    return "deploy_with_caution"
