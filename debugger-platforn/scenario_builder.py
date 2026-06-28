#!/usr/bin/env python3
"""
Scenario Builder CLI
~~~~~~~~~~~~~~~~~~~~

Create a scenario catalog from an Agent Map JSON.

Usage:
    python scenario_builder.py agent_map.json
    python scenario_builder.py agent_map.json --skip-ai
    python scenario_builder.py agent_map.json --generate 5 --variants 3
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv(Path(__file__).parent / ".env")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.scenarios.library import ScenarioLibrary

console = Console()


def _difficulty_style(d: str) -> str:
    return {"easy": "green", "medium": "yellow", "hard": "red"}.get(d, "white")


def _print_scenario_table(scenarios, title="Scenario Catalog"):
    table = Table(title=title, show_lines=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("Title", style="cyan", min_width=25, max_width=35)
    table.add_column("Type", width=12)
    table.add_column("Diff.", width=6)
    table.add_column("Tools", max_width=30)
    table.add_column("Turns", justify="center", width=5)
    table.add_column("Source", style="dim", width=12)

    for i, s in enumerate(scenarios, 1):
        diff_style = _difficulty_style(s.difficulty)
        type_style = {
            "happy_path": "green", "error_path": "red", "edge_case": "yellow",
        }.get(s.type, "white")

        tools_str = ", ".join(s.required_tools[:3]) if s.required_tools else "-"
        if len(s.required_tools) > 3:
            tools_str += f" +{len(s.required_tools) - 3}"

        source_label = s.source
        if s.variant_type:
            source_label = f"variant:{s.variant_type}"

        table.add_row(
            str(i),
            s.title,
            f"[{type_style}]{s.type}[/{type_style}]",
            f"[{diff_style}]{s.difficulty}[/{diff_style}]",
            tools_str,
            str(s.estimated_turns),
            source_label,
        )

    console.print(table)


def _print_summary_stats(scenarios):
    by_type = {}
    by_diff = {}
    by_source = {}
    for s in scenarios:
        by_type[s.type] = by_type.get(s.type, 0) + 1
        by_diff[s.difficulty] = by_diff.get(s.difficulty, 0) + 1
        by_source[s.source] = by_source.get(s.source, 0) + 1

    parts = []
    for label, counts in [("Type", by_type), ("Difficulty", by_diff), ("Source", by_source)]:
        items = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        parts.append(f"[bold]{label}:[/bold] {items}")

    console.print(Panel("\n".join(parts), title="Distribution", style="dim"))


@click.command()
@click.argument("agent_map_file", type=click.Path(exists=True))
@click.option("--output", "-o", default=None, help="Output JSON file path")
@click.option("--skip-ai", is_flag=True, help="Skip AI generation; use templates + offline variants only")
@click.option("--generate", "-g", default=0, type=int,
              help="Number of AI-generated base scenarios to add")
@click.option("--variants", "-v", default=5, type=int,
              help="Number of variants per base scenario (0 to skip)")
def main(
    agent_map_file: str,
    output: str | None,
    skip_ai: bool,
    generate: int,
    variants: int,
):
    """Build a scenario catalog from an Agent Map JSON."""
    start = time.time()

    console.print(Panel(
        "[bold]Scenario Builder[/bold]\nCreate test scenarios for agent testing",
        style="blue",
    ))

    with open(agent_map_file) as f:
        agent_map = json.load(f)

    agent_type = agent_map.get("metadata", {}).get("type", "custom")
    agent_purpose = agent_map.get("metadata", {}).get("purpose", "unknown")
    tool_names = [t["name"] for t in agent_map.get("components", {}).get("tools", [])]

    console.print(f"Agent type: [cyan]{agent_type}[/cyan]")
    console.print(f"Purpose: [dim]{agent_purpose}[/dim]")
    console.print(f"Tools: [green]{', '.join(tool_names) if tool_names else 'none'}[/green]\n")

    library = ScenarioLibrary(agent_map)
    has_api_key = bool(os.environ.get("ANTHROPIC_API_KEY"))

    # Step 1: Load templates
    with console.status("[bold green]Loading scenario templates..."):
        base_scenarios = library.load_templates()
    console.print(f"Loaded [green]{len(base_scenarios)}[/green] template scenarios")

    # Step 2: AI-generated base scenarios
    if generate > 0 and not skip_ai and has_api_key:
        with console.status(f"[bold green]Generating {generate} AI scenarios..."):
            ai_scenarios = library.generate_scenarios(count=generate)
        console.print(f"Generated [green]{len(ai_scenarios)}[/green] AI scenarios")
    elif generate > 0:
        reason = "--skip-ai" if skip_ai else "ANTHROPIC_API_KEY not set"
        console.print(f"[yellow]AI generation skipped ({reason})[/yellow]")

    # Step 3: Variant expansion
    if variants > 0:
        # Get only base scenarios (no variants yet)
        bases = [s for s in library.scenarios if s.base_scenario_id is None]
        total_variants = 0

        if skip_ai or not has_api_key:
            console.print(f"\n[bold]Generating offline variants for {len(bases)} base scenarios...[/bold]")
            for base in bases:
                v = library.generate_offline_variants(base)
                total_variants += len(v)
                console.print(f"  [cyan]{base.title}[/cyan] -> +{len(v)} variants")
        else:
            console.print(f"\n[bold]Generating AI variants ({variants} each) for {len(bases)} base scenarios...[/bold]")
            for base in bases:
                with console.status(f"[green]  {base.title}..."):
                    v = library.generate_variants(base, count=variants)
                total_variants += len(v)
                console.print(f"  [cyan]{base.title}[/cyan] -> +{len(v)} variants")

        console.print(f"Total variants generated: [green]{total_variants}[/green]")

    # Print catalog
    console.print()
    _print_scenario_table(library.scenarios)
    _print_summary_stats(library.scenarios)

    # Export
    catalog = library.export_catalog()
    output_path = output or "scenario_catalog.json"

    with open(output_path, "w") as f:
        json.dump(catalog.model_dump(), f, indent=2, default=str)

    elapsed = time.time() - start
    console.print(f"\n[bold green]Scenario catalog saved to {output_path}[/bold green]")
    console.print(
        f"[dim]{catalog.base_scenarios_count} base + "
        f"{catalog.total_scenarios_count - catalog.base_scenarios_count} variants = "
        f"{catalog.total_scenarios_count} total scenarios, {elapsed:.1f}s[/dim]"
    )


if __name__ == "__main__":
    main()
