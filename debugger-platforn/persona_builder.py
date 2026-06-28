#!/usr/bin/env python3
"""
Persona Builder CLI
~~~~~~~~~~~~~~~~~~~

Create a persona library from an Agent Map JSON.

Usage:
    python persona_builder.py agent_map.json
    python persona_builder.py agent_map.json --skip-ai
    python persona_builder.py agent_map.json -o personas.json --count 5
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

# Load .env and set up path
load_dotenv(Path(__file__).parent / ".env")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.personas.builder import PersonaBuilder

console = Console()


def _print_persona_table(personas, title="Persona Library"):
    table = Table(title=title)
    table.add_column("Name", style="cyan", min_width=20)
    table.add_column("Source", style="dim")
    table.add_column("Patience", justify="center")
    table.add_column("Clarity", justify="center")
    table.add_column("Tech", justify="center")
    table.add_column("Tone", style="yellow")
    table.add_column("Edge Behaviors", style="red", max_width=30)

    for p in personas:
        edge_list = [k for k, v in p.edge_behaviors.model_dump().items() if v]
        edge_str = ", ".join(edge_list) if edge_list else "-"
        table.add_row(
            p.name,
            p.source,
            f"{p.traits.patience}/10",
            f"{p.traits.clarity}/10",
            f"{p.traits.tech_savviness}/10",
            p.style.tone,
            edge_str,
        )

    console.print(table)


@click.command()
@click.argument("agent_map_file", type=click.Path(exists=True))
@click.option("--output", "-o", default=None, help="Output JSON file path")
@click.option("--skip-ai", is_flag=True, help="Skip AI generation; use only templates")
@click.option("--generate", "-g", default=0, type=int,
              help="Number of AI-generated personas to add (requires ANTHROPIC_API_KEY)")
@click.option("--sample-messages", "-s", default=0, type=int,
              help="Number of sample messages to generate per persona")
@click.option("--use-tlahuac", is_flag=True, help="Load personas from tlahuac data (auto-detects sibling directory)")
@click.option("--tlahuac-dir", default=None, type=click.Path(exists=True), help="Path to tlahuac persona pack directory")
@click.option("--tlahuac-endpoint", default="http://localhost:8000", help="Tlahuac API endpoint (fallback)")
@click.option("--tlahuac-personas", multiple=True, help="Specific tlahuac persona IDs to load")
def main(
    agent_map_file: str,
    output: str | None,
    skip_ai: bool,
    generate: int,
    sample_messages: int,
    use_tlahuac: bool,
    tlahuac_dir: str | None,
    tlahuac_endpoint: str,
    tlahuac_personas: tuple,
):
    """Build a persona library from an Agent Map JSON."""
    start = time.time()

    console.print(Panel(
        "[bold]Persona Builder[/bold]\nCreate synthetic user personas for agent testing",
        style="blue",
    ))

    # Load agent map
    with open(agent_map_file) as f:
        agent_map = json.load(f)

    agent_type = agent_map.get("metadata", {}).get("type", "custom")
    agent_purpose = agent_map.get("metadata", {}).get("purpose", "unknown")
    console.print(f"Agent type: [cyan]{agent_type}[/cyan]")
    console.print(f"Purpose: [dim]{agent_purpose}[/dim]\n")

    builder = PersonaBuilder(agent_map)

    # Step 1: Load templates (skip when using tlahuac-only mode)
    if not use_tlahuac:
        with console.status("[bold green]Loading persona templates..."):
            templates = builder.load_templates()
        console.print(f"Loaded [green]{len(templates)}[/green] template personas")

    # Step 1b: Tlahuac persona loading
    if use_tlahuac:
        # Resolve data directory
        data_dir = tlahuac_dir
        if not data_dir:
            from pathlib import Path as _P
            auto_dir = _P(__file__).parent.parent / "tlahuac_simulator_agent"
            if auto_dir.exists():
                data_dir = str(auto_dir)

        if data_dir:
            try:
                with console.status("[bold green]Loading tlahuac personas from disk..."):
                    tlahuac_list = builder.load_from_external(
                        data_dir=data_dir,
                        selected_ids=list(tlahuac_personas) or None,
                    )
                console.print(f"Loaded [green]{len(tlahuac_list)}[/green] tlahuac personas from [cyan]{data_dir}[/cyan]")
            except Exception as e:
                console.print(f"[red]Failed to load tlahuac personas: {e}[/red]")
                console.print("[yellow]Continuing with template personas only[/yellow]")
        else:
            try:
                with console.status("[bold green]Loading tlahuac personas from API..."):
                    tlahuac_list = builder.load_from_provider(
                        endpoint=tlahuac_endpoint,
                        provider_name="tlahuac",
                        selected_ids=list(tlahuac_personas) or None,
                    )
                console.print(f"Loaded [green]{len(tlahuac_list)}[/green] tlahuac personas from API")
            except Exception as e:
                console.print(f"[red]Failed to load tlahuac personas: {e}[/red]")
                console.print("[yellow]Continuing with template personas only[/yellow]")

    # Step 2: AI-generated personas
    has_api_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if generate > 0 and not skip_ai and has_api_key:
        with console.status(f"[bold green]Generating {generate} AI personas..."):
            ai_personas = builder.generate_personas(count=generate)
        console.print(f"Generated [green]{len(ai_personas)}[/green] AI personas")
    elif generate > 0 and (skip_ai or not has_api_key):
        reason = "skipped (--skip-ai)" if skip_ai else "ANTHROPIC_API_KEY not set"
        console.print(f"[yellow]AI generation {reason}[/yellow]")

    # Print persona table
    console.print()
    _print_persona_table(builder.personas)

    # Step 3: Sample messages
    if sample_messages > 0 and not skip_ai and has_api_key:
        console.print(f"\n[bold]Generating {sample_messages} sample messages per persona...[/bold]")
        for persona in builder.personas:
            with console.status(f"[green]  {persona.name}..."):
                msgs = builder.generate_sample_messages(persona, count=sample_messages)
            console.print(f"  [cyan]{persona.name}[/cyan]:")
            for msg in msgs:
                console.print(f"    \"{msg}\"")
    elif sample_messages > 0 and (skip_ai or not has_api_key):
        reason = "skipped (--skip-ai)" if skip_ai else "ANTHROPIC_API_KEY not set"
        console.print(f"\n[yellow]Sample messages {reason}[/yellow]")

    # Step 4: Export
    library = builder.export_library()
    output_path = output or "persona_library.json"

    with open(output_path, "w") as f:
        json.dump(library.model_dump(), f, indent=2, default=str)

    elapsed = time.time() - start
    console.print(f"\n[bold green]Persona library saved to {output_path}[/bold green]")
    console.print(f"[dim]{len(builder.personas)} personas, {elapsed:.1f}s[/dim]")


if __name__ == "__main__":
    main()
