#!/usr/bin/env python3
"""
Full Pipeline Orchestrator (A → B → C → D → E)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Single command to run the entire agent debugging pipeline:
  Phase A: Analyze agent codebase → agent_map.json
  Phase B: Generate test suite    → test_suite.json
  Phase C: Execute tests          → test_run_report.json + failure_inbox.json
  Phase D: Diagnose failures      → diagnosis_report.json
  Phase E: Improve agent          → improvement outputs

Usage:
    # Full pipeline (offline, mock)
    python run_pipeline.py /path/to/agent --mock --skip-ai --test-count 20 --count 10

    # Stop after Phase C
    python run_pipeline.py /path/to/agent --mock --skip-ai --stop-after c

    # Resume from existing agent map
    python run_pipeline.py /path/to/agent --agent-map agent_map.json --mock --skip-ai

    # Resume from existing test suite
    python run_pipeline.py /path/to/agent --agent-map agent_map.json --test-suite test_suite.json --mock
"""

from __future__ import annotations

import asyncio
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
project_root = Path(__file__).parent
load_dotenv(project_root / ".env")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

console = Console()

PHASE_ORDER = ["a", "b", "c", "d", "cert", "e"]


def _should_run(phase: str, stop_after: str) -> bool:
    """Return True if this phase should run given the stop_after setting."""
    return PHASE_ORDER.index(phase) <= PHASE_ORDER.index(stop_after)


def _phase_banner(label: str, description: str):
    console.print()
    console.print(Panel(
        f"[bold]{label}[/bold]\n{description}",
        style="blue",
    ))


def _transition_panel(from_phase: str, to_phase: str, artifact: str, path: str):
    console.print()
    console.print(Panel(
        f"  [bold]{from_phase} → {to_phase}[/bold]\n"
        f"  Passing: [cyan]{artifact}[/cyan]\n"
        f"  Path:    [dim]{path}[/dim]",
        style="dim",
    ))


@click.command()
@click.argument("repo_path", type=click.Path(exists=True))
# General
@click.option("--output-dir", "-o", default="pipeline_output", help="Base output directory")
@click.option("--skip-ai", is_flag=True, help="Skip all AI calls (offline mode)")
@click.option("--language", "-l", default=None, help="Language for conversations")
@click.option("--seed", default=None, type=int, help="Random seed for reproducibility")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
# Phase A
@click.option("--agent-map", default=None, type=click.Path(exists=True), help="Skip Phase A; use existing agent_map.json")
@click.option("--prompt-encoding", default="utf-8", help="Encoding for prompt files in Phase A (default: utf-8)")
# Phase B
@click.option("--test-suite", default=None, type=click.Path(exists=True), help="Skip Phase B; use existing test_suite.json")
@click.option("--test-count", default=250, type=int, help="Target test cases for Phase B (default 250)")
@click.option("--persona-count", default=8, type=int, help="AI personas to generate (default 8)")
@click.option("--scenario-count", default=10, type=int, help="AI scenarios to generate (default 10)")
# Phase C
@click.option("--mock", is_flag=True, help="Use mock agent connector")
@click.option("--fail-rate", default=0.05, type=float, help="Mock agent failure rate (default 0.05)")
@click.option("--workers", "-w", default=10, type=int, help="Parallel workers")
@click.option("--count", "-c", default=0, type=int, help="Limit tests to execute (0=all)")
@click.option("--ai-personas", is_flag=True, help="Use AI for persona messages")
# Phase D
@click.option("--use-embeddings", is_flag=True, help="Use embeddings for clustering")
@click.option("--max-retries", default=3, type=int, help="API retry attempts")
@click.option("--backoff-base", default=2.0, type=float, help="Backoff base seconds")
@click.option("--backoff-max", default=60.0, type=float, help="Backoff max seconds")
# Phase E
@click.option("--apply-fixes", is_flag=True, help="Actually apply fixes (default dry run)")
@click.option("--baseline-fail-rate", default=0.05, type=float, help="Baseline fail rate for A/B")
@click.option("--fixed-fail-rate", default=0.01, type=float, help="Fixed fail rate for A/B")
@click.option("--smoke-limit", default=10, type=int, help="Smoke test limit")
@click.option("--full-limit", default=50, type=int, help="Full test limit")
# Validation
@click.option("--skip-validation", is_flag=True, help="Skip post-Phase C conversation validation")
# Control
@click.option("--stop-after", default="e", type=click.Choice(["a", "b", "c", "d", "cert", "e"], case_sensitive=False),
              help="Stop after this phase (default: e = run all)")
