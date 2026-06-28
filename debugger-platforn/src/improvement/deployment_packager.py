"""
DeploymentPackageBuilder: bundles the fixed agent, regression tests,
improvement report, and deployment/rollback docs into a single directory.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from .models import DeploymentPackage


class DeploymentPackageBuilder:
    """Build a self-contained deployment directory."""

    def __init__(self, agent_source_dir: Path):
        self.agent_source_dir = agent_source_dir

    def build(
        self,
        improvement_report: Dict[str, Any],
        applied_fixes: List[Dict[str, Any]],
        regression_tests: List[Dict[str, Any]],
        output_dir: Path,
    ) -> DeploymentPackage:
        output_dir.mkdir(parents=True, exist_ok=True)

        # 1. Copy agent files
        agent_dir = output_dir / "agent"
        agent_dir.mkdir(exist_ok=True)
        fixed_files = self._copy_agent(agent_dir)

        # 2. Regression tests
        tests_dir = output_dir / "regression_tests"
        tests_dir.mkdir(exist_ok=True)
        (tests_dir / "regression_suite.json").write_text(
            json.dumps(regression_tests, indent=2, default=str)
        )

        # 3. Changelog
        changelog = self._changelog(applied_fixes, improvement_report)
        (output_dir / "CHANGELOG.md").write_text(changelog)

        # 4. Deployment instructions
        deploy_instructions = self._deployment_instructions(improvement_report)
        (output_dir / "DEPLOYMENT.md").write_text(deploy_instructions)

        # 5. Rollback
        (output_dir / "ROLLBACK.md").write_text(
            improvement_report.get("rollback_plan", "No rollback plan available.")
        )

        # 6. Improvement report
        (output_dir / "improvement_report.json").write_text(
            json.dumps(improvement_report, indent=2, default=str)
        )

        version = f"v1.0.{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}"

        package = DeploymentPackage(
            package_id=f"deploy_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
            created_at=datetime.now(timezone.utc),
            version=version,
            fixed_agent_files=fixed_files,
            applied_fixes=applied_fixes,
            regression_tests=regression_tests,
            all_tests_passed=improvement_report.get("ready_to_deploy", False),
            improvement_validated=improvement_report.get("improvement_significant", False),
            changelog=changelog,
            deployment_instructions=deploy_instructions,
            rollback_instructions=improvement_report.get("rollback_plan", ""),
            expected_improvement=improvement_report.get("pass_rate_improvement", 0.0),
            expected_risk=improvement_report.get("deployment_risk", "unknown"),
        )

        (output_dir / "package.json").write_text(
            json.dumps(package.model_dump(mode="json"), indent=2, default=str)
        )

        return package

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _copy_agent(self, target_dir: Path) -> List[str]:
        copied: List[str] = []
        exclude = {".git", "__pycache__", ".env", "node_modules", ".pytest_cache",
                   "improvement", "results", "deployment"}

        if not self.agent_source_dir.exists():
            return copied

        # Resolve to avoid copying output into itself
        target_resolved = target_dir.resolve()

        for item in self.agent_source_dir.rglob("*"):
            if not item.is_file():
                continue
            # Skip excluded dirs
            if any(p in item.parts for p in exclude):
                continue
            # Skip if inside the target dir (avoid recursion)
            try:
                item.resolve().relative_to(target_resolved)
                continue
            except ValueError:
                pass
            rel = item.relative_to(self.agent_source_dir)
            dest = target_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)
            copied.append(str(rel))

        return copied

    @staticmethod
    def _changelog(
        applied_fixes: List[Dict],
        report: Dict,
    ) -> str:
        lines = [
            f"# Changelog - {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
            "",
            "## Improvements",
            f"- Pass rate improved by {report.get('pass_rate_improvement', 0):.1f} pp",
            f"- Baseline: {report.get('baseline_pass_rate', 0) * 100:.1f}%",
            f"- Fixed: {report.get('fixed_pass_rate', 0) * 100:.1f}%",
            "",
            "## Fixes Applied",
            "",
        ]
        for fix in applied_fixes:
            if fix.get("status") in ("applied", "pending"):
                lines.append(f"### {fix.get('description', 'Fix')}")
                lines.append(f"- Type: {fix.get('fix_type')}")
                lines.append(f"- Cluster: {fix.get('cluster_id', 'N/A')[:8]}")
                lines.append(f"- Applied to: {fix.get('applied_to')}")
                lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _deployment_instructions(report: Dict) -> str:
        improvement = report.get("pass_rate_improvement", 0)
        risk = report.get("deployment_risk", "unknown")
        fixes_count = report.get("successful_fixes", 0)

        return f"""# Deployment Instructions

## Overview
This package contains a fixed agent with {improvement:.1f} pp improvement in pass rate.

## Pre-Deployment Checklist
- [ ] Review improvement report
- [ ] Verify all regression tests pass
- [ ] Backup current production agent
- [ ] Prepare rollback plan (see ROLLBACK.md)

## Deployment Steps

1. Backup current agent
2. Copy fixed agent files from `agent/` to production
3. Run regression tests from `regression_tests/`
4. Monitor error rates for 1 hour
5. Review metrics

## Metrics
- Expected improvement: {improvement:.1f} pp
- Risk level: {risk}
- Fixes applied: {fixes_count}

## Rollback
If issues occur, see ROLLBACK.md
"""
