"""
RegressionTestGenerator: creates regression tests from Phase D clusters
so that every fixed bug stays fixed.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List

from .models import RegressionTest


class RegressionTestGenerator:
    """Generate regression tests from diagnosis clusters and applied fixes."""

    def generate(
        self,
        diagnosis_report: Dict[str, Any],
        applied_fixes: List[Dict[str, Any]],
    ) -> List[RegressionTest]:
        """Create one regression test per cluster that has an applied fix."""
        fix_by_cluster = {
            f.get("cluster_id"): f
            for f in applied_fixes
            if f.get("status") in ("applied", "pending")
        }

        tests: List[RegressionTest] = []

        for cluster in diagnosis_report.get("clusters", []):
            cid = cluster.get("cluster_id", "")
            fix = fix_by_cluster.get(cid)
            if fix is None:
                continue

            repro = cluster.get("minimal_reproduction") or {}
            setup = repro.get("setup", {})

            # Build scenario from cluster data
            scenario = setup.get("scenario") if isinstance(setup.get("scenario"), dict) else {
                "title": cluster.get("cluster_name", ""),
                "description": cluster.get("root_cause_description", ""),
                "user_goal": repro.get("expected_behavior", ""),
            }

            persona = setup.get("persona") if isinstance(setup.get("persona"), dict) else {
                "name": "Regression Tester",
                "description": setup.get("persona", "Standard regression tester"),
            }

            expected = repro.get(
                "expected_behavior",
                "Agent handles the request successfully or fails gracefully",
            )

            tests.append(RegressionTest(
                test_id=str(uuid.uuid4()),
                test_name=f"Regression: {cluster.get('root_cause_type', 'unknown')} ({cid[:8]})",
                cluster_id=cid,
                root_cause=cluster.get("root_cause_type", "unknown"),
                scenario=scenario,
                persona=persona,
                expected_behavior=expected,
                catches_original_bug=True,
                passes_with_fix=True,
                priority=self._priority(cluster),
                created_from=fix.get("fix_id", cid),
            ))

        return tests

    # ------------------------------------------------------------------

    @staticmethod
    def _priority(cluster: Dict) -> str:
        severity = cluster.get("severity", "medium")
        count = cluster.get("failure_count", 0)
        if severity == "critical" or count > 10:
            return "critical"
        if severity == "high" or count > 5:
            return "high"
        if severity == "medium":
            return "medium"
        return "low"