def main(
    repo_path: str,
    output_dir: str,
    skip_ai: bool,
    language: str | None,
    seed: int | None,
    verbose: bool,
    agent_map: str | None,
    prompt_encoding: str,
    test_suite: str | None,
    test_count: int,
    persona_count: int,
    scenario_count: int,
    mock: bool,
    fail_rate: float,
    workers: int,
    count: int,
    ai_personas: bool,
    use_embeddings: bool,
    max_retries: int,
    backoff_base: float,
    backoff_max: float,
    apply_fixes: bool,
    baseline_fail_rate: float,
    fixed_fail_rate: float,
    smoke_limit: int,
    full_limit: int,
    skip_validation: bool,
    stop_after: str,
):
    """Run the full A→B→C→D→E agent debugging pipeline."""
    import random as _random
    if seed is not None:
        _random.seed(seed)

    pipeline_start = time.time()
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    console.print(Panel(
        "[bold]Agent Debugger — Full Pipeline[/bold]\n"
        "A (Analyze) → B (Generate) → C (Execute) → D (Diagnose) → Cert → E (Improve)",
        style="bold blue",
    ))

    phases_to_run = [p for p in PHASE_ORDER if _should_run(p, stop_after)]
    skip_a = agent_map is not None
    skip_b = test_suite is not None

    summary_table = Table(title="Pipeline Configuration", show_lines=True)
    summary_table.add_column("Setting", style="cyan", min_width=18)
    summary_table.add_column("Value", min_width=30)
    summary_table.add_row("Repo path", repo_path)
    summary_table.add_row("Output dir", output_dir)
    summary_table.add_row("Phases", " → ".join(p.upper() for p in phases_to_run))
    summary_table.add_row("Phase A", f"[yellow]SKIP[/yellow] (using {agent_map})" if skip_a else "[green]RUN[/green]")
    summary_table.add_row("Phase B", f"[yellow]SKIP[/yellow] (using {test_suite})" if skip_b else "[green]RUN[/green]")
    summary_table.add_row("AI mode", "off (--skip-ai)" if skip_ai else "on")
    summary_table.add_row("Mock agent", "yes" if mock else "no")
    console.print(summary_table)

    # Track metrics per phase
    metrics: dict = {}

    # ─────────────────────────────────────────────────
    # Phase A: Analyze
    # ─────────────────────────────────────────────────
    agent_map_path: str
    agent_map_data: dict

    if skip_a:
        with open(agent_map) as f:
            agent_map_data = json.load(f)
        agent_map_path = agent_map
        console.print(f"\n[yellow]Phase A skipped — using {agent_map}[/yellow]")
    elif _should_run("a", stop_after):
        _phase_banner("Phase A: Agent Analysis", "Scan agent codebase → agent_map.json")

        from src.ingestion.ingestor import ingest_directory
        from src.analysis.static_analyzer import analyze_files
        from src.patterns.detector import detect_patterns
        from src.risk.analyzer import analyze_risks
        from src.graph.builder import generate_agent_map

        a_start = time.time()

        with console.status("[bold green]Scanning codebase..."):
            ingestion = ingest_directory(repo_path, language_filter="python")

        console.print(f"  Files found: [bold]{len(ingestion.files)}[/bold]")

        if not ingestion.files:
            console.print("[red]No relevant files found. Check your path.[/red]")
            raise SystemExit(1)

        with console.status("[bold green]Parsing with Tree-sitter..."):
            file_paths = [f.path for f in ingestion.files]
            all_symbols = analyze_files(file_paths)

        with console.status("[bold green]Detecting agent patterns..."):
            pattern_result = detect_patterns(
                all_symbols,
                ingestion.prompt_files,
                prompt_encoding=prompt_encoding,
            )

        with console.status("[bold green]Analyzing risks..."):
            risks, _taint_flows = analyze_risks(pattern_result.tools, pattern_result.prompts, all_symbols)

        ai_result = None
        if not skip_ai:
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if api_key:
                with console.status("[bold green]Running AI semantic analysis..."):
                    from src.ai_analyzer.analyzer import run_semantic_analysis
                    ai_result = run_semantic_analysis(
                        all_symbols=all_symbols,
                        tools=pattern_result.tools,
                        prompts=pattern_result.prompts,
                        entry_points=ingestion.entry_points,
                        framework=pattern_result.framework,
                    )

        with console.status("[bold green]Building Agent Map..."):
            agent_map_data = generate_agent_map(
                all_symbols=all_symbols,
                pattern_result=pattern_result,
                ai_result=ai_result,
                risks=risks,
                entry_points=ingestion.entry_points,
                root_path=ingestion.root_path,
                taint_flows=_taint_flows,
            )

        agent_map_path = str(out / "agent_map.json")
        with open(agent_map_path, "w") as f:
            json.dump(agent_map_data, f, indent=2, default=str)

        a_elapsed = time.time() - a_start
        n_tools = len(agent_map_data.get("components", {}).get("tools", []))
        metrics["a"] = {"tools": n_tools, "duration": f"{a_elapsed:.1f}s"}
        console.print(f"  [green]Phase A complete[/green] — {n_tools} tools, {a_elapsed:.1f}s")
        console.print(f"  Saved: [cyan]{agent_map_path}[/cyan]")

    if not _should_run("b", stop_after):
        _print_final_summary(metrics, pipeline_start)
        return

    # ─────────────────────────────────────────────────
    # Phase B: Generate Tests
    # ─────────────────────────────────────────────────
    test_suite_path: str
    test_suite_data: dict

    if skip_b:
        with open(test_suite) as f:
            test_suite_data = json.load(f)
        test_suite_path = test_suite
        console.print(f"\n[yellow]Phase B skipped — using {test_suite}[/yellow]")
    else:
        _transition_panel("Phase A", "Phase B", "agent_map.json", agent_map_path)
        _phase_banner("Phase B: Test Generation", "Coverage → Personas → Scenarios → Test Suite")

        from generate_tests import _run_phase_b, PhaseBUsageTracker

        b_start = time.time()
        gen_dir = out / "generated"
        phase_b_usage = (
            PhaseBUsageTracker()
            if not skip_ai and os.environ.get("ANTHROPIC_API_KEY")
            else None
        )

        test_suite_path = _run_phase_b(
            agent_map=agent_map_data,
            output_dir=gen_dir,
            skip_ai=skip_ai,
            count=test_count,
            persona_count=persona_count,
            scenario_count=scenario_count,
            variants=3,
            seed=seed,
            language=language,
            usage_tracker=phase_b_usage,
        )

        with open(test_suite_path) as f:
            test_suite_data = json.load(f)

        b_elapsed = time.time() - b_start
        n_tests = len(test_suite_data.get("test_cases", []))
        metrics["b"] = {"tests_generated": n_tests, "duration": f"{b_elapsed:.1f}s"}
        console.print(f"\n  [green]Phase B complete[/green] — {n_tests} tests, {b_elapsed:.1f}s")

    if not _should_run("c", stop_after):
        _print_final_summary(metrics, pipeline_start)
        return

    # ─────────────────────────────────────────────────
    # Phase C: Execute Tests
    # ─────────────────────────────────────────────────
    _transition_panel("Phase B", "Phase C", "test_suite.json", test_suite_path)
    _phase_banner("Phase C: Test Execution", "Execute test suite with live monitoring")

    from src.execution.agent_connector import MockAgentConnector, APIAgentConnector
    from src.execution.persona_context import analyze_persona_context, prompt_for_persona_context
    from src.execution.runner import TestExecutionEngine
    from src.execution.monitor import RealTimeMonitor
    from src.execution.aggregator import ResultsAggregator

    c_start = time.time()
    results_dir = out / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    # Detect language
    detected_language = language or agent_map_data.get("metadata", {}).get("conversation_language", "English")
    if detected_language.lower() in ("spanish", "español", "espanol", "es"):
        detected_language = "Spanish"
    elif detected_language.lower() in ("english", "en"):
        detected_language = "English"

    # Limit tests
    suite_for_exec = dict(test_suite_data)
    if count > 0:
        suite_for_exec["test_cases"] = suite_for_exec["test_cases"][:count]

    # Connector
    if mock:
        connector = MockAgentConnector(agent_map_data, fail_rate=fail_rate, tool_call_rate=0.4)
    else:
        connector = APIAgentConnector(agent_map_data)

    traces_dir = str(results_dir / "traces")

    # Optional context for personas (inline text or path to file)
    persona_context = prompt_for_persona_context()
    persona_context_analyzed = None
    if persona_context:
        console.print("[dim]Persona context loaded.[/dim]")
        if not skip_ai:
            sample_goal = None
            for tc in suite_for_exec.get("test_cases", [])[:1]:
                sample_goal = tc.get("scenario", {}).get("user_goal")
                break
            with console.status("[dim]Analyzing context for personas...[/dim]"):
                persona_context_analyzed = analyze_persona_context(persona_context, user_goal=sample_goal)
            if persona_context_analyzed:
                console.print("[dim]Context analyzed.[/dim]")

    # Run execution
    async def _run_phase_c():
        from datetime import datetime, timezone
        started_at = datetime.now(timezone.utc)

        engine = TestExecutionEngine(
            test_suite=suite_for_exec,
            agent_connector=connector,
            max_workers=workers,
            use_ai_personas=ai_personas,
            traces_dir=traces_dir,
            language=detected_language,
            persona_context=persona_context,
            persona_context_analyzed=persona_context_analyzed,
        )

        monitor_task = None
        monitor = RealTimeMonitor(
            total_tests=len(suite_for_exec["test_cases"]),
            console=console,
        )
        monitor_task = asyncio.create_task(monitor.monitor(engine.event_queue))

        results = await engine.run_all()

        if monitor_task:
            await monitor_task

        aggregator = ResultsAggregator(suite_for_exec, results)
        report = aggregator.save_report(results_dir / "test_run_report.json", started_at)
        inbox = aggregator.save_failure_inbox(results_dir / "failure_inbox.json")
        aggregator.save_passed_inbox(results_dir / "passed_inbox.json")
        return report, inbox, aggregator

    report, inbox, aggregator = asyncio.run(_run_phase_c())

    c_elapsed = time.time() - c_start
    metrics["c"] = {
        "total": report.total_tests,
        "passed": report.passed,
        "failed": report.failed,
        "pass_rate": f"{report.pass_rate:.1f}%",
        "duration": f"{c_elapsed:.1f}s",
    }
    console.print(f"\n  [green]Phase C complete[/green] — {report.passed}/{report.total_tests} passed ({report.pass_rate:.1f}%), {c_elapsed:.1f}s")

    # ─────────────────────────────────────────────────
    # Validation: Filter fake failures & catch fake successes
    # ─────────────────────────────────────────────────
    if not skip_validation and _should_run("d", stop_after):
        console.print()
        console.print(Panel(
            "[bold]Post-Phase C Validation[/bold]\n"
            "Filtering persona-induced failures, chaos artifacts, and catching false successes",
            style="yellow",
        ))

        v_start = time.time()

        def on_validation_progress(msg: str):
            console.print(f"  [dim]{msg}[/dim]")

        inbox, _, validation = aggregator.validate_and_save(
            results_dir=results_dir,
            agent_map=agent_map_data,
            use_ai=not skip_ai,
            retry_config={
                "max_retries": max_retries,
                "backoff_base": backoff_base,
            },
            on_progress=on_validation_progress,
        )

        v_elapsed = time.time() - v_start
        s = validation.summary
        console.print(
            f"  [green]Validation complete[/green] — "
            f"{s.get('genuine_failures', 0)} genuine failures, "
            f"{s.get('persona_incompetence_filtered', 0)} persona issues filtered, "
            f"{s.get('chaos_induced_filtered', 0)} chaos-induced filtered, "
            f"{s.get('false_successes_caught', 0)} false successes caught "
            f"[{v_elapsed:.1f}s]"
        )
        metrics["validation"] = {
            "genuine": s.get("genuine_failures", 0),
            "persona_filtered": s.get("persona_incompetence_filtered", 0),
            "chaos_filtered": s.get("chaos_induced_filtered", 0),
            "false_successes": s.get("false_successes_caught", 0),
            "duration": f"{v_elapsed:.1f}s",
        }

    if not _should_run("d", stop_after):
        _print_final_summary(metrics, pipeline_start)
        return

    # ─────────────────────────────────────────────────
    # Phase D: Diagnose Failures
    # ─────────────────────────────────────────────────
    total_failures = inbox.get("total_failures", 0)
    diag_dict = None

    if total_failures > 0:
        _transition_panel("Phase C", "Phase D", "failure_inbox.json", str(results_dir / "failure_inbox.json"))
        _phase_banner("Phase D: Diagnosis & Analysis", "Cluster failures, identify root causes, generate fixes")

        from src.diagnosis.engine import DiagnosisEngine

        d_start = time.time()

        def on_progress(msg: str):
            console.print(f"  [dim]{msg}[/dim]")

        diag_engine = DiagnosisEngine(
            use_ai=not skip_ai,
            use_embeddings=use_embeddings,
            on_progress=on_progress,
            max_retries=max_retries,
            backoff_base=backoff_base,
            backoff_max=backoff_max,
        )

        report_dict = report.model_dump(mode="json")
        diag_report = diag_engine.diagnose(inbox, report_dict, agent_map_data)
        diag_dict = diag_report.model_dump(mode="json")

        diag_path = results_dir / "diagnosis_report.json"
        with open(diag_path, "w") as f:
            json.dump(diag_dict, f, indent=2, default=str)

        d_elapsed = time.time() - d_start
        n_clusters = len(diag_dict.get("clusters", []))
        n_fixes = len(diag_dict.get("fix_proposals", []))
        metrics["d"] = {
            "clusters": n_clusters,
            "fix_proposals": n_fixes,
            "duration": f"{d_elapsed:.1f}s",
        }
        console.print(f"\n  [green]Phase D complete[/green] — {n_clusters} clusters, {n_fixes} fix proposals, {d_elapsed:.1f}s")
        console.print(f"  Saved: [cyan]{diag_path}[/cyan]")
    else:
        console.print("\n[green]No failures to diagnose — all tests passed![/green]")
        metrics["d"] = {"clusters": 0, "fix_proposals": 0, "duration": "0.0s"}

    if not _should_run("cert", stop_after):
        _print_final_summary(metrics, pipeline_start)
        return

    # ─────────────────────────────────────────────────
    # Certification Phase
    # ─────────────────────────────────────────────────
    _phase_banner("Certification", "Score agent across 5 categories and assign tier")

    from src.certification.engine import CertificationEngine

    cert_start = time.time()

    def on_cert_progress(msg: str):
        console.print(f"  [dim]{msg}[/dim]")

    cert_engine = CertificationEngine(on_progress=on_cert_progress)

    report_dict_for_cert = report.model_dump(mode="json")
    cert_result = cert_engine.run(
        results_dir=results_dir,
        test_run_report=report_dict_for_cert,
        diagnosis_report=diag_dict,
        agent_map=agent_map_data,
    )

    cert_elapsed = time.time() - cert_start
    tier = cert_result.get("tier", "not_certified")
    overall = cert_result.get("overall_score", 0)

    # Tier display styling
    tier_styles = {
        "platinum": "[bold white on blue] PLATINUM [/bold white on blue]",
        "gold": "[bold black on yellow] GOLD [/bold black on yellow]",
        "silver": "[bold black on white] SILVER [/bold black on white]",
        "not_certified": "[bold white on red] NOT CERTIFIED [/bold white on red]",
    }
    tier_display = tier_styles.get(tier, tier)

    # Category scores bar chart
    cat_lines = []
    for cs in cert_result.get("category_scores", []):
        bar_len = int(cs["score"] / 5)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        cat_lines.append(f"  {cs['category']:<25} {bar} {cs['score']:5.1f}/100 ({cs['weight']:.0%})")

    body = f"  Tier: {tier_display}  |  Overall Score: [bold]{overall:.1f}[/bold]/100\n\n"
    body += "\n".join(cat_lines)

    # Strengths
    strengths = cert_result.get("strengths", [])
    if strengths:
        body += "\n\n  [green]Strengths:[/green]"
        for s in strengths:
            body += f"\n    + {s}"

    # Improvements
    improvements = cert_result.get("improvements", [])
    if improvements:
        body += "\n\n  [yellow]Improvements:[/yellow]"
        for imp in improvements:
            body += f"\n    - {imp}"

    console.print(Panel(body, title="[bold]Certification Report[/bold]", style="cyan"))

    metrics["cert"] = {
        "tier": tier,
        "overall_score": overall,
        "duration": f"{cert_elapsed:.1f}s",
    }
    console.print(f"\n  [green]Certification complete[/green] — {tier.upper()} ({overall:.1f}/100), {cert_elapsed:.1f}s")

    if not _should_run("e", stop_after):
        _print_final_summary(metrics, pipeline_start)
        return

    # ─────────────────────────────────────────────────
    # Phase E: Improve Agent
    # ─────────────────────────────────────────────────
    if diag_dict and len(diag_dict.get("fix_proposals", [])) > 0:
        _transition_panel("Phase D", "Phase E", "diagnosis_report.json", str(results_dir / "diagnosis_report.json"))
        _phase_banner("Phase E: Improvement & Validation", "Apply fixes, A/B test, validate, regression tests")

        from src.improvement.engine import ImprovementEngine

        e_start = time.time()

        def on_progress_e(msg: str):
            console.print(f"  [dim]{msg}[/dim]")

        improve_engine = ImprovementEngine(
            agent_map=agent_map_data,
            agent_source_dir=Path(repo_path),
            test_suite=test_suite_data,
            diagnosis_report=diag_dict,
            dry_run=not apply_fixes,
            baseline_fail_rate=baseline_fail_rate,
            fixed_fail_rate=fixed_fail_rate,
            smoke_limit=smoke_limit,
            full_limit=full_limit,
            max_workers=workers,
            language=detected_language,
            on_progress=on_progress_e,
        )

        improve_dir = out / "improvement"
        improve_results = improve_engine.run(improve_dir)

        e_elapsed = time.time() - e_start
        imp_report = improve_results.get("improvement_report", {})
        metrics["e"] = {
            "fixes_applied": imp_report.get("successful_fixes", 0),
            "pass_rate_improvement": f"{imp_report.get('pass_rate_improvement', 0):+.1f} pp",
            "ready_to_deploy": imp_report.get("ready_to_deploy", False),
            "duration": f"{e_elapsed:.1f}s",
        }
        console.print(f"\n  [green]Phase E complete[/green] — {e_elapsed:.1f}s")
        console.print(f"  Saved: [cyan]{improve_dir}/[/cyan]")
    else:
        console.print("\n[green]No fix proposals — skipping Phase E.[/green]")
        metrics["e"] = {"fixes_applied": 0, "duration": "0.0s"}

    _print_final_summary(metrics, pipeline_start)


