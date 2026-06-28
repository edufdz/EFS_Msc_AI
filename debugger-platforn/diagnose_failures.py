#!/usr/bin/env python3
"""
Diagnosis CLI (Phase D)
~~~~~~~~~~~~~~~~~~~~~~~~

Analyze test failures: cluster them, identify root causes,
generate minimal reproductions, propose fixes, and rank by priority.

Usage:
    # Default (AI-powered analysis)
    python diagnose_failures.py results/failure_inbox.json results/test_run_report.json agent_map.json

    # Skip AI (offline heuristics only)
    python diagnose_failures.py results/failure_inbox.json results/test_run_report.json agent_map.json --skip-ai

    # Custom output path
    python diagnose_failures.py results/failure_inbox.json results/test_run_report.json agent_map.json -o results/diagnosis.json
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

from src.diagnosis.engine import DiagnosisEngine

console = Console()


def _severity_style(severity: str) -> str:
    return {
        "critical": "bold red",
        "high": "red",
        "medium": "yellow",
        "low": "green",
    }.get(severity, "white")


def _print_clusters(report):
    """Print cluster summary table."""
    table = Table(title="Failure Clusters", show_lines=True)
    table.add_column("#", justify="center", width=3)
    table.add_column("Root Cause", style="cyan", min_width=20)
    table.add_column("Failures", justify="center", width=9)
    table.add_column("Severity", justify="center", width=10)
    table.add_column("Affected Scenarios", min_width=25)
    table.add_column("Key Indicators", min_width=25)

    for i, cluster in enumerate(report.clusters, 1):
        sev = cluster.severity.value
        sev_style = _severity_style(sev)
        scenarios = ", ".join(s[:25] for s in cluster.affected_scenarios[:3])
        if len(cluster.affected_scenarios) > 3:
            scenarios += f" (+{len(cluster.affected_scenarios) - 3})"
        indicators = ", ".join(cluster.key_indicators[:3])

        table.add_row(
            str(i),
            cluster.root_cause_type.value,
            str(cluster.failure_count),
            f"[{sev_style}]{sev}[/{sev_style}]",
            scenarios,
            indicators,
        )

    console.print(table)


def _print_fix_proposals(report):
    """Print fix proposals table."""
    if not report.fix_proposals:
        console.print("[dim]No fix proposals generated.[/dim]")
        return

    table = Table(title="Fix Proposals", show_lines=True)
    table.add_column("#", justify="center", width=3)
    table.add_column("Type", style="cyan", width=16)
    table.add_column("Description", min_width=35)
    table.add_column("Fix Rate", justify="center", width=9)
    table.add_column("Effort", justify="center", width=8)
    table.add_column("Risk", justify="center", width=6)

    for i, fix in enumerate(report.fix_proposals, 1):
        effort_style = {"low": "green", "medium": "yellow", "high": "red"}.get(fix.estimated_effort, "white")
        risk_style = {"low": "green", "medium": "yellow", "high": "red"}.get(fix.risk_level, "white")

        table.add_row(
            str(i),
            fix.fix_type,
            fix.description[:60],
            f"{fix.estimated_fix_rate:.0%}",
            f"[{effort_style}]{fix.estimated_effort}[/{effort_style}]",
            f"[{risk_style}]{fix.risk_level}[/{risk_style}]",
        )

    console.print(table)


def _print_priority_ranking(report):
    """Print priority ranking."""
    if not report.priority_ranking:
        return

    cluster_map = {c.cluster_id: c for c in report.clusters}
    console.print("\n[bold]Priority Ranking (highest impact first):[/bold]")
    for rank, cid in enumerate(report.priority_ranking, 1):
        cluster = cluster_map.get(cid)
        if cluster:
            sev_style = _severity_style(cluster.severity.value)
            console.print(
                f"  {rank}. [{sev_style}]{cluster.severity.value.upper()}[/{sev_style}] "
                f"[cyan]{cluster.root_cause_type.value}[/cyan] "
                f"({cluster.failure_count} failures)"
            )


def _print_summary(report):
    """Print summary panel."""
    s = report.summary
    console.print(Panel(
        f"  Total failures analyzed: [bold]{s.get('total_failures_analyzed', 0)}[/bold]\n"
        f"  Total tests:             [bold]{s.get('total_tests', 0)}[/bold]\n"
        f"  Failure rate:            [bold red]{s.get('failure_rate', 0)}%[/bold red]\n"
        f"  Clusters found:          [bold]{s.get('clusters_count', 0)}[/bold]\n"
        f"  Fix proposals:           [bold]{s.get('fixes_count', 0)}[/bold]\n"
        f"\n"
        f"  [bold underline]Performance Metrics[/bold underline]\n"
        f"  Bug discovery rate:      [bold green]{s.get('bug_discovery_rate', 0)}%[/bold green]  (unique bugs / tests)\n"
        f"  Redundancy rate:         [bold yellow]{s.get('redundancy_rate', 0)}%[/bold yellow]  (duplicate findings)\n"
        f"  Severity-weighted score: [bold]{s.get('severity_weighted_score', 0)}[/bold]  (avg severity per failure)\n"
        f"\n"
        f"  By root cause:  {_format_dict(s.get('by_root_cause', {}))}\n"
        f"  By severity:    {_format_dict(s.get('by_severity', {}))}",
        title="[bold]Diagnosis Summary[/bold]",
        style="blue",
    ))


def _format_dict(d: dict) -> str:
    if not d:
        return "[dim]none[/dim]"
    return ", ".join(f"[cyan]{k}[/cyan]={v}" for k, v in d.items())


def _print_reproductions(report):
    """Print minimal reproduction summaries."""
    has_repro = [c for c in report.clusters if c.minimal_reproduction]
    if not has_repro:
        return

    console.print("\n[bold]Minimal Reproductions:[/bold]")
    for cluster in has_repro:
        repro = cluster.minimal_reproduction
        expected = repro.get("expected_behavior", "N/A")
        actual = repro.get("actual_behavior", "N/A")
        steps = repro.get("steps_to_reproduce", [])

        console.print(f"\n  [cyan]{cluster.cluster_name}[/cyan]")
        console.print(f"    Expected: [green]{expected[:80]}[/green]")
        console.print(f"    Actual:   [red]{actual[:80]}[/red]")
        if steps:
            console.print(f"    Steps:    {steps[0][:60]}")
            for step in steps[1:3]:
                console.print(f"              {step[:60]}")


@click.command()
@click.argument("failure_inbox_file", type=click.Path(exists=True))
@click.argument("test_report_file", type=click.Path(exists=True))
@click.argument("agent_map_file", type=click.Path(exists=True))
@click.option("--output", "-o", default=None, help="Output JSON file path")
@click.option("--skip-ai", is_flag=True, help="Skip AI analysis (offline heuristics only)")
@click.option("--use-embeddings", is_flag=True, help="Use sentence-transformers for clustering (requires extra install)")
@click.option("--max-retries", default=3, type=int, help="Max retries for AI API calls (default 3)")
@click.option("--backoff-base", default=2.0, type=float, help="Exponential backoff base in seconds (default 2.0)")
@click.option("--backoff-max", default=60.0, type=float, help="Maximum backoff delay in seconds (default 60.0)")
@click.option("--ai-workers", default=1, type=int, help="Parallel AI workers (default 1, reserved for future use)")
def main(
    failure_inbox_file: str,
    test_report_file: str,
    agent_map_file: str,
    output: str | None,
    skip_ai: bool,
    use_embeddings: bool,
    max_retries: int,
    backoff_base: float,
    backoff_max: float,
    ai_workers: int,
):
    """Analyze test failures and generate diagnosis report."""
    start = time.time()

    console.print(Panel(
        "[bold]Phase D: Diagnosis & Analysis[/bold]\n"
        "Cluster failures, identify root causes, generate fixes",
        style="blue",
    ))

    # Load inputs
    with open(failure_inbox_file) as f:
        failure_inbox = json.load(f)
    with open(test_report_file) as f:
        test_run_report = json.load(f)
    with open(agent_map_file) as f:
        agent_map = json.load(f)

    total_failures = failure_inbox.get("total_failures", len(failure_inbox.get("failures", [])))
    console.print(f"  Failures to analyze: [bold]{total_failures}[/bold]")
    console.print(f"  AI analysis:         [bold]{'off' if skip_ai else 'on'}[/bold]")
    console.print(f"  Embedding clustering: [bold]{'on' if use_embeddings else 'off (TF-IDF)'}[/bold]")
    console.print()

    if total_failures == 0:
        console.print("[green]No failures to analyze — all tests passed![/green]")
        return

    # Run diagnosis
    def on_progress(msg: str):
        console.print(f"  [dim]{msg}[/dim]")

    engine = DiagnosisEngine(
        use_ai=not skip_ai,
        use_embeddings=use_embeddings,
        on_progress=on_progress,
        max_retries=max_retries,
        backoff_base=backoff_base,
        backoff_max=backoff_max,
        ai_workers=ai_workers,
    )

    report = engine.diagnose(failure_inbox, test_run_report, agent_map)

    elapsed = time.time() - start
    console.print()

    # Display results
    _print_clusters(report)
    console.print()
    _print_fix_proposals(report)
    _print_priority_ranking(report)
    _print_reproductions(report)
    console.print()
    _print_summary(report)

    # Save report
    output_path = output or "results/diagnosis_report.json"
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    report_dict = report.model_dump(mode="json")
    with open(output_path, "w") as f:
        json.dump(report_dict, f, indent=2, default=str)

    console.print(f"\n[bold green]Diagnosis report saved to {output_path}[/bold green]")
    console.print(f"[dim]{elapsed:.1f}s[/dim]")


if __name__ == "__main__":
    main()
