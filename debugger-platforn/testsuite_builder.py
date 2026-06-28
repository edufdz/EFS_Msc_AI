#!/usr/bin/env python3
"""
Test Suite Builder CLI
~~~~~~~~~~~~~~~~~~~~~

Generate an executable test suite by combining personas, scenarios,
and coverage configuration from Phases B1-B3.

Usage:
    python testsuite_builder.py agent_map.json persona_library.json scenario_catalog.json test_configuration.json
    python testsuite_builder.py agent_map.json persona_library.json scenario_catalog.json test_configuration.json --count 500
    python testsuite_builder.py agent_map.json persona_library.json scenario_catalog.json test_configuration.json -o my_suite.json
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

from src.coverage.models import CoverageGoals, SandboxConfig, TestConfiguration
from src.generator.test_suite import TestSuiteGenerator
from src.personas.models import Persona, PersonaLibrary
from src.scenarios.models import Scenario, ScenarioCatalog

console = Console()


def _difficulty_style(d: str) -> str:
    return {"easy": "green", "medium": "yellow", "hard": "red"}.get(d, "white")


def _print_input_summary(personas, scenarios, config):
    """Show what we're working with."""
    table = Table(title="Input Summary", show_lines=True)
    table.add_column("Input", style="cyan", min_width=20)
    table.add_column("Count", justify="center", width=8)
    table.add_column("Details", max_width=50)

    # Personas
    persona_names = ", ".join(p.name for p in personas[:5])
    if len(personas) > 5:
        persona_names += f" +{len(personas) - 5} more"
    table.add_row("Personas", str(len(personas)), persona_names)

    # Scenarios
    base = sum(1 for s in scenarios if s.base_scenario_id is None)
    variants = len(scenarios) - base
    table.add_row("Scenarios", str(len(scenarios)), f"{base} base + {variants} variants")

    # Coverage tools
    tool_count = len(config.coverage_goals.tool_coverage.min_invocations_per_tool)
    total_min = sum(config.coverage_goals.tool_coverage.min_invocations_per_tool.values())
    table.add_row("Tools to cover", str(tool_count), f"{total_min} min invocations total")

    # Combos
    combo_count = len(config.coverage_goals.tool_coverage.tool_combinations)
    table.add_row("Tool combos", str(combo_count), "high-risk pairs")

    console.print(table)


