"""Certification engine — pipeline integration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .certifier import Certifier
from .models import CertificationReport


class CertificationEngine:
    """Runs certification scoring and saves the report."""

    def __init__(self, on_progress: Optional[Callable[[str], None]] = None):
        self._on_progress = on_progress or (lambda _: None)

    def run(
        self,
        results_dir: Path,
        test_run_report: Dict[str, Any],
        diagnosis_report: Optional[Dict[str, Any]],
        agent_map: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Run certification and save report.

        Returns the certification report as a dict.
        """
        self._on_progress("Step 1: Loading data...")

        certifier = Certifier()

        self._on_progress("Step 2: Scoring categories...")
        report = certifier.certify(test_run_report, diagnosis_report, agent_map)

        self._on_progress("Step 3: Saving certification report...")
        report_dict = report.model_dump(mode="json")

        results_dir = Path(results_dir)
        results_dir.mkdir(parents=True, exist_ok=True)
        report_path = results_dir / "certification_report.json"
        with open(report_path, "w") as f:
            json.dump(report_dict, f, indent=2, default=str)

        self._on_progress("Certification complete")
        return report_dict
