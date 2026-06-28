"""
DiagnosisEngine: orchestrates clustering, root-cause analysis,
minimal reproduction, fix generation, and priority ranking.
"""

from __future__ import annotations

import json
import os
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .clustering import FailureClusterer
from .fix_generator import FixProposalGenerator
from .minimal_reproducer import MinimalReproducer
from .models import (
    DiagnosisReport,
    FailureCluster,
    FailureExample,
    FixProposal,
    RootCauseType,
    Severity,
)
from .priority_ranker import PriorityRanker
from .retry import RetryConfig
from .root_cause_analyzer import RootCauseAnalyzer

# Map root-cause type → severity if frequency is low
_BASE_SEVERITY: Dict[str, Severity] = {
    "hallucination": Severity.CRITICAL,
    "missing_guardrail": Severity.CRITICAL,
    "tool_selection_error": Severity.HIGH,
    "state_management": Severity.HIGH,
    "service_unavailable": Severity.HIGH,
    "error_handling": Severity.MEDIUM,
    "timeout_handling": Severity.MEDIUM,
    "retry_logic_bug": Severity.MEDIUM,
    "prompt_issue": Severity.MEDIUM,
    "edge_case_unhandled": Severity.MEDIUM,
    "validation_missing": Severity.MEDIUM,
    "tool_schema_mismatch": Severity.LOW,
}


def _load_trace(trace_file: str) -> Optional[Dict]:
    if not trace_file or not os.path.exists(trace_file):
        return None
    with open(trace_file) as f:
        return json.load(f)


