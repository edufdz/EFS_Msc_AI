"""
ImprovementValidator: validates improvement with statistical rigour
and produces a deployment-readiness assessment.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from .models import ABTestRun, ImprovementReport


class ImprovementValidator:
    """Consume A/B test runs and produce a validated ImprovementReport."""

    def validate(
        self,
        ab_test_runs: List[ABTestRun],
        applied_fixes: List[Dict[str, Any]],
    ) -> ImprovementReport:
        """Generate an improvement report from one or more A/B test runs."""
        if not ab_test_runs:
            raise ValueError("No A/B test runs provided")

        latest = ab_test_runs[-1]

        baseline = latest.baseline_results
        fixed = latest.fixed_results

        baseline_rate = baseline.get("pass_rate", 0.0)
        fixed_rate = fixed.get("pass_rate", 0.0)
        improvement_pct = latest.improvement.get("pass_rate_improvement_pct", 0.0)

        ci = self._confidence_interval(
            baseline_rate,
            fixed_rate,
            baseline.get("total_tests", 1),
        )

        new_failures_count = latest.improvement.get("new_failures", 0)
        new_failures_ids = [f"test_{i}" for i in range(new_failures_count)]

        ready = self._is_ready(latest, new_failures_count, applied_fixes)
        risk = self._risk(latest, new_failures_count)

        successful = sum(1 for f in applied_fixes if f.get("status") in ("applied", "pending"))
        failed = sum(1 for f in applied_fixes if f.get("status") == "failed")

        return ImprovementReport(
            report_id=str(uuid.uuid4()),
            created_at=datetime.now(timezone.utc),
            total_fixes_applied=len(applied_fixes),
            successful_fixes=successful,
            failed_fixes=failed,
            ab_test_runs=ab_test_runs,
            baseline_pass_rate=baseline_rate,
            fixed_pass_rate=fixed_rate,
            pass_rate_improvement=improvement_pct,
            baseline_avg_cost=baseline.get("avg_cost_usd", 0.0),
            fixed_avg_cost=fixed.get("avg_cost_usd", 0.0),
            cost_delta=fixed.get("avg_cost_usd", 0.0) - baseline.get("avg_cost_usd", 0.0),
            improvement_significant=latest.statistical_significance.get("is_significant", False),
            confidence_interval=ci,
            new_failures=new_failures_ids,
            regression_count=new_failures_count,
            ready_to_deploy=ready,
            deployment_risk=risk,
            rollback_plan=self._rollback_plan(applied_fixes),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _confidence_interval(
        baseline_rate: float,
        fixed_rate: float,
        n: int,
        confidence: float = 0.95,
    ) -> Dict[str, Any]:
        """95 % CI for the difference in proportions."""
        try:
            import numpy as np
            from scipy import stats

            diff = fixed_rate - baseline_rate
            se = float(np.sqrt(
                (baseline_rate * (1 - baseline_rate) / max(n, 1))
                + (fixed_rate * (1 - fixed_rate) / max(n, 1))
            ))
            z = float(stats.norm.ppf((1 + confidence) / 2))
            margin = z * se
            return {
                "improvement": diff,
                "lower_bound": diff - margin,
                "upper_bound": diff + margin,
                "confidence_level": confidence,
            }
        except ImportError:
            diff = fixed_rate - baseline_rate
            return {
                "improvement": diff,
                "lower_bound": diff,
                "upper_bound": diff,
                "confidence_level": 0.0,
            }

    @staticmethod
    def _is_ready(
        run: ABTestRun,
        new_failures: int,
        applied_fixes: List[Dict],
    ) -> bool:
        if not run.statistical_significance.get("is_significant", False):
            return False
        if new_failures > 2:
            return False
        if run.improvement.get("pass_rate_improvement_pct", 0.0) < 5:
            return False
        return True

    @staticmethod
    def _risk(run: ABTestRun, new_failures: int) -> str:
        if new_failures > 5:
            return "high"
        if new_failures > 2:
            return "medium"
        if run.improvement.get("pass_rate_improvement_pct", 0.0) < 10:
            return "medium"
        return "low"

    @staticmethod
    def _rollback_plan(applied_fixes: List[Dict]) -> str:
        lines = [
            "Rollback Plan:",
            "1. Stop the fixed agent",
            "2. Restore baseline agent from backup",
            "3. Revert applied fixes:",
        ]
        for fix in applied_fixes:
            if fix.get("status") in ("applied", "pending"):
                instr = fix.get("rollback_instructions", "No instructions")
                lines.append(f"   - {instr}")
        lines.append("4. Verify baseline agent is working")
        lines.append("5. Investigate why fixes caused regressions")
        return "\n".join(lines)
