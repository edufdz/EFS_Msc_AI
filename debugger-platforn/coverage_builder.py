#!/usr/bin/env python3
"""
Coverage Builder CLI
~~~~~~~~~~~~~~~~~~~~

Auto-calculate coverage goals and sandbox configuration from an Agent Map.

Usage:
    python coverage_builder.py agent_map.json
    python coverage_builder.py agent_map.json -o test_config.json
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

from src.coverage.calculator import (
    build_test_configuration,
    calculate_coverage_goals,
    generate_sandbox_config,
)

console = Console()


def _risk_style(risk: str) -> str:
    return {"critical": "bold red", "high": "red", "medium": "yellow", "low": "green"}.get(risk, "white")


def _mode_style(mode: str) -> str:
    return {"mock": "yellow", "real": "green", "capture": "cyan"}.get(mode, "white")


def _print_coverage_goals(goals):
    """Print coverage goals as rich tables."""
    # Tool coverage
    tc = goals.tool_coverage
    table = Table(title="Tool Coverage Goals", show_lines=True)
    table.add_column("Tool", style="cyan", min_width=20, max_width=35)
    table.add_column("Min Invocations", justify="center", width=16)

    for tool_name, min_calls in sorted(tc.min_invocations_per_tool.items()):
        style = "red" if min_calls >= 25 else "yellow" if min_calls >= 15 else "green"
        table.add_row(tool_name, f"[{style}]{min_calls}[/{style}]")

    console.print(table)
    console.print(f"  Target coverage: [bold]{tc.target_percentage}%[/bold]")
    console.print(f"  Tool combinations to test: [bold]{len(tc.tool_combinations)}[/bold]")

    # Edge-case coverage
    ec = goals.edge_case_coverage
    console.print(Panel(
        f"  Ambiguous requests:      [yellow]{ec.ambiguous_requests}[/yellow]\n"
        f"  Incomplete information:   [yellow]{ec.incomplete_information}[/yellow]\n"
        f"  User changes mind:        [yellow]{ec.user_changes_mind}[/yellow]\n"
        f"  Contradictory statements: [yellow]{ec.contradictory_statements}[/yellow]",
        title="Edge-Case Coverage Goals",
        style="dim",
    ))

    # Stressor coverage
    sc = goals.stressor_coverage
    console.print(Panel(
        f"  Timeout scenarios:           [red]{sc.timeout_scenarios}[/red]\n"
        f"  Malformed response scenarios: [red]{sc.malformed_response_scenarios}[/red]\n"
        f"  Data conflict scenarios:      [red]{sc.data_conflict_scenarios}[/red]",
        title="Stressor Coverage Goals",
        style="dim",
    ))


def _print_sandbox_config(sandbox):
    """Print sandbox config as rich table."""
    table = Table(title="Sandbox Configuration", show_lines=True)
    table.add_column("Tool", style="cyan", min_width=20, max_width=35)
    table.add_column("Mode", width=8)
    table.add_column("Mock Strategy", width=14)
    table.add_column("Rate Limit", justify="center", width=10)
    table.add_column("Confirm?", justify="center", width=8)
    table.add_column("Latency", width=16)

    for tool_name, cfg in sorted(sandbox.tool_configs.items()):
        mode_s = _mode_style(cfg.mode)
        latency_str = (
            f"{cfg.latency_simulation['min_ms']}-{cfg.latency_simulation['max_ms']}ms"
            if cfg.latency_simulation else "-"
        )
        table.add_row(
            tool_name,
            f"[{mode_s}]{cfg.mode}[/{mode_s}]",
            cfg.mock_strategy or "-",
            str(cfg.rate_limit) if cfg.rate_limit else "-",
            "[red]YES[/red]" if cfg.require_confirmation else "no",
            latency_str,
        )

    console.print(table)

    # Cost limits
    console.print(Panel(
        "\n".join(f"  {k}: [bold]{v}[/bold]" for k, v in sandbox.cost_limits.items()),
        title="Cost Limits",
        style="dim",
    ))

    # Safety rules
    console.print(Panel(
        "\n".join(f"  {k}: [bold]{v}[/bold]" for k, v in sandbox.safety.items()),
        title="Safety Rules",
        style="dim",
    ))


def _print_risk_summary(agent_map):
    """Print a quick risk summary from the agent map."""
    tools = agent_map.get("components", {}).get("tools", [])
    seen = set()
    risk_counts = {}
    for t in tools:
        if t["name"] in seen:
            continue
        seen.add(t["name"])
        r = t.get("risk_level", "medium")
        risk_counts[r] = risk_counts.get(r, 0) + 1

    parts = []
    for risk in ["critical", "high", "medium", "low"]:
        count = risk_counts.get(risk, 0)
        if count:
            style = _risk_style(risk)
            parts.append(f"[{style}]{risk}: {count}[/{style}]")

    console.print(f"  Tool risk profile: {', '.join(parts)}")
    console.print(f"  Unique tools: [bold]{len(seen)}[/bold]")


@click.command()
@click.argument("agent_map_file", type=click.Path(exists=True))
@click.option("--output", "-o", default=None, help="Output JSON file path")
def main(agent_map_file: str, output: str | None):
    """Build coverage goals and sandbox config from an Agent Map JSON."""
    start = time.time()

    console.print(Panel(
        "[bold]Coverage Builder[/bold]\nAuto-calculate coverage goals & sandbox configuration",
        style="blue",
    ))

    with open(agent_map_file) as f:
        agent_map = json.load(f)

    agent_type = agent_map.get("metadata", {}).get("type", "custom")
    agent_purpose = agent_map.get("metadata", {}).get("purpose", "unknown")
    console.print(f"Agent type: [cyan]{agent_type}[/cyan]")
    console.print(f"Purpose: [dim]{agent_purpose}[/dim]\n")

    _print_risk_summary(agent_map)
    console.print()

    # Calculate coverage goals
    with console.status("[bold green]Calculating coverage goals..."):
        goals = calculate_coverage_goals(agent_map)
    console.print("[green]Coverage goals calculated[/green]\n")
    _print_coverage_goals(goals)

    # Generate sandbox config
    with console.status("[bold green]Generating sandbox configuration..."):
        sandbox = generate_sandbox_config(agent_map)
    console.print("\n[green]Sandbox configuration generated[/green]\n")
    _print_sandbox_config(sandbox)

    # Build full test configuration
    config = build_test_configuration(agent_map)

    # Export
    output_path = output or "test_configuration.json"
    with open(output_path, "w") as f:
        json.dump(config.model_dump(), f, indent=2, default=str)

    elapsed = time.time() - start

    # Summary
    tool_count = len(sandbox.tool_configs)
    mock_count = sum(1 for c in sandbox.tool_configs.values() if c.mode == "mock")
    capture_count = sum(1 for c in sandbox.tool_configs.values() if c.mode == "capture")
    real_count = sum(1 for c in sandbox.tool_configs.values() if c.mode == "real")

    console.print(Panel(
        f"  Tools configured:  [bold]{tool_count}[/bold]\n"
        f"  Mock mode:         [yellow]{mock_count}[/yellow]\n"
        f"  Capture mode:      [cyan]{capture_count}[/cyan]\n"
        f"  Real mode:         [green]{real_count}[/green]\n"
        f"  Tool combinations: [bold]{len(goals.tool_coverage.tool_combinations)}[/bold]",
        title="Summary",
        style="green",
    ))

    console.print(f"\n[bold green]Test configuration saved to {output_path}[/bold green]")
    console.print(f"[dim]{elapsed:.1f}s[/dim]")


if __name__ == "__main__":
    main()
