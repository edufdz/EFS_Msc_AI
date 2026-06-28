#!/usr/bin/env python3
"""
Improvement CLI (Phase E)
~~~~~~~~~~~~~~~~~~~~~~~~~

Apply fixes from Phase D, run A/B tests, validate improvements,
generate regression tests, and build deployment packages.

Usage:
    # Dry run (no files modified)
    python improve_agent.py results/diagnosis_report.json agent_map.json test_suite.json

    # Apply fixes for real
    python improve_agent.py results/diagnosis_report.json agent_map.json test_suite.json --apply

    # Custom output dir + tuning
    python improve_agent.py results/diagnosis_report.json agent_map.json test_suite.json \\
        --apply --output improvement/ --smoke-limit 20 --full-limit 100
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.improvement.engine import ImprovementEngine

console = Console()


def _severity_style(risk: str) -> str:
    return {"low": "green", "medium": "yellow", "high": "red"}.get(risk, "white")


def _print_applied_fixes(applied: list):
    table = Table(title="Applied Fixes", show_lines=True)
    table.add_column("#", justify="center", width=3)
    table.add_column("Type", style="cyan", width=16)
    table.add_column("Status", width=10)
    table.add_column("Applied To", min_width=30)

    for i, fix in enumerate(applied, 1):
        status = fix.get("status", "unknown")
        sty = {"applied": "green", "pending": "yellow", "failed": "red", "skipped": "dim"}.get(status, "white")
        table.add_row(
            str(i),
            fix.get("fix_type", "?"),
            f"[{sty}]{status}[/{sty}]",
            str(fix.get("applied_to", ""))[:50],
        )
    console.print(table)


def _print_ab_results(ab_runs: list):
    table = Table(title="A/B Test Results", show_lines=True)
    table.add_column("Suite", style="cyan", width=8)
    table.add_column("Baseline", justify="center", width=10)
    table.add_column("Fixed", justify="center", width=10)
    table.add_column("Delta", justify="center", width=10)
    table.add_column("p-value", justify="center", width=10)
    table.add_column("Recommendation", min_width=20)

    for run in ab_runs:
        b_rate = run.get("baseline_results", {}).get("pass_rate", 0)
        f_rate = run.get("fixed_results", {}).get("pass_rate", 0)
        delta = run.get("improvement", {}).get("pass_rate_delta", 0)
        p_val = run.get("statistical_significance", {}).get("pass_rate_p_value", 1.0)
        rec = run.get("recommendation", "?")

        delta_style = "green" if delta > 0 else "red" if delta < 0 else "white"
        p_style = "green" if p_val < 0.05 else "yellow"
        rec_style = "green" if "deploy" in rec else "red" if "rollback" in rec else "yellow"

        table.add_row(
            run.get("test_suite_used", "?"),
            f"{b_rate:.0%}",
            f"{f_rate:.0%}",
            f"[{delta_style}]{delta:+.1%}[/{delta_style}]",
            f"[{p_style}]{p_val:.4f}[/{p_style}]",
            f"[{rec_style}]{rec}[/{rec_style}]",
        )
    console.print(table)


def _print_improvement_summary(report: dict):
    ready = report.get("ready_to_deploy", False)
    risk = report.get("deployment_risk", "unknown")
    risk_style = _severity_style(risk)
    ready_style = "green" if ready else "red"
    ci = report.get("confidence_interval", {})

    console.print(Panel(
        f"  Fixes applied:      [bold]{report.get('successful_fixes', 0)}[/bold] / {report.get('total_fixes_applied', 0)}\n"
        f"  Baseline pass rate: [bold]{report.get('baseline_pass_rate', 0):.0%}[/bold]\n"
        f"  Fixed pass rate:    [bold]{report.get('fixed_pass_rate', 0):.0%}[/bold]\n"
        f"  Improvement:        [bold]{report.get('pass_rate_improvement', 0):+.1f} pp[/bold]\n"
        f"  Significant:        [bold]{report.get('improvement_significant', False)}[/bold]\n"
        f"  95% CI:             [{ci.get('lower_bound', 0):.1%}, {ci.get('upper_bound', 0):.1%}]\n"
        f"  Regressions:        [bold]{report.get('regression_count', 0)}[/bold]\n"
        f"\n"
        f"  Ready to deploy:    [{ready_style}]{ready}[/{ready_style}]\n"
        f"  Deployment risk:    [{risk_style}]{risk}[/{risk_style}]",
        title="[bold]Improvement Summary[/bold]",
        style="blue",
    ))


@click.command()
@click.argument("diagnosis_report_file", type=click.Path(exists=True))
@click.argument("agent_map_file", type=click.Path(exists=True))
@click.argument("test_suite_file", type=click.Path(exists=True))
@click.option("--output", "-o", default="improvement", help="Output directory")
@click.option("--apply", "do_apply", is_flag=True, help="Actually apply fixes (default is dry run)")
@click.option("--agent-dir", "-d", default=None, type=click.Path(), help="Agent source directory (for file patching)")
@click.option("--baseline-fail-rate", default=0.05, type=float, help="Baseline mock fail rate for A/B test")
@click.option("--fixed-fail-rate", default=0.01, type=float, help="Fixed mock fail rate for A/B test")
@click.option("--smoke-limit", default=10, type=int, help="Max tests for smoke test")
@click.option("--full-limit", default=50, type=int, help="Max tests for full test")
@click.option("--workers", "-w", default=10, type=int, help="Max parallel workers for A/B tests")
@click.option("--language", "-l", default=None, help="Conversation language (auto-detects from agent_map)")
def main(
    diagnosis_report_file: str,
    agent_map_file: str,
    test_suite_file: str,
    output: str,
    do_apply: bool,
    agent_dir: str | None,
    baseline_fail_rate: float,
    fixed_fail_rate: float,
    smoke_limit: int,
    full_limit: int,
    workers: int,
    language: str | None,
):
    """Run Phase E: Improvement & Validation pipeline."""
    start = time.time()

    console.print(Panel(
        "[bold]Phase E: Improvement & Validation[/bold]\n"
        "Apply fixes, A/B test, validate, generate regression tests",
        style="blue",
    ))

    # Load inputs
    with open(diagnosis_report_file) as f:
        diagnosis_report = json.load(f)
    with open(agent_map_file) as f:
        agent_map = json.load(f)
    with open(test_suite_file) as f:
        test_suite = json.load(f)

    # Detect language
    if not language:
        language = agent_map.get("metadata", {}).get("conversation_language", "English")

    # Agent source dir
    source_dir = Path(agent_dir) if agent_dir else Path(".")

    total_fixes = len(diagnosis_report.get("fix_proposals", []))
    console.print(f"  Fixes to apply: [bold]{total_fixes}[/bold]")
    console.print(f"  Mode:           [bold]{'APPLY' if do_apply else 'DRY RUN'}[/bold]")
    console.print(f"  A/B testing:    baseline={baseline_fail_rate:.0%} fail → fixed={fixed_fail_rate:.0%} fail")
    console.print()

    if total_fixes == 0:
        console.print("[green]No fixes to apply — diagnosis found no actionable proposals.[/green]")
        return

    # Progress callback
    def on_progress(msg: str):
        console.print(f"  [dim]{msg}[/dim]")

    # Run Phase E
    engine = ImprovementEngine(
        agent_map=agent_map,
        agent_source_dir=source_dir,
        test_suite=test_suite,
        diagnosis_report=diagnosis_report,
        dry_run=not do_apply,
        baseline_fail_rate=baseline_fail_rate,
        fixed_fail_rate=fixed_fail_rate,
        smoke_limit=smoke_limit,
        full_limit=full_limit,
        max_workers=workers,
        language=language,
        on_progress=on_progress,
    )

    output_dir = Path(output)
    results = engine.run(output_dir)

    elapsed = time.time() - start
    console.print()

    # Display results
    _print_applied_fixes(results["applied_fixes"])
    console.print()
    _print_ab_results(results["ab_test_runs"])
    console.print()
    _print_improvement_summary(results["improvement_report"])

    # Regression tests
    reg_count = len(results.get("regression_tests", []))
    if reg_count > 0:
        console.print(f"\n[bold]Regression tests generated: {reg_count}[/bold]")

    # Deployment package
    pkg = results.get("deployment_package")
    if pkg:
        console.print(f"\n[bold green]Deployment package: {output_dir / 'deployment'}[/bold green]")
        console.print(f"  Version: {pkg.get('version', '?')}")

    # Output files
    console.print(f"\n[bold green]Output files saved to {output_dir}/[/bold green]")
    console.print(f"  applied_fixes.json")
    console.print(f"  ab_test_results.json")
    console.print(f"  improvement_report.json")
    console.print(f"  regression_tests.json")
    console.print(f"\n[dim]{elapsed:.1f}s[/dim]")


if __name__ == "__main__":
    main()
