#!/usr/bin/env python3
"""
Test Execution CLI (Phase C)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Execute a test suite against an agent, with live monitoring,
trace collection, and failure-inbox generation.

Usage:
    # Mock mode (no real agent needed — for pipeline testing)
    python execute_tests.py test_suite.json agent_map.json --mock

    # Mock with AI personas
    python execute_tests.py test_suite.json agent_map.json --mock --ai-personas

    # Against a real API endpoint
    python execute_tests.py test_suite.json agent_map.json

    # Custom options
    python execute_tests.py test_suite.json agent_map.json --mock --workers 5 --count 50 -o results/
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import click
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.endpoints_config import apply_endpoints_to_agent_map
from src.execution.agent_connector import APIAgentConnector, MockAgentConnector, VictoriaConnector
from src.execution.aggregator import ResultsAggregator
from src.execution.monitor import RealTimeMonitor
from src.execution.persona_context import analyze_persona_context, prompt_for_persona_context
from src.execution.runner import TestExecutionEngine

console = Console()


def _print_pre_run_summary(test_suite: dict, agent_map: dict, opts: dict):
    agent_type = agent_map.get("metadata", {}).get("type", "custom")
    total = len(test_suite.get("test_cases", []))

    table = Table(title="Execution Plan", show_lines=True)
    table.add_column("Setting", style="cyan", min_width=20)
    table.add_column("Value", min_width=30)

    table.add_row("Agent type", agent_type)
    table.add_row("Test cases", str(total))
    table.add_row("Workers", str(opts["workers"]))
    table.add_row("Connector", opts["connector"])
    table.add_row("AI personas", "yes" if opts["ai_personas"] else "no (offline)")
    table.add_row("Persona model", opts.get("persona_model", "anthropic/claude-haiku-4-5"))
    table.add_row("GAN mode", opts.get("gan_label", "off"))
    if opts.get("gan_label", "off") != "off":
        table.add_row("Critic model", opts.get("critic_model_label", ""))
    table.add_row("Language", opts.get("language", "English"))
    table.add_row("Traces", opts["traces_dir"] or "disabled")
    table.add_row("Output dir", str(opts["output_dir"]))
    table.add_row("Persona context", "yes" if opts.get("persona_context") else "no")

    console.print(table)


def _print_final_report(report, inbox, output_dir):
    console.print()

    # Summary panel
    pass_style = "green" if report.pass_rate >= 80 else "yellow" if report.pass_rate >= 50 else "red"
    console.print(Panel(
        f"  Total tests:   [bold]{report.total_tests}[/bold]\n"
        f"  Passed:        [green]{report.passed}[/green]\n"
        f"  Failed:        [red]{report.failed}[/red]\n"
        f"  Errors:        [yellow]{report.errors}[/yellow]\n"
        f"  Timeouts:      [magenta]{report.timeouts}[/magenta]\n"
        f"  Pass rate:     [{pass_style}]{report.pass_rate:.1f}%[/{pass_style}]\n"
        f"\n"
        f"  Duration:      [bold]{report.total_duration_sec:.1f}s[/bold]  (avg {report.avg_duration_sec:.2f}s/test)\n"
        f"  Cost:          [bold]${report.total_cost_usd:.3f}[/bold]\n"
        f"  Tool coverage: [bold]{report.coverage_pct:.1f}%[/bold]  ({len(report.tools_not_covered)} tools missed)",
        title="[bold]Test Run Results[/bold]",
        style="green" if report.pass_rate >= 80 else "yellow",
    ))

    # Difficulty breakdown
    if report.by_difficulty:
        table = Table(title="By Difficulty", show_lines=True)
        table.add_column("Difficulty", style="cyan")
        table.add_column("Passed", style="green", justify="center")
        table.add_column("Failed", style="red", justify="center")
        table.add_column("Error", style="yellow", justify="center")
        table.add_column("Timeout", style="magenta", justify="center")

        for diff in ["easy", "medium", "hard"]:
            counts = report.by_difficulty.get(diff, {})
            if counts:
                table.add_row(
                    diff,
                    str(counts.get("passed", 0)),
                    str(counts.get("failed", 0)),
                    str(counts.get("error", 0)),
                    str(counts.get("timeout", 0)),
                )
        console.print(table)

    # Failure inbox
    total_failures = inbox.get("total_failures", 0)
    if total_failures > 0:
        console.print(f"\n[bold red]Failure inbox: {total_failures} failures[/bold red]")
        top = inbox.get("failures", [])[:5]
        for f in top:
            console.print(
                f"  [dim]#{f['test_number']}[/dim] "
                f"[cyan]{f['scenario'][:35]}[/cyan] → "
                f"[red]{(f.get('failure_reason') or f['status'])[:50]}[/red]"
            )
        if total_failures > 5:
            console.print(f"  [dim]... and {total_failures - 5} more[/dim]")

    # Output files
    console.print(f"\n[bold green]Output files:[/bold green]")
    console.print(f"  Report:        [cyan]{output_dir}/test_run_report.json[/cyan]")
    console.print(f"  Failure inbox: [cyan]{output_dir}/failure_inbox.json[/cyan]")


@click.command()
@click.argument("test_suite_file", type=click.Path(exists=True))
@click.argument("agent_map_file", type=click.Path(exists=True))
@click.option("--output", "-o", default="results", help="Output directory")
@click.option("--workers", "-w", default=10, type=int, help="Max parallel workers")
@click.option("--count", "-c", default=0, type=int, help="Limit to first N tests (0=all)")
@click.option("--mock", is_flag=True, help="Use mock agent connector (no real agent needed)")
@click.option("--ai-personas", is_flag=True, help="Use AI for persona messages (costs $)")
@click.option("--traces/--no-traces", default=True, help="Save per-test trace files")
@click.option("--no-monitor", is_flag=True, help="Disable live Rich terminal dashboard")
@click.option("--ui", is_flag=True, help="Launch browser-based live dashboard at http://localhost:8080")
@click.option("--ui-port", default=8080, type=int, help="Port for web dashboard (default: 8080)")
@click.option("--fail-rate", default=0.05, type=float, help="Mock agent failure rate")
@click.option("--seed", default=None, type=int, help="Random seed for reproducibility")
@click.option("--language", "-l", default=None, help="Language for persona messages (English, Spanish, etc.). Auto-detects from agent_map if not specified.")
@click.option("--diagnose", is_flag=True, help="Run Phase D diagnosis after test execution (if failures > 0)")
@click.option("--skip-ai", is_flag=True, help="Skip AI in diagnosis (offline heuristics only)")
@click.option("--use-embeddings", is_flag=True, help="Use embeddings for diagnosis clustering")
@click.option("--max-retries", default=3, type=int, help="Max retries for AI API calls (default 3)")
@click.option("--backoff-base", default=2.0, type=float, help="Exponential backoff base in seconds (default 2.0)")
@click.option("--backoff-max", default=60.0, type=float, help="Maximum backoff delay in seconds (default 60.0)")
@click.option("--ai-workers", default=1, type=int, help="Parallel AI workers for diagnosis (default 1)")
@click.option("--improve", is_flag=True, help="Run Phase E improvement after diagnosis (implies --diagnose)")
@click.option("--apply-fixes", is_flag=True, help="Actually apply fixes in Phase E (default is dry run)")
@click.option("--baseline-fail-rate", default=0.05, type=float, help="Baseline mock fail rate for A/B test (default 0.05)")
@click.option("--fixed-fail-rate", default=0.01, type=float, help="Fixed mock fail rate for A/B test (default 0.01)")
@click.option("--smoke-limit", default=10, type=int, help="Max tests for Phase E smoke test (default 10)")
@click.option("--full-limit", default=50, type=int, help="Max tests for Phase E full test (default 50)")
@click.option("--gan", is_flag=True, help="Enable GAN-style testing: Generator + Critic agents. Cost: ~2x LLM calls per test; worst case ~6x with restarts.")
@click.option("--critic-model", default="claude-haiku-4-5", help="Model for the Critic agent (default: Haiku)")
@click.option("--max-restarts", default=2, type=int, help="Max conversation restarts by Critic (default 2)")
@click.option("--quality-threshold", default=3.0, type=float, help="Minimum quality score 0-10 to avoid restart (default 3.0)")
@click.option("--evaluate-every", default=2, type=int, help="Critic evaluates every N agent turns (default 2). Lower = more LLM calls.")
@click.option("--persona-provider", default="anthropic", help="LLM provider for persona messages: anthropic (default), groq, together, fireworks, openai, custom")
@click.option("--persona-model", "persona_model_opt", default=None, help="Model override for persona (default: provider's cheapest model)")
@click.option("--persona-api-key", default=None, help="API key for persona provider (or set GROQ_API_KEY / TOGETHER_API_KEY / etc. env var)")
@click.option("--persona-base-url", default=None, help="Base URL for custom OpenAI-compatible persona provider")
@click.option("--critic-provider", default="anthropic", help="LLM provider for Critic agent: anthropic (default), groq, together, fireworks, openai, custom")
@click.option("--critic-api-key", default=None, help="API key for critic provider")
@click.option("--critic-base-url", default=None, help="Base URL for custom critic provider")
def main(
    test_suite_file: str,
    agent_map_file: str,
    output: str,
    workers: int,
    count: int,
    mock: bool,
    ai_personas: bool,
    traces: bool,
    no_monitor: bool,
    ui: bool,
    ui_port: int,
    fail_rate: float,
    seed: int | None,
    language: str | None,
    diagnose: bool,
    skip_ai: bool,
    use_embeddings: bool,
    max_retries: int,
    backoff_base: float,
    backoff_max: float,
    ai_workers: int,
    improve: bool,
    apply_fixes: bool,
    baseline_fail_rate: float,
    fixed_fail_rate: float,
    smoke_limit: int,
    full_limit: int,
    gan: bool,
    critic_model: str,
    max_restarts: int,
    quality_threshold: float,
    evaluate_every: int,
    persona_provider: str,
    persona_model_opt: str | None,
    persona_api_key: str | None,
    persona_base_url: str | None,
    critic_provider: str,
    critic_api_key: str | None,
    critic_base_url: str | None,
):
    """Execute a test suite against an agent."""
    import random as _random
    if seed is not None:
        _random.seed(seed)

    # Build LLM provider configs for persona generator and critic agent.
    from src.execution.llm_config import LLMProviderConfig
    persona_config = LLMProviderConfig(
        provider=persona_provider,
        model=persona_model_opt or None,
        api_key=persona_api_key or None,
        base_url=persona_base_url or None,
    )
    critic_config = LLMProviderConfig(
        provider=critic_provider,
        model=critic_model if critic_model != "claude-haiku-4-5" else None,
        api_key=critic_api_key or None,
        base_url=critic_base_url or None,
    )

    # --improve implies --diagnose
    if improve:
        diagnose = True

    console.print(Panel(
        "[bold]Phase C: Test Execution Engine[/bold]\n"
        "Execute test suite with live monitoring and trace collection",
        style="blue",
    ))

    # Load inputs
    with open(test_suite_file) as f:
        test_suite_full = json.load(f)
    with open(agent_map_file) as f:
        agent_map = json.load(f)

    # Resolve api_endpoint from agent_endpoints.json if not in agent_map
    apply_endpoints_to_agent_map(agent_map, agent_map_file)

    # Detect language: CLI flag > agent_map > default English
    if language:
        detected_language = language
    else:
        detected_language = agent_map.get("metadata", {}).get("conversation_language", "English")

    # Normalize language name
    if detected_language.lower() in ("spanish", "español", "espanol", "es"):
        detected_language = "Spanish"
    elif detected_language.lower() in ("english", "en"):
        detected_language = "English"

    # Limit test count (keep full suite for Phase E)
    # Ensure test_cases exists in the loaded file
    if "test_cases" not in test_suite_full:
        raise ValueError(f"test_suite.json missing 'test_cases' key. Found keys: {list(test_suite_full.keys())}")
    
    test_suite = dict(test_suite_full)
    if count > 0:
        test_suite["test_cases"] = test_suite_full["test_cases"][:count]
    # test_cases should already be in test_suite from dict() copy, but ensure it's there
    if "test_cases" not in test_suite:
        test_suite["test_cases"] = test_suite_full["test_cases"]

    # Output dir
    output_dir = Path(output)
    output_dir.mkdir(parents=True, exist_ok=True)
    traces_dir = str(output_dir / "traces") if traces else None

    # Optional context for personas (inline text or path to file)
    persona_context = prompt_for_persona_context()
    persona_context_analyzed = None
    if persona_context:
        console.print("[dim]Persona context loaded.[/dim]")
        # Analyze context once so personas understand it (any domain); skip if --skip-ai
        if not skip_ai:
            sample_goal = None
            for tc in test_suite.get("test_cases", [])[:1]:
                sample_goal = tc.get("scenario", {}).get("user_goal")
                break
            with console.status("[dim]Analyzing context for personas...[/dim]"):
                persona_context_analyzed = analyze_persona_context(persona_context, user_goal=sample_goal)
            if persona_context_analyzed:
                console.print("[dim]Context analyzed.[/dim]")

    # Connector
    if mock:
        connector = MockAgentConnector(
            agent_map,
            fail_rate=fail_rate,
            tool_call_rate=0.4,
            language=detected_language,
        )
        connector_label = f"mock (fail_rate={fail_rate})"
    else:
        # Check if this is a Victoria agent (custom framework)
        framework = agent_map.get("metadata", {}).get("framework", "")
        agent_type = agent_map.get("metadata", {}).get("type", "")
        
        # Use Victoria connector if it's Victoria or if api_endpoint contains "victoria"
        api_endpoint = agent_map.get("api_endpoint") or agent_map.get("metadata", {}).get("api_endpoint", "")
        is_victoria = (
            "victoria" in api_endpoint.lower() or
            (framework == "custom" and agent_type == "sales") or
            "victoria" in str(agent_map.get("metadata", {}).get("name", "")).lower()
        )
        
        if is_victoria:
            connector = VictoriaConnector(agent_map)
            connector_label = f"Victoria ({connector.base_endpoint})"
        else:
            connector = APIAgentConnector(agent_map)
            connector_label = f"API ({agent_map.get('api_endpoint', 'N/A')})"

    opts = {
        "workers": workers,
        "connector": connector_label,
        "ai_personas": ai_personas,
        "persona_model": persona_config.display_name() if ai_personas else "n/a (offline)",
        "gan_label": f"Generator + Critic" if gan else "off",
        "critic_model_label": critic_config.display_name() if gan else "",
        "traces_dir": traces_dir,
        "output_dir": output_dir,
        "language": detected_language,
        "persona_context": persona_context,
        "persona_context_analyzed": persona_context_analyzed,
    }

    _print_pre_run_summary(test_suite, agent_map, opts)
    console.print()

    # Run
    # GAN mode display
    if gan:
        console.print("[bold magenta]GAN mode enabled[/bold magenta]: Generator + Critic (adversarial self-correction)")
        console.print(f"  Critic model: {critic_model} | Max restarts: {max_restarts} | Quality threshold: {quality_threshold} | Evaluate every: {evaluate_every} turns")
        console.print()

    asyncio.run(_run_async(
        test_suite=test_suite,
        test_suite_full=test_suite_full,
        agent_map=agent_map,
        connector=connector,
        workers=workers,
        ai_personas=ai_personas,
        traces_dir=traces_dir,
        output_dir=output_dir,
        show_monitor=not no_monitor,
        show_ui=ui,
        ui_port=ui_port,
        language=detected_language,
        persona_context=persona_context,
        persona_context_analyzed=persona_context_analyzed,
        diagnose=diagnose,
        skip_ai=skip_ai,
        use_embeddings=use_embeddings,
        max_retries=max_retries,
        backoff_base=backoff_base,
        backoff_max=backoff_max,
        ai_workers=ai_workers,
        improve=improve,
        apply_fixes=apply_fixes,
        baseline_fail_rate=baseline_fail_rate,
        fixed_fail_rate=fixed_fail_rate,
        smoke_limit=smoke_limit,
        full_limit=full_limit,
        use_gan=gan,
        critic_model=critic_model,
        max_restarts=max_restarts,
        quality_threshold=quality_threshold,
        evaluate_every=evaluate_every,
        persona_config=persona_config,
        critic_config=critic_config,
    ))


async def _run_async(
    test_suite: dict,
    test_suite_full: dict,
    agent_map: dict,
    connector,
    workers: int,
    ai_personas: bool,
    traces_dir: str | None,
    output_dir: Path,
    show_monitor: bool,
    show_ui: bool = False,
    ui_port: int = 8080,
    language: str = "English",
    persona_context: str | None = None,
    persona_context_analyzed: dict | None = None,
    diagnose: bool = False,
    skip_ai: bool = False,
    use_embeddings: bool = False,
    max_retries: int = 3,
    backoff_base: float = 2.0,
    backoff_max: float = 60.0,
    ai_workers: int = 1,
    improve: bool = False,
    apply_fixes: bool = False,
    baseline_fail_rate: float = 0.05,
    fixed_fail_rate: float = 0.01,
    smoke_limit: int = 10,
    full_limit: int = 50,
    use_gan: bool = False,
    critic_model: str = "claude-haiku-4-5",
    max_restarts: int = 2,
    quality_threshold: float = 3.0,
    evaluate_every: int = 2,
    persona_config=None,
    critic_config=None,
):
    started_at = datetime.now(timezone.utc)

    # Conversation log file for real-time viewing — truncate so only current run shows
    conversation_log_file = str(output_dir / "conversations.log")
    Path(conversation_log_file).write_text("")
    
    engine = TestExecutionEngine(
        test_suite=test_suite,
        agent_connector=connector,
        max_workers=workers,
        use_ai_personas=ai_personas,
        traces_dir=traces_dir,
        language=language,
        conversation_log_file=conversation_log_file,
        agent_map=agent_map,
        persona_context=persona_context,
        persona_context_analyzed=persona_context_analyzed,
        use_gan=use_gan,
        critic_model=critic_model,
        max_restarts=max_restarts,
        quality_threshold=quality_threshold,
        evaluate_every=evaluate_every,
        persona_config=persona_config,
        critic_config=critic_config,
    )

    # Monitor task (Rich terminal)
    monitor_task = None
    if show_monitor and not show_ui:
        monitor = RealTimeMonitor(
            total_tests=len(test_suite["test_cases"]),
            console=console,
        )
        monitor_task = asyncio.create_task(monitor.monitor(engine.event_queue))

    # Web UI task
    ui_task = None
    if show_ui:
        from src.monitor_ui.server import MonitorUIServer

        tool_names = [t.get("name", "") for t in agent_map.get("components", {}).get("tools", [])]
        agent_name = agent_map.get("metadata", {}).get("name", agent_map.get("agent_id", ""))

        ui_server = MonitorUIServer(
            port=ui_port,
            report_file=str(output_dir / "test_run_report.json"),
        )
        console.print(f"[bold cyan]Dashboard running at http://localhost:{ui_port}[/bold cyan]")
        ui_task = asyncio.create_task(
            ui_server.start_integrated(
                engine_queue=engine.event_queue,
                agent_name=agent_name,
                tools=tool_names,
            )
        )

    # Execute
    results = await engine.run_all()

    # Wait for monitor to finish
    if monitor_task:
        await monitor_task

    # Wait briefly for UI to broadcast final events, but don't block
    if ui_task:
        try:
            await asyncio.wait_for(ui_task, timeout=3.0)
        except (asyncio.TimeoutError, Exception):
            pass

    # Aggregate
    console.print("\n[bold]Generating reports...[/bold]")
    aggregator = ResultsAggregator(test_suite, results)
    report = aggregator.save_report(output_dir / "test_run_report.json", started_at)
    inbox = aggregator.save_failure_inbox(output_dir / "failure_inbox.json")

    _print_final_report(report, inbox, output_dir)

    # Phase D: Diagnosis (if requested and there are failures)
    total_failures = inbox.get("total_failures", 0)
    if diagnose and total_failures > 0:
        console.print()
        console.print(Panel(
            "[bold]Phase D: Diagnosis & Analysis[/bold]\n"
            "Cluster failures, identify root causes, generate fixes",
            style="blue",
        ))
        console.print(f"  Failures to analyze: [bold]{total_failures}[/bold]")
        console.print(f"  AI analysis:         [bold]{'off' if skip_ai else 'on'}[/bold]")
        console.print()

        from src.diagnosis.engine import DiagnosisEngine
        from diagnose_failures import (
            _print_clusters,
            _print_fix_proposals,
            _print_priority_ranking,
            _print_reproductions,
            _print_summary,
        )

        def on_progress(msg: str):
            console.print(f"  [dim]{msg}[/dim]")

        diag_engine = DiagnosisEngine(
            use_ai=not skip_ai,
            use_embeddings=use_embeddings,
            on_progress=on_progress,
            max_retries=max_retries,
            backoff_base=backoff_base,
            backoff_max=backoff_max,
            ai_workers=ai_workers,
        )

        report_dict = report.model_dump(mode="json")
        diag_report = diag_engine.diagnose(inbox, report_dict, agent_map)

        console.print()
        _print_clusters(diag_report)
        console.print()
        _print_fix_proposals(diag_report)
        _print_priority_ranking(diag_report)
        _print_reproductions(diag_report)
        console.print()
        _print_summary(diag_report)

        # Save diagnosis report
        diag_path = output_dir / "diagnosis_report.json"
        diag_dict = diag_report.model_dump(mode="json")
        with open(diag_path, "w") as f:
            json.dump(diag_dict, f, indent=2, default=str)

        console.print(f"\n[bold green]Diagnosis report saved to {diag_path}[/bold green]")

        # Phase E: Improvement (if requested and fix proposals exist)
        fix_proposals = diag_dict.get("fix_proposals", [])
        if improve and len(fix_proposals) > 0:
            console.print()
            console.print(Panel(
                "[bold]Phase E: Improvement & Validation[/bold]\n"
                "Apply fixes, A/B test, validate, generate regression tests",
                style="blue",
            ))
            console.print(f"  Fixes to apply: [bold]{len(fix_proposals)}[/bold]")
            console.print(f"  Mode:           [bold]{'APPLY' if apply_fixes else 'DRY RUN'}[/bold]")
            console.print(f"  A/B testing:    baseline={baseline_fail_rate:.0%} fail → fixed={fixed_fail_rate:.0%} fail")
            console.print()

            from src.improvement.engine import ImprovementEngine
            from improve_agent import (
                _print_applied_fixes,
                _print_ab_results,
                _print_improvement_summary,
            )

            improve_engine = ImprovementEngine(
                agent_map=agent_map,
                agent_source_dir=Path("."),
                test_suite=test_suite_full,
                diagnosis_report=diag_dict,
                dry_run=not apply_fixes,
                baseline_fail_rate=baseline_fail_rate,
                fixed_fail_rate=fixed_fail_rate,
                smoke_limit=smoke_limit,
                full_limit=full_limit,
                max_workers=workers,
                language=language,
                on_progress=on_progress,
            )

            improve_dir = output_dir / "improvement"
            improve_results = await improve_engine.run_async(improve_dir)

            console.print()
            _print_applied_fixes(improve_results["applied_fixes"])
            console.print()
            _print_ab_results(improve_results["ab_test_runs"])
            console.print()
            _print_improvement_summary(improve_results["improvement_report"])

            # Regression tests
            reg_count = len(improve_results.get("regression_tests", []))
            if reg_count > 0:
                console.print(f"\n[bold]Regression tests generated: {reg_count}[/bold]")

            # Deployment package
            pkg = improve_results.get("deployment_package")
            if pkg:
                console.print(f"\n[bold green]Deployment package: {improve_dir / 'deployment'}[/bold green]")

            console.print(f"\n[bold green]Improvement outputs saved to {improve_dir}/[/bold green]")

        elif improve and len(fix_proposals) == 0:
            console.print("\n[green]No fix proposals to apply — skipping Phase E.[/green]")

    elif diagnose and total_failures == 0:
        console.print("\n[green]No failures to diagnose — all tests passed![/green]")


if __name__ == "__main__":
    main()