def _print_final_summary(metrics: dict, pipeline_start: float):
    """Print a summary panel with metrics from each phase that ran."""
    elapsed = time.time() - pipeline_start

    rows = []
    if "a" in metrics:
        m = metrics["a"]
        rows.append(f"  Phase A (Analyze):   {m.get('tools', '?')} tools detected  [{m['duration']}]")
    if "b" in metrics:
        m = metrics["b"]
        rows.append(f"  Phase B (Generate):  {m.get('tests_generated', '?')} tests generated  [{m['duration']}]")
    if "c" in metrics:
        m = metrics["c"]
        rows.append(f"  Phase C (Execute):   {m.get('passed', '?')}/{m.get('total', '?')} passed ({m.get('pass_rate', '?')})  [{m['duration']}]")
    if "validation" in metrics:
        m = metrics["validation"]
        rows.append(
            f"  Validation:          {m.get('genuine', '?')} genuine, "
            f"{m.get('persona_filtered', 0)}+{m.get('chaos_filtered', 0)} filtered, "
            f"{m.get('false_successes', 0)} false successes  [{m['duration']}]"
        )
    if "d" in metrics:
        m = metrics["d"]
        rows.append(f"  Phase D (Diagnose):  {m.get('clusters', '?')} clusters, {m.get('fix_proposals', '?')} fixes  [{m['duration']}]")
    if "cert" in metrics:
        m = metrics["cert"]
        rows.append(f"  Certification:       {m.get('tier', '?').upper()} ({m.get('overall_score', '?')}/100)  [{m['duration']}]")
    if "e" in metrics:
        m = metrics["e"]
        rows.append(f"  Phase E (Improve):   {m.get('fixes_applied', '?')} fixes, {m.get('pass_rate_improvement', '?')}  [{m['duration']}]")

    body = "\n".join(rows) if rows else "  No phases completed"
    body += f"\n\n  Total time: [bold]{elapsed:.1f}s[/bold]"

    console.print()
    console.print(Panel(
        body,
        title="[bold green]Pipeline Summary[/bold green]",
        style="green",
    ))


if __name__ == "__main__":
    main()
