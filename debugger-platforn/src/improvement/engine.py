"""
ImprovementEngine: orchestrates Phase E — fix application, A/B testing,
validation, regression-test generation, and deployment packaging.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .ab_testing import ABTestingFramework
from .deployment_packager import DeploymentPackageBuilder
from .fix_applicator import FixApplicationEngine
from .models import (
    ABTestRun,
    AppliedFix,
    DeploymentPackage,
    ImprovementReport,
    RegressionTest,
)
from .regression_generator import RegressionTestGenerator
from .validator import ImprovementValidator


class ImprovementEngine:
    """Main orchestrator for Phase E."""

    def __init__(
        self,
        agent_map: Dict[str, Any],
        agent_source_dir: Path,
        test_suite: Dict[str, Any],
        diagnosis_report: Dict[str, Any],
        *,
        dry_run: bool = True,
        baseline_fail_rate: float = 0.05,
        fixed_fail_rate: float = 0.01,
        smoke_limit: int = 10,
        full_limit: int = 50,
        max_workers: int = 10,
        language: str = "English",
        on_progress: Optional[Callable[[str], None]] = None,
    ):
        self.agent_map = agent_map
        self.agent_source_dir = agent_source_dir
        self.test_suite = test_suite
        self.diagnosis_report = diagnosis_report
        self.dry_run = dry_run
        self.baseline_fail_rate = baseline_fail_rate
        self.fixed_fail_rate = fixed_fail_rate
        self.smoke_limit = smoke_limit
        self.full_limit = full_limit
        self.max_workers = max_workers
        self.language = language
        self._progress = on_progress or (lambda msg: None)

        # Sub-components
        self._applicator = FixApplicationEngine(agent_map, agent_source_dir)
        self._ab = ABTestingFramework(
            test_suite=test_suite,
            agent_map=agent_map,
            baseline_fail_rate=baseline_fail_rate,
            fixed_fail_rate=fixed_fail_rate,
            max_workers=max_workers,
            language=language,
        )
        self._regression_gen = RegressionTestGenerator()
        self._validator = ImprovementValidator()
        self._packager = DeploymentPackageBuilder(agent_source_dir)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(self, output_dir: Path) -> Dict[str, Any]:
        """Run the full Phase E pipeline (sync wrapper around async)."""
        return asyncio.run(self.run_async(output_dir))

    async def run_async(self, output_dir: Path) -> Dict[str, Any]:
        """Run the full Phase E pipeline."""
        output_dir.mkdir(parents=True, exist_ok=True)

        # ------ Step 1: Apply fixes ------
        self._progress("Step 1: Applying fixes...")
        proposed_fixes = self.diagnosis_report.get("fix_proposals", [])
        applied = self._applicator.apply_fixes(proposed_fixes, dry_run=self.dry_run)
        applied_dicts = [a.model_dump(mode="json") for a in applied]
        successful = [a for a in applied if a.status.value in ("applied", "pending")]
        self._progress(
            f"  Applied {len(successful)}/{len(proposed_fixes)} fixes"
            + (" (dry run)" if self.dry_run else "")
        )

        # ------ Step 2: A/B testing ------
        self._progress("Step 2: Running A/B tests...")
        ab_runs: List[ABTestRun] = []

        self._progress("  Running smoke test...")
        smoke = await self._ab.run_smoke_test(limit=self.smoke_limit)
        ab_runs.append(smoke)
        self._progress(
            f"  Smoke: baseline {smoke.baseline_results['pass_rate']:.0%} → "
            f"fixed {smoke.fixed_results['pass_rate']:.0%} "
            f"(p={smoke.statistical_significance.get('pass_rate_p_value', 1.0):.3f})"
        )

        if smoke.recommendation not in ("rollback",):
            self._progress("  Running full test...")
            full = await self._ab.run_full_test(limit=self.full_limit)
            ab_runs.append(full)
            self._progress(
                f"  Full:  baseline {full.baseline_results['pass_rate']:.0%} → "
                f"fixed {full.fixed_results['pass_rate']:.0%} "
                f"(p={full.statistical_significance.get('pass_rate_p_value', 1.0):.3f})"
            )
        else:
            self._progress("  Skipping full test (smoke test recommended rollback)")

        # ------ Step 3: Regression tests ------
        self._progress("Step 3: Generating regression tests...")
        regression_tests = self._regression_gen.generate(
            self.diagnosis_report,
            applied_dicts,
        )
        regression_dicts = [t.model_dump(mode="json") for t in regression_tests]
        self._progress(f"  Generated {len(regression_tests)} regression tests")

        # ------ Step 4: Validate improvement ------
        self._progress("Step 4: Validating improvement...")
        improvement_report = self._validator.validate(ab_runs, applied_dicts)
        improvement_dict = improvement_report.model_dump(mode="json")
        self._progress(
            f"  Improvement: {improvement_report.pass_rate_improvement:+.1f} pp  "
            f"Ready: {improvement_report.ready_to_deploy}  "
            f"Risk: {improvement_report.deployment_risk}"
        )

        # ------ Step 5: Deployment package ------
        package: Optional[DeploymentPackage] = None
        if improvement_report.ready_to_deploy:
            self._progress("Step 5: Building deployment package...")
            package = self._packager.build(
                improvement_dict,
                applied_dicts,
                regression_dicts,
                output_dir / "deployment",
            )
            self._progress(f"  Package: {package.version} → {output_dir / 'deployment'}")
        else:
            self._progress("Step 5: Skipped (not ready to deploy)")

        # ------ Save artefacts ------
        self._progress("Saving artefacts...")
        import json

        def _save(name: str, data: Any) -> None:
            (output_dir / name).write_text(
                json.dumps(data, indent=2, default=str)
            )

        _save("applied_fixes.json", applied_dicts)
        _save("ab_test_results.json", [r.model_dump(mode="json") for r in ab_runs])
        _save("improvement_report.json", improvement_dict)
        _save("regression_tests.json", regression_dicts)

        self._progress("Phase E complete")

        return {
            "applied_fixes": applied_dicts,
            "ab_test_runs": [r.model_dump(mode="json") for r in ab_runs],
            "improvement_report": improvement_dict,
            "regression_tests": regression_dicts,
            "deployment_package": package.model_dump(mode="json") if package else None,
        }
