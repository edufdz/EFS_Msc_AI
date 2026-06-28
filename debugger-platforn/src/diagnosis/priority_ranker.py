"""
PriorityRanker: ranks failure clusters by impact (frequency x severity x scope).
"""

from __future__ import annotations

from typing import List

from .models import FailureCluster, Severity

_SEVERITY_WEIGHT = {
    Severity.LOW: 1.0,
    Severity.MEDIUM: 2.0,
    Severity.HIGH: 3.0,
    Severity.CRITICAL: 5.0,
}


class PriorityRanker:
    """Rank clusters by composite impact score."""

    def rank(self, clusters: List[FailureCluster], total_tests: int) -> List[str]:
        """Return cluster IDs sorted by descending impact."""
        scored = [
            (c.cluster_id, self._score(c, total_tests))
            for c in clusters
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [cid for cid, _ in scored]

    @staticmethod
    def _score(cluster: FailureCluster, total_tests: int) -> float:
        frequency = cluster.failure_count / max(total_tests, 1)
        severity = _SEVERITY_WEIGHT.get(cluster.severity, 2.0)
        scope = len(cluster.affected_scenarios) * 0.5 + len(cluster.affected_tools) * 0.5
        scope = max(scope, 1.0)
        return frequency * severity * scope