def _print_suite_summary(summary):
    """Print test suite summary with rich formatting."""
    # Main stats
    console.print(Panel(
        f"  Total tests:         [bold]{summary.total_tests}[/bold]\n"
        f"  Estimated duration:  [bold]{summary.estimated_duration_min} min[/bold]\n"
        f"  Estimated cost:      [bold]${summary.estimated_cost_usd:.2f}[/bold]",
        title="Test Suite Summary",
        style="green",
    ))

    # By difficulty
    diff_parts = []
    for d in ["easy", "medium", "hard"]:
        count = summary.by_difficulty.get(d, 0)
        style = _difficulty_style(d)
        diff_parts.append(f"[{style}]{d}: {count}[/{style}]")
    console.print(f"  Difficulty: {', '.join(diff_parts)}")

    # By coverage goal
    table = Table(title="Coverage Goal Breakdown", show_lines=True)
    table.add_column("Coverage Goal", style="cyan", min_width=25)
    table.add_column("Tests", justify="center", width=8)
    table.add_column("Pct", justify="center", width=8)

    for goal, count in sorted(summary.by_coverage_goal.items(), key=lambda x: -x[1]):
        pct = round(100 * count / summary.total_tests, 1)
        table.add_row(goal, str(count), f"{pct}%")
    console.print(table)

    # By scenario type
    type_parts = []
    for t in ["happy_path", "edge_case", "error_path"]:
        count = summary.by_scenario_type.get(t, 0)
        style = {"happy_path": "green", "edge_case": "yellow", "error_path": "red"}.get(t, "white")
        type_parts.append(f"[{style}]{t}: {count}[/{style}]")
    console.print(f"  Scenario types: {', '.join(type_parts)}")

    # By persona
    console.print(f"\n  Persona distribution:")
    for name, count in sorted(summary.by_persona.items(), key=lambda x: -x[1]):
        bar_len = min(40, count // 2)
        bar = "#" * bar_len
        console.print(f"    [cyan]{name:<25}[/cyan] {count:>4}  [dim]{bar}[/dim]")

    # Tool coverage check
    console.print(f"\n  Unique tools hit: [bold]{len(summary.tool_invocation_counts)}[/bold]")
    top_tools = sorted(summary.tool_invocation_counts.items(), key=lambda x: -x[1])[:10]
    if top_tools:
        console.print("  Top 10 tools by invocation:")
        for tool, count in top_tools:
            console.print(f"    [cyan]{tool:<35}[/cyan] {count:>4}")


@click.command()
@click.argument("agent_map_file", type=click.Path(exists=True))
@click.argument("persona_library_file", type=click.Path(exists=True))
@click.argument("scenario_catalog_file", type=click.Path(exists=True))
@click.argument("test_config_file", type=click.Path(exists=True))
@click.option("--count", "-c", default=250, type=int, help="Target number of test cases")
@click.option("--output", "-o", default=None, help="Output JSON file path")
@click.option("--seed", "-s", default=None, type=int, help="Random seed for reproducibility")
def main(
    agent_map_file: str,
    persona_library_file: str,
    scenario_catalog_file: str,
    test_config_file: str,
    count: int,
    output: str | None,
    seed: int | None,
):
    """Generate a test suite from B1-B3 outputs."""
    import random as _random
    if seed is not None:
        _random.seed(seed)

    start = time.time()

    console.print(Panel(
        "[bold]Test Suite Builder[/bold]\nGenerate executable test cases from personas, scenarios, and coverage goals",
        style="blue",
    ))

    # Load all inputs
    with console.status("[bold green]Loading inputs..."):
        with open(agent_map_file) as f:
            agent_map = json.load(f)

        with open(persona_library_file) as f:
            persona_data = json.load(f)
        persona_lib = PersonaLibrary(**persona_data)
        personas = persona_lib.personas

        with open(scenario_catalog_file) as f:
            scenario_data = json.load(f)
        catalog = ScenarioCatalog(**scenario_data)
        scenarios = catalog.scenarios

        with open(test_config_file) as f:
            config_data = json.load(f)
        config = TestConfiguration(**config_data)

    agent_type = agent_map.get("metadata", {}).get("type", "custom")
    agent_purpose = agent_map.get("metadata", {}).get("purpose", "unknown")
    console.print(f"Agent type: [cyan]{agent_type}[/cyan]")
    console.print(f"Purpose: [dim]{agent_purpose}[/dim]\n")

    _print_input_summary(personas, scenarios, config)
    console.print()

    # Generate test suite
    console.print(f"[bold]Generating {count} test cases...[/bold]")
    with console.status("[bold green]Building test suite..."):
        generator = TestSuiteGenerator(
            agent_map=agent_map,
            personas=personas,
            scenarios=scenarios,
            coverage_goals=config.coverage_goals,
            sandbox_config=config.sandbox_config,
        )
        suite = generator.generate(target_count=count)

    console.print(f"[green]Generated {suite.summary.total_tests} test cases[/green]\n")

    _print_suite_summary(suite.summary)

    # Export
    output_path = output or "test_suite.json"
    with open(output_path, "w") as f:
        json.dump(suite.model_dump(), f, indent=2, default=str)

    elapsed = time.time() - start
    console.print(f"\n[bold green]Test suite saved to {output_path}[/bold green]")
    console.print(f"[dim]{suite.summary.total_tests} tests, {elapsed:.1f}s[/dim]")


if __name__ == "__main__":
    main()
