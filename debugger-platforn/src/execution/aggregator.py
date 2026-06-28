"""
ResultsAggregator: generates the final test-run report and failure inbox
from collected TestResult objects.  Includes optional post-execution
validation to filter fake failures and catch fake successes.
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .models import TestResult, TestRunReport


class ResultsAggregator:
    """Aggregate test results into a report + failure inbox."""

    def __init__(self, test_suite: Dict[str, Any], results: List[TestResult]):
        self.test_suite = test_suite
        self.results = results

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------

    def generate_report(self, started_at: datetime) -> TestRunReport:
        total = len(self.results)
        passed = sum(1 for r in self.results if r.status.value == "passed")
        failed = sum(1 for r in self.results if r.status.value == "failed")
        errors = sum(1 for r in self.results if r.status.value == "error")
        timeouts = sum(1 for r in self.results if r.status.value == "timeout")

        durations = [r.duration_sec for r in self.results]
        total_duration = sum(durations)
        avg_duration = total_duration / total if total else 0.0

        total_cost = sum(r.cost_usd for r in self.results)

        # Tool coverage
        tool_counts: Dict[str, int] = defaultdict(int)
        for r in self.results:
            for turn in r.turns:
                for tc in turn.tool_calls:
                    tool_counts[tc.get("tool_name", "unknown")] += 1

        expected_tools: List[str] = list(
            self.test_suite
            .get("summary", {})
            .get("tool_invocation_counts", {})
            .keys()
        )
        tools_not_covered = [t for t in expected_tools if t not in tool_counts]
        coverage_pct = (
            ((len(expected_tools) - len(tools_not_covered)) / len(expected_tools) * 100)
            if expected_tools else 0.0
        )

        # Breakdown by difficulty
        by_difficulty: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for r in self.results:
            by_difficulty[r.difficulty][r.status.value] += 1

        # Breakdown by coverage goal
        by_coverage: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for r in self.results:
            by_coverage[r.coverage_goal][r.status.value] += 1

        return TestRunReport(
            run_id=str(uuid.uuid4()),
            test_suite_id=self.test_suite.get("test_suite_id", "unknown"),
            total_tests=total,
            passed=passed,
            failed=failed,
            errors=errors,
            timeouts=timeouts,
            pass_rate=(passed / total * 100) if total else 0.0,
            total_duration_sec=total_duration,
            avg_duration_sec=avg_duration,
            total_cost_usd=total_cost,
            tool_coverage=dict(tool_counts),
            tools_not_covered=tools_not_covered,
            coverage_pct=coverage_pct,
            by_difficulty={k: dict(v) for k, v in by_difficulty.items()},
            by_coverage_goal={k: dict(v) for k, v in by_coverage.items()},
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------------
    # Failure inbox (for Phase D)
    # ------------------------------------------------------------------

    def generate_failure_inbox(self) -> Dict[str, Any]:
        failures = [
            r for r in self.results
            if r.status.value in ("failed", "error", "timeout")
        ]

        return {
            "total_failures": len(failures),
            "by_status": {
                "failed": sum(1 for f in failures if f.status.value == "failed"),
                "error": sum(1 for f in failures if f.status.value == "error"),
                "timeout": sum(1 for f in failures if f.status.value == "timeout"),
            },
            "failures": [
                {
                    "test_id": f.test_id,
                    "test_number": f.test_number,
                    "scenario": f.scenario_title,
                    "persona": f.persona_name,
                    "difficulty": f.difficulty,
                    "coverage_goal": f.coverage_goal,
                    "status": f.status.value,
                    "failure_reason": f.failure_reason,
                    "total_turns": f.total_turns,
                    "duration_sec": f.duration_sec,
                    "cost_usd": f.cost_usd,
                    "outcome": f.outcome,
                    "tools_called_sequence": f.tools_called_sequence,
                    "tool_results": f.tool_results,
                    "chaos_events": [e.model_dump() for e in f.chaos_events],
                    "trace_file": f.trace_file,
                }
                for f in failures
            ],
        }

    # ------------------------------------------------------------------
    # Passed inbox (for validation step)
    # ------------------------------------------------------------------

    def generate_passed_inbox(self) -> Dict[str, Any]:
        """Return passed tests with enough data for false-success detection."""
        passed = [r for r in self.results if r.status.value == "passed"]
        return {
            "total_passed": len(passed),
            "results": [
                {
                    "test_id": r.test_id,
                    "test_number": r.test_number,
                    "scenario": r.scenario_title,
                    "persona": r.persona_name,
                    "difficulty": r.difficulty,
                    "coverage_goal": r.coverage_goal,
                    "total_turns": r.total_turns,
                    "tools_called_sequence": r.tools_called_sequence,
                    "tool_results": r.tool_results,
                    "outcome": r.outcome,
                    "trace_file": r.trace_file,
                }
                for r in passed
            ],
        }

    # ------------------------------------------------------------------
    # Save helpers
    # ------------------------------------------------------------------

    def save_report(self, filepath: str | Path, started_at: datetime) -> TestRunReport:
        report = self.generate_report(started_at)
        with open(filepath, "w") as f:
            json.dump(report.model_dump(), f, indent=2, default=str)
        return report

    def save_failure_inbox(self, filepath: str | Path) -> Dict:
        inbox = self.generate_failure_inbox()
        with open(filepath, "w") as f:
            json.dump(inbox, f, indent=2, default=str)
        return inbox

    def save_passed_inbox(self, filepath: str | Path) -> Dict:
        passed_inbox = self.generate_passed_inbox()
        with open(filepath, "w") as f:
            json.dump(passed_inbox, f, indent=2, default=str)
        return passed_inbox

    # ------------------------------------------------------------------
    # Validation (filter fake failures, catch fake successes)
    # ------------------------------------------------------------------

    def validate_and_save(
        self,
        results_dir: str | Path,
        agent_map: Dict[str, Any],
        use_ai: bool = True,
        retry_config: Optional[Dict] = None,
        on_progress: Optional[Callable[[str], None]] = None,
        event_queue: Optional[Any] = None,
    ) -> tuple[Dict, Dict, "ValidationResult"]:
        """Run validation on failure inbox + passed results, save all artifacts.

        Returns (validated_inbox, validation_report_dict, validation_result).
        """
        from src.validation.conversation_validator import ConversationValidator, ValidationResult

        results_dir = Path(results_dir)

        # Generate raw inboxes
        failure_inbox = self.generate_failure_inbox()
        passed_inbox = self.generate_passed_inbox()

        # Save raw inboxes
        with open(results_dir / "failure_inbox.json", "w") as f:
            json.dump(failure_inbox, f, indent=2, default=str)
        with open(results_dir / "passed_inbox.json", "w") as f:
            json.dump(passed_inbox, f, indent=2, default=str)

        # Validate
        validator = ConversationValidator(use_ai=use_ai, retry_config=retry_config)
        validation = validator.validate_results(
            failure_inbox=failure_inbox,
            passed_results=passed_inbox.get("results", []),
            agent_map=agent_map,
            on_progress=on_progress,
        )

        # Build validated inbox
        validated_failures = validation.genuine_failures + validation.false_successes
        validated_inbox = {
            "total_failures": len(validated_failures),
            "by_status": {
                "failed": sum(1 for f in validated_failures if f.get("status") == "failed"),
                "error": sum(1 for f in validated_failures if f.get("status") == "error"),
                "timeout": sum(1 for f in validated_failures if f.get("status") == "timeout"),
            },
            "failures": validated_failures,
        }

        # Save validated inbox
        with open(results_dir / "validated_failure_inbox.json", "w") as f:
            json.dump(validated_inbox, f, indent=2, default=str)

        # Save validation report
        validation_report = {
            "summary": validation.summary,
            "persona_failures": validation.persona_failures,
            "chaos_failures": validation.chaos_failures,
            "false_successes": validation.false_successes,
        }
        with open(results_dir / "validation_report.json", "w") as f:
            json.dump(validation_report, f, indent=2, default=str)

        # Push validation event to UI if event queue is available
        if event_queue is not None:
            try:
                event_queue.put_nowait({
                    "type": "validation_completed",
                    "summary": validation.summary,
                })
            except Exception:
                pass

        return validated_inbox, validation_report, validation
