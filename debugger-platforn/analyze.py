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
            modifier = "[red]state-modifying[/red]" if t.state_modifying else "[green]read-only[/green]"
            leaf = tree.add(f"[cyan]{t.name}[/cyan] ({t.source}) {modifier}")
            leaf.add(f"[dim]{desc}[/dim]")
            if t.preconditions:
                leaf.add(f"[dim]Preconditions: {len(t.preconditions)}[/dim]")
            if t.side_effects:
                leaf.add(f"[dim]Side-effects: {', '.join(t.side_effects[:3])}[/dim]")
        console.print(tree)
        n_state = sum(1 for t in pattern_result.tools if t.state_modifying)
        n_readonly = len(pattern_result.tools) - n_state
        n_with_pre = sum(1 for t in pattern_result.tools if t.preconditions)
        console.print(f"  [dim]{n_state} state-modifying, {n_readonly} read-only, "
                      f"{n_with_pre} with preconditions[/dim]")
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
    table.add_column("Taxonomy", style="magenta")
    table.add_column("Description")

    for r in risks:
        severity_style = {
            "low": "green", "medium": "yellow",
            "high": "red", "critical": "bold red",
        }.get(r.severity, "white")
        taxonomy_str = ", ".join(r.taxonomy_ids) if r.taxonomy_ids else "-"
        table.add_row(
            r.tool or "-",
            r.risk_type,
            f"[{severity_style}]{r.severity}[/{severity_style}]",
            taxonomy_str,
            r.description[:70],
        )
    console.print(table)

    # Show taxonomy summary
    taxonomy_counts: dict[str, tuple[int, str]] = {}
    for r in risks:
        for tid, tname in zip(r.taxonomy_ids, r.taxonomy_names):
            if tid not in taxonomy_counts:
                taxonomy_counts[tid] = (0, tname)
            taxonomy_counts[tid] = (taxonomy_counts[tid][0] + 1, tname)

    if taxonomy_counts:
        tax_table = Table(title="Risk Taxonomy Summary")
        tax_table.add_column("ID", style="magenta")
        tax_table.add_column("Name", style="cyan")
        tax_table.add_column("Count", style="yellow", justify="right")
        for tid, (count, name) in sorted(taxonomy_counts.items()):
            tax_table.add_row(tid, name, str(count))
        console.print(tax_table)


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
@click.option("--context-budget", default=80_000, type=int, help="Max chars for AI context (default: 80000)")
@click.option("--use-traces", is_flag=True, help="Ingest Langfuse traces for dynamic analysis")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def main(
    repo_path: str,
    output: str | None,
    skip_ai: bool,
    language: str | None,
    prompt_encoding: str,
    context_budget: int,
    use_traces: bool,
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
        risks, taint_flows = analyze_risks(pattern_result.tools, pattern_result.prompts, all_symbols)
    _print_risk_summary(risks)
    if taint_flows:
        console.print(f"\n[bold]Taint flows detected:[/bold] {len(taint_flows)}")
        for tf in taint_flows[:10]:
            pii = f" [{', '.join(tf.data_types)}]" if tf.data_types else ""
            console.print(f"  - {tf.source.description} → {tf.sink.description}{pii} ({tf.risk_level})")

    # ── Step 4.5: Trace Ingestion (optional) ──
    trace_result = None
    if use_traces:
        with console.status("[bold green]Ingesting Langfuse traces..."):
            from src.traces.langfuse_client import LangfuseTraceIngester
            from src.traces.trace_parser import parse_trace_detail
            from src.traces.sequence_miner import mine_tool_sequences

            ingester = LangfuseTraceIngester()
            if ingester.available:
                raw_traces = ingester.fetch_traces(limit=500)
                trace_details = []
                for rt in raw_traces:
                    detail = ingester.fetch_trace_detail(rt["id"])
                    if detail:
                        trace_details.append(detail)
                from src.traces.trace_parser import parse_langfuse_traces
                conversations = parse_langfuse_traces(trace_details)
                tool_names = [t.name for t in pattern_result.tools]
                trace_result = mine_tool_sequences(conversations, tool_names)
                console.print(f"\n[bold]Traces:[/bold] {len(conversations)} conversations, "
                              f"{len(trace_result.tool_frequency)} unique tools observed")
                if trace_result.tools_not_in_static:
                    console.print(f"  [yellow]Tools in traces but not in static: "
                                  f"{', '.join(trace_result.tools_not_in_static)}[/yellow]")
                if len(conversations) < 50:
                    console.print("  [dim]Warning: <50 conversations — trace patterns may not be statistically meaningful[/dim]")
            else:
                console.print("[yellow]Langfuse credentials not set — skipping trace ingestion.[/yellow]")

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
                    context_budget=context_budget,
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
            taint_flows=taint_flows,
            trace_result=trace_result,
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

    # Guardrail summary
    guardrails = agent_map.get("guardrails", {})
    n_rules = guardrails.get("total_rules", 0)
    if n_rules > 0:
        by_cat = guardrails.get("by_category", {})
        cat_parts = [f"{v} {k}" for k, v in sorted(by_cat.items())]
        console.print(f"\n[bold]Guardrail rules:[/bold] {n_rules} "
                      f"(complexity: {guardrails.get('total_complexity', 0)})")
        if cat_parts:
            console.print(f"  [dim]{', '.join(cat_parts)}[/dim]")
        if not guardrails.get("guardrail_language_matches_conversation", True):
            console.print(
                f"  [yellow]⚠ Language mismatch: guardrails in "
                f"{guardrails.get('guardrail_language', '?')} but conversation in "
                f"{agent_map['metadata'].get('conversation_language', '?')}[/yellow]"
            )

    # Behavioural model summary
    bm = agent_map.get("behavioural_model", {})
    dep_graph = bm.get("dependency_graph", {})
    n_edges = len(dep_graph.get("edges", []))
    if n_edges > 0:
        props = dep_graph.get("properties", {})
        parts = [f"{n_edges} dependency edges"]
        if props.get("bottleneck_tools"):
            parts.append(f"bottlenecks: {', '.join(props['bottleneck_tools'][:3])}")
        if props.get("circular_dependencies"):
            parts.append(f"[red]{len(props['circular_dependencies'])} circular deps[/red]")
        if props.get("longest_chain"):
            parts.append(f"longest chain: {len(props['longest_chain'])} tools")
        if props.get("orphan_tools"):
            parts.append(f"{len(props['orphan_tools'])} orphan tools")
        console.print(f"\n[bold]Behavioural model:[/bold] {', '.join(parts)}")
    fsm = bm.get("fsm")
    if fsm and fsm.get("states"):
        console.print(f"  [dim]FSM: {len(fsm['states'])} states, "
                      f"{len(fsm.get('transitions', []))} transitions[/dim]")

    # Quick summary
    n_tools = len(agent_map["components"]["tools"])
    n_risks = len(agent_map["risk_flags"]["all_risks"])
    n_prompts = len(agent_map["components"]["prompts"])
    conv_lang = agent_map["metadata"].get("conversation_language", "English")
    console.print(
        Panel(
            f"[bold]{n_tools}[/bold] tools | "
            f"[bold]{n_prompts}[/bold] prompts | "
            f"[bold]{n_rules}[/bold] rules | "
            f"[bold]{n_risks}[/bold] risks | "
            f"Framework: [cyan]{agent_map['metadata']['framework']}[/cyan] | "
            f"Language: [cyan]{conv_lang}[/cyan]",
            title="Summary",
            style="green",
        )
    )


if __name__ == "__main__":
    main()