class DiagnosisEngine:
    """Main orchestrator for Phase D failure analysis."""

    def __init__(
        self,
        use_ai: bool = True,
        use_embeddings: bool = False,
        on_progress=None,
        max_retries: int = 3,
        backoff_base: float = 2.0,
        backoff_max: float = 60.0,
        ai_workers: int = 1,
    ):
        retry_cfg = RetryConfig(
            max_retries=max_retries,
            backoff_base=backoff_base,
            backoff_max=backoff_max,
        )
        self.clusterer = FailureClusterer(use_embeddings=use_embeddings)
        self.root_cause_analyzer = RootCauseAnalyzer(use_ai=use_ai, retry_config=retry_cfg)
        self.reproducer = MinimalReproducer(use_ai=use_ai, retry_config=retry_cfg)
        self.fix_generator = FixProposalGenerator(use_ai=use_ai, retry_config=retry_cfg)
        self.ranker = PriorityRanker()
        self._progress = on_progress or (lambda msg: None)
        self._ai_workers = ai_workers  # reserved for future parallel AI calls

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def diagnose(
        self,
        failure_inbox: Dict[str, Any],
        test_run_report: Dict[str, Any],
        agent_map: Dict[str, Any],
    ) -> DiagnosisReport:
        failures = failure_inbox.get("failures", [])
        total_tests = test_run_report.get("total_tests", 0) or len(
            test_run_report.get("test_cases", [])
        )

        self._progress(f"Analyzing {len(failures)} failures...")

        # Step 1: Cluster
        self._progress("Step 1: Clustering failures...")
        groups = self.clusterer.cluster_failures(failures)
        self._progress(f"  Found {len(groups)} clusters")

        # Step 2: Analyze each cluster
        self._progress("Step 2: Analyzing root causes...")
        clusters: List[FailureCluster] = []
        for i, group in enumerate(groups, 1):
            self._progress(f"  Cluster {i}/{len(groups)} ({len(group)} failures)...")

            examples = self._build_examples(group)
            root_type, description, pattern, indicators = (
                self.root_cause_analyzer.analyze_cluster(group)
            )
            severity = self._determine_severity(root_type, len(group), total_tests)
            affected_scenarios = list({f.get("scenario", "") for f in group})
            affected_tools = self._extract_tools(group)

            cluster = FailureCluster(
                cluster_id=str(uuid.uuid4()),
                cluster_name=f"Cluster {i}: {root_type}",
                failure_count=len(group),
                failure_examples=examples,
                root_cause_type=RootCauseType(root_type),
                root_cause_description=description,
                common_pattern=pattern,
                key_indicators=indicators,
                severity=severity,
                affected_scenarios=affected_scenarios,
                affected_tools=affected_tools,
                created_at=datetime.now(timezone.utc),
            )
            clusters.append(cluster)

        # Step 3: Minimal reproductions
        self._progress("Step 3: Generating minimal reproductions...")
        for cluster in clusters:
            self._progress(f"  {cluster.cluster_name}...")
            cluster.minimal_reproduction = self.reproducer.generate(cluster)

        # Step 4: Fix proposals
        self._progress("Step 4: Generating fix proposals...")
        all_fixes: List[FixProposal] = []
        for cluster in clusters:
            self._progress(f"  {cluster.cluster_name}...")
            raw_fixes = self.fix_generator.generate(cluster, agent_map)
            for fix_data in raw_fixes:
                fix = FixProposal(
                    fix_id=str(uuid.uuid4()),
                    cluster_id=cluster.cluster_id,
                    created_at=datetime.now(timezone.utc),
                    **fix_data,
                )
                all_fixes.append(fix)

        # Step 5: Priority ranking
        self._progress("Step 5: Ranking by priority...")
        ranking = self.ranker.rank(clusters, total_tests)

        # Build report
        report = DiagnosisReport(
            report_id=str(uuid.uuid4()),
            run_id=test_run_report.get("run_id", "unknown"),
            total_failures=len(failures),
            clusters_found=len(clusters),
            clusters=clusters,
            fix_proposals=all_fixes,
            priority_ranking=ranking,
            summary=self._build_summary(clusters, all_fixes, total_tests),
            generated_at=datetime.now(timezone.utc),
        )

        self._progress("Diagnosis complete")
        return report

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_examples(group: List[Dict]) -> List[FailureExample]:
        examples = []
        for f in group:
            trace = _load_trace(f.get("trace_file", ""))
            tools_called: List[str] = []
            if trace:
                for turn in trace.get("turns", []):
                    for tc in turn.get("tool_calls", []):
                        tools_called.append(tc.get("tool_name", ""))

            examples.append(FailureExample(
                test_id=f.get("test_id", ""),
                test_number=f.get("test_number", 0),
                scenario=f.get("scenario", ""),
                persona=f.get("persona", ""),
                failure_reason=f.get("failure_reason", ""),
                trace_file=f.get("trace_file", ""),
                difficulty=f.get("difficulty", "medium"),
                coverage_goal=f.get("coverage_goal", ""),
                tools_called=tools_called,
                turn_count=f.get("total_turns", 0),
                duration_sec=f.get("duration_sec", 0),
                chaos_events=f.get("chaos_events", []),
            ))
        return examples

    @staticmethod
    def _extract_tools(group: List[Dict]) -> List[str]:
        tools: set = set()
        for f in group:
            trace = _load_trace(f.get("trace_file", ""))
            if trace:
                for turn in trace.get("turns", []):
                    for tc in turn.get("tool_calls", []):
                        name = tc.get("tool_name", "")
                        if name:
                            tools.add(name)
        return sorted(tools)

    @staticmethod
    def _determine_severity(root_type: str, count: int, total: int) -> Severity:
        base = _BASE_SEVERITY.get(root_type, Severity.MEDIUM)
        # Boost if cluster is large relative to total
        if total > 0 and count / total > 0.15:
            if base == Severity.LOW:
                return Severity.MEDIUM
            if base == Severity.MEDIUM:
                return Severity.HIGH
        return base

    @staticmethod
    def _build_summary(
        clusters: List[FailureCluster],
        fixes: List[FixProposal],
        total_tests: int,
    ) -> Dict[str, Any]:
        by_root_cause: Dict[str, int] = defaultdict(int)
        by_severity: Dict[str, int] = defaultdict(int)
        for c in clusters:
            by_root_cause[c.root_cause_type.value] += 1
            by_severity[c.severity.value] += 1

        by_fix_type: Dict[str, int] = defaultdict(int)
        for f in fixes:
            by_fix_type[f.fix_type] += 1

        total_failures = sum(c.failure_count for c in clusters)
        unique_bugs = len(clusters)

        # Bug Discovery Rate: unique bugs found per test executed (%)
        bug_discovery_rate = round(
            unique_bugs / max(total_tests, 1) * 100, 1
        )

        # Redundancy Rate: % of failures that are duplicates of already-found bugs
        redundancy_rate = round(
            (total_failures - unique_bugs) / max(total_failures, 1) * 100, 1
        ) if total_failures > 0 else 0.0

        # Severity-Weighted Score: average severity weight per failure
        severity_weights = {"critical": 5, "high": 3, "medium": 2, "low": 1}
        severity_weighted_score = round(
            sum(
                severity_weights.get(c.severity.value, 2) * c.failure_count
                for c in clusters
            ) / max(total_failures, 1),
            2,
        )

        return {
            "total_failures_analyzed": total_failures,
            "total_tests": total_tests,
            "failure_rate": round(total_failures / max(total_tests, 1) * 100, 1),
            "by_root_cause": dict(by_root_cause),
            "by_severity": dict(by_severity),
            "fix_proposals_by_type": dict(by_fix_type),
            "clusters_count": len(clusters),
            "fixes_count": len(fixes),
            "unique_bugs_count": unique_bugs,
            "bug_discovery_rate": bug_discovery_rate,
            "redundancy_rate": redundancy_rate,
            "severity_weighted_score": severity_weighted_score,
        }
