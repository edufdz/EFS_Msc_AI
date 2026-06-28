#!/usr/bin/env python3
"""
Agent Code Analyzer CLI
~~~~~~~~~~~~~~~~~~~~~~~

Analyze an agent codebase to produce a structured Agent Map JSON.

Usage:
    python analyze.py /path/to/agent/repo
    python analyze.py /path/to/agent/repo --skip-ai
    python analyze.py /path/to/agent/repo -o agent_map.json
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
from rich.tree import Tree

# Load .env file from project root
project_root = Path(__file__).parent
load_dotenv(project_root / ".env")

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.ingestion.ingestor import ingest_directory
from src.analysis.static_analyzer import analyze_files
from src.patterns.detector import detect_patterns
from src.risk.analyzer import analyze_risks
from src.graph.builder import generate_agent_map

console = Console()


def _print_ingestion_summary(result):
    table = Table(title="Ingestion Summary")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Root path", result.root_path)
    table.add_row("Project type", result.project_type)
    table.add_row("Files found", str(len(result.files)))
    table.add_row("Entry points", str(len(result.entry_points)))
    table.add_row("Prompt files", str(len(result.prompt_files)))
    console.print(table)


def _print_pattern_summary(pattern_result):
    console.print(f"\n[bold]Framework detected:[/bold] {pattern_result.framework} "
                  f"(confidence: {pattern_result.framework_confidence:.0%})")

    if pattern_result.tools:
        tree = Tree("[bold]Tools found[/bold]")
        for t in pattern_result.tools:
            desc = (t.description or "no description")[:80]
            leaf = tree.add(f"[cyan]{t.name}[/cyan] ({t.source})")
            leaf.add(f"[dim]{desc}[/dim]")
        console.print(tree)
    else:
        console.print("[yellow]No tools detected[/yellow]")

    if pattern_result.prompts:
        console.print(f"\n[bold]Prompts found:[/bold] {len(pattern_result.prompts)}")
        for p in pattern_result.prompts:
            console.print(f"  - {p.name} ({p.type})")

    if pattern_result.memory_systems:
        console.print(f"\n[bold]Memory systems:[/bold] {len(pattern_result.memory_systems)}")
        for m in pattern_result.memory_systems:
            console.print(f"  - {m.type}: {m.implementation}")


def _print_risk_summary(risks):
    if not risks:
        console.print("\n[green]No risks detected[/green]")
        return

    table = Table(title="Risk Analysis")
    table.add_column("Tool", style="cyan")
    table.add_column("Type", style="yellow")
    table.add_column("Severity")
    table.add_column("Description")

    for r in risks:
        severity_style = {
            "low": "green", "medium": "yellow",
            "high": "red", "critical": "bold red",
        }.get(r.severity, "white")
        table.add_row(
            r.tool or "-",
            r.risk_type,
            f"[{severity_style}]{r.severity}[/{severity_style}]",
            r.description[:80],
        )
    console.print(table)


def _print_ai_summary(ai_result):
    if ai_result.goal:
        panel = Panel(
            f"[bold]Purpose:[/bold] {ai_result.goal.purpose}\n"
            f"[bold]Domain:[/bold] {ai_result.goal.domain}\n"
            f"[bold]Capabilities:[/bold] {', '.join(ai_result.goal.capabilities)}\n"
            f"[bold]Confidence:[/bold] {ai_result.goal.confidence:.0%}",
            title="AI Goal Analysis",
        )
        console.print(panel)

    if ai_result.workflow:
        console.print(f"\n[bold]Decision strategy:[/bold] {ai_result.workflow.decision_strategy}")
        if ai_result.workflow.guardrails:
            console.print("[bold]Guardrails:[/bold]")
            for g in ai_result.workflow.guardrails:
                console.print(f"  - {g}")


@click.command()
@click.argument("repo_path", type=click.Path(exists=True))
@click.option("--output", "-o", default=None, help="Output JSON file path")
@click.option("--skip-ai", is_flag=True, help="Skip AI semantic analysis (offline mode)")
@click.option("--language", "-l", default=None, help="Language filter (default: None = scan all languages)")
@click.option("--prompt-encoding", default="utf-8", help="Encoding for prompt files (default: utf-8)")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def main(
    repo_path: str,
    output: str | None,
    skip_ai: bool,
    language: str | None,
    prompt_encoding: str,
    verbose: bool,
):
    """Analyze an agent codebase and generate an Agent Map."""
    start_time = time.time()

    console.print(Panel("[bold]Agent Code Analyzer[/bold]\nAI-powered agent architecture discovery", style="blue"))

    # ── Step 1: Ingest ──
    with console.status("[bold green]Scanning codebase..."):
        ingestion = ingest_directory(repo_path, language_filter=language)
    _print_ingestion_summary(ingestion)

    if not ingestion.files:
        console.print("[red]No relevant files found. Check your path and language filter.[/red]")
        raise SystemExit(1)

    # ── Step 2: Static Analysis ──
    with console.status("[bold green]Parsing with Tree-sitter..."):
        file_paths = [f.path for f in ingestion.files]
        all_symbols = analyze_files(file_paths)

    total_funcs = sum(len(s.functions) for s in all_symbols)
    total_classes = sum(len(s.classes) for s in all_symbols)
    total_imports = sum(len(s.imports) for s in all_symbols)
    console.print(f"\n[bold]Static analysis:[/bold] {total_funcs} functions, "
                  f"{total_classes} classes, {total_imports} imports across "
                  f"{len(all_symbols)} files")

    if verbose:
        for sym in all_symbols:
            if sym.parse_errors:
                for err in sym.parse_errors:
                    console.print(f"  [yellow]Parse warning: {err}[/yellow]")

    # ── Step 3: Pattern Detection ──
    with console.status("[bold green]Detecting agent patterns..."):
        pattern_result = detect_patterns(
            all_symbols,
            ingestion.prompt_files,
            prompt_encoding=prompt_encoding,
        )
    _print_pattern_summary(pattern_result)

    # ── Step 4: Risk Analysis ──
    with console.status("[bold green]Analyzing risks..."):
        risks = analyze_risks(pattern_result.tools, pattern_result.prompts)
    _print_risk_summary(risks)

    # ── Step 5: AI Semantic Analysis (optional) ──
    ai_result = None
    if not skip_ai:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            console.print("\n[yellow]ANTHROPIC_API_KEY not set – skipping AI analysis.[/yellow]")
            console.print("[dim]Set ANTHROPIC_API_KEY or use --skip-ai to suppress this warning.[/dim]")
        else:
            with console.status("[bold green]Running AI semantic analysis (this may take a minute)..."):
                from src.ai_analyzer.analyzer import run_semantic_analysis
                ai_result = run_semantic_analysis(
                    all_symbols=all_symbols,
                    tools=pattern_result.tools,
                    prompts=pattern_result.prompts,
                    entry_points=ingestion.entry_points,
                    framework=pattern_result.framework,
                )
            _print_ai_summary(ai_result)

    # ── Step 6: Build Agent Map ──
    with console.status("[bold green]Building Agent Map..."):
        agent_map = generate_agent_map(
            all_symbols=all_symbols,
            pattern_result=pattern_result,
            ai_result=ai_result,
            risks=risks,
            entry_points=ingestion.entry_points,
            root_path=ingestion.root_path,
        )

    # ── Output ──
    elapsed = time.time() - start_time
    output_path = output or "agent_map.json"
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(agent_map, f, indent=2, default=str)

    console.print(f"\n[bold green]Agent Map written to {output_path}[/bold green]")

    # Generate graph visualizations
    try:
        from src.graph.visualizer import visualize_agent_map
        png_path, mmd_path = visualize_agent_map(agent_map, str(Path(output_path).parent))
        console.print(f"[bold green]Graph saved to {png_path}[/bold green]")
        console.print(f"[bold green]Mermaid saved to {mmd_path}[/bold green]")
    except ModuleNotFoundError as e:
        if "matplotlib" in str(e):
            console.print("[yellow]Graph generation skipped: matplotlib not installed.[/yellow]")
            console.print("[dim]Install with: uv sync  (or pip install matplotlib)[/dim]")
        else:
            console.print(f"[yellow]Graph generation skipped: {e}[/yellow]")
    except Exception as e:
        console.print(f"[yellow]Graph generation skipped: {e}[/yellow]")

    console.print(f"[dim]Analysis completed in {elapsed:.1f}s[/dim]")

    # Quick summary
    n_tools = len(agent_map["components"]["tools"])
    n_risks = len(agent_map["risk_flags"]["all_risks"])
    n_prompts = len(agent_map["components"]["prompts"])
    conv_lang = agent_map["metadata"].get("conversation_language", "English")
    console.print(
        Panel(
            f"[bold]{n_tools}[/bold] tools | "
            f"[bold]{n_prompts}[/bold] prompts | "
            f"[bold]{n_risks}[/bold] risks | "
            f"Framework: [cyan]{agent_map['metadata']['framework']}[/cyan] | "
            f"Language: [cyan]{conv_lang}[/cyan]",
            title="Summary",
            style="green",
        )
    )


if __name__ == "__main__":
    main()
