#!/usr/bin/env python3
"""
AI Validation Script
~~~~~~~~~~~~~~~~~~~~

Loads existing Phase C outputs and the offline diagnosis report,
runs a full AI-powered diagnosis, saves the result, and prints
a comparison table (offline vs AI).

Usage:
    python run_ai_validation.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.diagnosis.engine import DiagnosisEngine

console = Console()

# Paths
RESULTS_DIR = Path("results")
INBOX_PATH = RESULTS_DIR / "failure_inbox.json"
REPORT_PATH = RESULTS_DIR / "test_run_report.json"
AGENT_MAP_PATH = Path("agent_map.json")
OFFLINE_DIAG_PATH = RESULTS_DIR / "diagnosis_report.json"
AI_DIAG_PATH = RESULTS_DIR / "diagnosis_report_ai.json"


def _load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def _print_comparison(offline: dict, ai: dict):
    """Print side-by-side comparison of offline vs AI diagnosis."""
    table = Table(title="Offline vs AI Diagnosis Comparison", show_lines=True)
    table.add_column("Metric", style="cyan", min_width=25)
    table.add_column("Offline", min_width=25)
    table.add_column("AI", min_width=25)
    table.add_column("Delta", min_width=15)

    # Clusters count
    off_clusters = offline.get("clusters_found", 0)
    ai_clusters = ai.get("clusters_found", 0)
    delta = ai_clusters - off_clusters
    table.add_row("Clusters found", str(off_clusters), str(ai_clusters), f"{delta:+d}" if delta else "same")

    # Fix proposals count
    off_fixes = len(offline.get("fix_proposals", []))
    ai_fixes = len(ai.get("fix_proposals", []))
    delta = ai_fixes - off_fixes
    table.add_row("Fix proposals", str(off_fixes), str(ai_fixes), f"{delta:+d}" if delta else "same")

    # Root cause distribution
    off_rc = offline.get("summary", {}).get("by_root_cause", {})
    ai_rc = ai.get("summary", {}).get("by_root_cause", {})
    all_rc = sorted(set(list(off_rc.keys()) + list(ai_rc.keys())))
    for rc in all_rc:
        ov = off_rc.get(rc, 0)
        av = ai_rc.get(rc, 0)
        d = av - ov
        table.add_row(
            f"  root_cause: {rc}",
            str(ov),
            str(av),
            f"{d:+d}" if d else "same",
        )

    # Severity distribution
    off_sev = offline.get("summary", {}).get("by_severity", {})
    ai_sev = ai.get("summary", {}).get("by_severity", {})
    all_sev = sorted(set(list(off_sev.keys()) + list(ai_sev.keys())))
    for sev in all_sev:
        ov = off_sev.get(sev, 0)
        av = ai_sev.get(sev, 0)
        d = av - ov
        table.add_row(
            f"  severity: {sev}",
            str(ov),
            str(av),
            f"{d:+d}" if d else "same",
        )

    # Fix type distribution
    off_ft = offline.get("summary", {}).get("fix_proposals_by_type", {})
    ai_ft = ai.get("summary", {}).get("fix_proposals_by_type", {})
    all_ft = sorted(set(list(off_ft.keys()) + list(ai_ft.keys())))
    for ft in all_ft:
        ov = off_ft.get(ft, 0)
        av = ai_ft.get(ft, 0)
        d = av - ov
        table.add_row(
            f"  fix_type: {ft}",
            str(ov),
            str(av),
            f"{d:+d}" if d else "same",
        )

    console.print(table)

    # Cluster-level comparison
    console.print("\n[bold]Cluster Root Causes:[/bold]")
    off_clusters_list = offline.get("clusters", [])
    ai_clusters_list = ai.get("clusters", [])
    max_len = max(len(off_clusters_list), len(ai_clusters_list))
    for i in range(max_len):
        off_name = off_clusters_list[i]["root_cause_type"] if i < len(off_clusters_list) else "-"
        ai_name = ai_clusters_list[i]["root_cause_type"] if i < len(ai_clusters_list) else "-"
        marker = " [green]=[/green]" if off_name == ai_name else " [red]!=[/red]"
        console.print(f"  Cluster {i + 1}: [dim]{off_name}[/dim] vs [cyan]{ai_name}[/cyan]{marker}")


def main():
    console.print(Panel(
        "[bold]AI Validation: Offline vs AI Diagnosis[/bold]",
        style="blue",
    ))

    # Check required files
    for path in [INBOX_PATH, REPORT_PATH, AGENT_MAP_PATH]:
        if not path.exists():
            console.print(f"[red]Missing required file: {path}[/red]")
            console.print("Run Phase C first: python execute_tests.py test_suite.json agent_map.json --mock")
            sys.exit(1)

    # Load inputs
    inbox = _load_json(INBOX_PATH)
    test_report = _load_json(REPORT_PATH)
    agent_map = _load_json(AGENT_MAP_PATH)

    total_failures = inbox.get("total_failures", 0)
    if total_failures == 0:
        console.print("[green]No failures to diagnose.[/green]")
        return

    console.print(f"  Failures: [bold]{total_failures}[/bold]")
    console.print(f"  Mode:     [bold]AI-powered[/bold] (max_retries=5, backoff_base=4.0)")
    console.print()

    # Run AI diagnosis
    def on_progress(msg: str):
        console.print(f"  [dim]{msg}[/dim]")

    engine = DiagnosisEngine(
        use_ai=True,
        max_retries=5,
        backoff_base=4.0,
        on_progress=on_progress,
    )

    ai_report = engine.diagnose(inbox, test_report, agent_map)

    # Save AI report
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ai_dict = ai_report.model_dump(mode="json")
    with open(AI_DIAG_PATH, "w") as f:
        json.dump(ai_dict, f, indent=2, default=str)

    console.print(f"\n[bold green]AI diagnosis report saved to {AI_DIAG_PATH}[/bold green]")

    # Compare with offline report
    if OFFLINE_DIAG_PATH.exists():
        offline_dict = _load_json(OFFLINE_DIAG_PATH)
        console.print()
        _print_comparison(offline_dict, ai_dict)
    else:
        console.print(f"\n[yellow]No offline report at {OFFLINE_DIAG_PATH} — skipping comparison.[/yellow]")
        console.print("Run offline first: python diagnose_failures.py results/failure_inbox.json results/test_run_report.json agent_map.json --skip-ai")


if __name__ == "__main__":
    main()
