#!/usr/bin/env python3
"""
Test Generation CLI (Unified Phase B)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Single entry point that runs B1→B2→B3→B4 in sequence:
  1. Coverage goals & sandbox config  (coverage_builder)
  2. Persona library                  (persona_builder)
  3. Scenario catalog                 (scenario_builder)
  4. Test suite generation            (testsuite_builder)

Usage:
    # Offline (no API key needed)
    python generate_tests.py agent_map.json --skip-ai --count 20

    # With AI enrichment
    python generate_tests.py agent_map.json --count 250 --persona-count 8 --scenario-count 10

    # Custom output directory
    python generate_tests.py agent_map.json --skip-ai --output-dir my_tests/
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
project_root = Path(__file__).parent
load_dotenv(project_root / ".env")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.coverage.calculator import build_test_configuration
from src.personas.builder import PersonaBuilder
from src.personas.models import PersonaLibrary
from src.scenarios.library import ScenarioLibrary
from src.scenarios.models import ScenarioCatalog
from src.coverage.models import TestConfiguration
from src.generator.test_suite import TestSuiteGenerator

console = Console()

# Pricing per 1M tokens (Claude Haiku 4.5, approximate as of 2025)
_PHASE_B_PRICING = {"claude-haiku-4-5": {"input": 1.00, "output": 5.00}}


class PhaseBUsageTracker:
    """Tracks token usage and cost for Phase B AI calls."""

    def __init__(self, model: str = "claude-haiku-4-5", llm_config=None):
        self.model = model
        self.input_tokens = 0
        self.output_tokens = 0
        self._llm_config = llm_config

    def add(self, usage) -> None:
        """Record one API response usage (object with input_tokens, output_tokens)."""
        self.input_tokens += getattr(usage, "input_tokens", 0) or 0
        self.output_tokens += getattr(usage, "output_tokens", 0) or 0

    def add_tokens(self, input_tokens: int, output_tokens: int) -> None:
        """Record raw token counts from LLMProviderConfig.call_sync()."""
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens

    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def cost_usd(self) -> float:
        if self._llm_config:
            return self._llm_config.cost_for_tokens(self.input_tokens, self.output_tokens)
        prices = _PHASE_B_PRICING.get(self.model, _PHASE_B_PRICING["claude-haiku-4-5"])
        return (self.input_tokens / 1_000_000 * prices["input"]) + (
            self.output_tokens / 1_000_000 * prices["output"]
        )


def _run_phase_b(
    agent_map: dict,
    output_dir: Path,
    skip_ai: bool,
    count: int,
    persona_count: int,
    scenario_count: int,
    variants: int,
    seed: int | None,
    language: str | None,
    use_tlahuac: bool = False,
    tlahuac_endpoint: str = "http://localhost:8000",
    tlahuac_personas: list[str] | None = None,
    tlahuac_dir: str | None = None,
    usage_tracker: PhaseBUsageTracker | None = None,
    include_templates: bool = False,
    llm_config=None,
    use_traces: bool = False,
    traces_file: str | None = None,
) -> str:
    """Run all four Phase B sub-steps. Returns path to test_suite.json."""
    import random as _random
    if seed is not None:
        _random.seed(seed)

    output_dir.mkdir(parents=True, exist_ok=True)
    if llm_config and not llm_config.needs_api_key:
        has_api_key = True  # local provider (e.g. Ollama) — no key needed
    elif llm_config:
        has_api_key = bool(llm_config.resolved_api_key)
    else:
        has_api_key = bool(os.environ.get("ANTHROPIC_API_KEY"))

    if llm_config:
        console.print(f"  LLM provider: [cyan]{llm_config.display_name()}[/cyan]  has_api_key={has_api_key}")
    else:
        console.print(f"  LLM provider: [cyan]anthropic (default)[/cyan]  has_api_key={has_api_key}")

    # Offline runs cannot generate AI scenarios; fall back to the built-in
    # template personas/scenarios so --skip-ai always yields a usable suite.
    if (skip_ai or not has_api_key) and not include_templates and not use_tlahuac:
        include_templates = True
        console.print("  [yellow]Offline mode: enabling built-in template personas and scenarios[/yellow]")

    # Resolve language: explicit flag > agent_map metadata > default English
    if language:
        detected_language = language
    else:
        detected_language = agent_map.get("metadata", {}).get("conversation_language", "English")
    # Normalize
    if detected_language.lower() in ("spanish", "español", "espanol", "es"):
        detected_language = "Spanish"
    elif detected_language.lower() in ("english", "en"):
        detected_language = "English"

    # ── B3: Coverage goals & sandbox config ──
    console.print(Panel(
        "[bold]Step 1/4: Coverage Configuration[/bold]\n"
        "Calculate coverage goals and sandbox config from agent map",
        style="blue",
    ))

    with console.status("[bold green]Building test configuration..."):
        config = build_test_configuration(agent_map)

    config_path = output_dir / "test_configuration.json"
    with open(config_path, "w") as f:
        json.dump(config.model_dump(), f, indent=2, default=str)

    tool_count = len(config.coverage_goals.tool_coverage.min_invocations_per_tool)
    combo_count = len(config.coverage_goals.tool_coverage.tool_combinations)
    # Sprint E3: interaction & transition coverage summary
    ca_count = len(config.coverage_goals.tool_coverage.covering_array)
    tcov = config.coverage_goals.transition_coverage
    transition_count = len(tcov.all_transitions) if tcov else 0
    console.print(
        f"  [green]Done[/green] — {tool_count} tools, "
        f"{combo_count} combos, {ca_count} covering-array rows, "
        f"{transition_count} FSM transitions → [cyan]{config_path}[/cyan]"
    )

    # ── B1: Persona library ──
    console.print()
    console.print(Panel(
        "[bold]Step 2/4: Persona Library[/bold]\n"
        "Generate synthetic user personas for testing",
        style="blue",
    ))

    builder = PersonaBuilder(
        agent_map, language=detected_language, usage_tracker=usage_tracker,
        llm_config=llm_config,
    )

    # Resolve tlahuac data directory (used for both personas and scenarios)
    data_dir = tlahuac_dir
    if use_tlahuac and not data_dir:
        auto_dir = Path(__file__).parent.parent / "tlahuac_simulator_agent"
        if auto_dir.exists():
            data_dir = str(auto_dir)

    # When using tlahuac, skip template personas (use only tlahuac personas)
    if not use_tlahuac and include_templates:
        with console.status("[bold green]Loading persona templates..."):
            builder.load_templates()

    # External persona pack (tlahuac or custom directory)
    if use_tlahuac:
        if data_dir:
            try:
                with console.status("[bold green]Loading tlahuac personas from disk..."):
                    tlahuac_list = builder.load_from_external(
                        data_dir=data_dir,
                        selected_ids=tlahuac_personas,
                    )
                console.print(f"  Loaded [green]{len(tlahuac_list)}[/green] tlahuac personas from [cyan]{data_dir}[/cyan]")
            except Exception as e:
                console.print(f"  [red]Failed to load tlahuac personas: {e}[/red]")
                console.print("  [yellow]Continuing with template personas only[/yellow]")
        else:
            # Fallback: try API endpoint
            try:
                with console.status("[bold green]Loading tlahuac personas from API..."):
                    tlahuac_list = builder.load_from_provider(
                        endpoint=tlahuac_endpoint,
                        provider_name="tlahuac",
                        selected_ids=tlahuac_personas,
                    )
                console.print(f"  Loaded [green]{len(tlahuac_list)}[/green] tlahuac personas from API")
            except Exception as e:
                console.print(f"  [red]Failed to load tlahuac personas: {e}[/red]")
                console.print("  [yellow]Continuing with template personas only[/yellow]")

    # Tool-attack personas (one per tool from agent_map)
    tool_attack_personas = builder.generate_tool_attack_personas()
    if tool_attack_personas:
        console.print(f"  Generated [green]{len(tool_attack_personas)}[/green] tool-attack personas")

    # Flow-attack personas (one per tool chain from agent_map)
    tool_chains = agent_map.get("tool_chains", [])
    if tool_chains:
        flow_attack_personas = builder.generate_flow_attack_personas(tool_chains)
        console.print(f"  Generated [green]{len(flow_attack_personas)}[/green] flow-attack personas")

    # Adversarial personas (one per OWASP/ASI taxonomy category present in
    # risk_flags — Sprint E5). Fully offline; used by Phase 2.5 adversarial
    # coverage to pair each risk-guided attack scenario with an attacker.
    from src.scenarios.adversarial import present_taxonomy_ids as _present_tax_ids
    _adv_tax_ids = _present_tax_ids(agent_map)
    if _adv_tax_ids:
        adversarial_personas = builder.generate_adversarial_personas(_adv_tax_ids)
        console.print(
            f"  Generated [green]{len(adversarial_personas)}[/green] adversarial personas "
            f"for taxonomy: [cyan]{', '.join(_adv_tax_ids)}[/cyan]"
        )

    # Production-grounded personas (Sprint E6): fit the 10-trait and style
    # distributions to real production conversations and sample a matching
    # persona population (source="production_grounded"). Fully offline — reads
    # --traces-file or the agent map's embedded trace_analysis; degrades
    # gracefully to no personas when no traced conversations are available.
    if use_traces:
        from src.scenarios.seed_corpus import load_trace_result as _load_traces_e6

        _trace_result_e6 = _load_traces_e6(traces_file=traces_file, agent_map=agent_map)
        _e6_conversations = (
            (_trace_result_e6.get("conversations")
             if isinstance(_trace_result_e6, dict)
             else getattr(_trace_result_e6, "conversations", None))
            if _trace_result_e6 else None
        ) or []
        if _e6_conversations:
            production_personas = builder.generate_production_grounded_personas(
                _trace_result_e6, count=5,
            )
            console.print(
                f"  Generated [green]{len(production_personas)}[/green] "
                f"production-grounded personas from [green]{len(_e6_conversations)}[/green] "
                f"traced conversations"
            )
        else:
            console.print(
                "  [dim]No traced conversations available — skipping "
                "production-grounded personas[/dim]"
            )

    # AI-generated personas (skip when using tlahuac-only mode)
    if use_tlahuac:
        console.print("  [dim]AI persona generation skipped (tlahuac-only mode)[/dim]")
    elif persona_count > 0 and not skip_ai and has_api_key:
        with console.status(f"[bold green]Generating {persona_count} AI personas..."):
            builder.generate_personas(count=persona_count)
        console.print(f"  Generated [green]{persona_count}[/green] AI personas")
    elif persona_count > 0 and (skip_ai or not has_api_key):
        reason = "--skip-ai" if skip_ai else "ANTHROPIC_API_KEY not set"
        console.print(f"  [yellow]AI persona generation skipped ({reason})[/yellow]")

    library = builder.export_library()
    persona_path = output_dir / "persona_library.json"
    with open(persona_path, "w") as f:
        json.dump(library.model_dump(), f, indent=2, default=str)

    console.print(
        f"  [green]Done[/green] — {len(builder.personas)} personas → [cyan]{persona_path}[/cyan]"
    )

    # Sprint E7: report quality-diversity coverage (MAP-Elites archive) next to
    # the classic trait-bucket diversity score.
    _div = builder.report_diversity()
    console.print(
        f"  Diversity: trait score [green]{_div.get('diversity_score', 0.0):.3f}[/green], "
        f"MAP-Elites coverage [green]{_div.get('map_elites_coverage', 0.0):.3f}[/green] "
        f"([cyan]{_div.get('map_elites_cells_filled', 0)}[/cyan]/"
        f"{_div.get('map_elites_cells_total', 0)} behavioural cells)"
    )

    # ── B2: Scenario catalog ──
    console.print()
    console.print(Panel(
        "[bold]Step 3/4: Scenario Catalog[/bold]\n"
        "Create test scenarios for agent testing",
        style="blue",
    ))

    scenario_lib = ScenarioLibrary(
        agent_map, language=detected_language, usage_tracker=usage_tracker,
        llm_config=llm_config,
    )
    if include_templates:
        with console.status("[bold green]Loading scenario templates..."):
            scenario_lib.load_templates()

    # External scenario loading (tlahuac)
    if use_tlahuac and data_dir:
        try:
            with console.status("[bold green]Loading tlahuac scenarios..."):
                tlahuac_scenarios = scenario_lib.load_from_external(data_dir=data_dir)
            console.print(f"  Loaded [green]{len(tlahuac_scenarios)}[/green] tlahuac scenarios with Spanish openers")
        except Exception as e:
            console.print(f"  [yellow]Could not load tlahuac scenarios: {e}[/yellow]")

    # Production-failure seed corpus (Sprint E1): convert real failure
    # traces into seed scenarios + mutated neighbours. Fully offline —
    # reads --traces-file or the agent map's embedded trace_analysis.
    # Phase A trace analysis, when available, is reused by the B4 APFD
    # prioritiser (Sprint E8) to weight tests by the operational profile.
    trace_result = None
    if use_traces:
        from src.scenarios.seed_corpus import load_trace_result

        trace_result = load_trace_result(traces_file=traces_file, agent_map=agent_map)
        if trace_result is None:
            console.print(
                "  [yellow]No trace data available (no --traces-file and no "
                "trace_analysis in agent map) — skipping production seeds[/yellow]"
            )
        else:
            failure_patterns = (
                trace_result.get("failure_patterns")
                if isinstance(trace_result, dict)
                else getattr(trace_result, "failure_patterns", None)
            ) or []
            n_conversations = len(
                (trace_result.get("conversations")
                 if isinstance(trace_result, dict)
                 else getattr(trace_result, "conversations", None)) or []
            )
            with console.status("[bold green]Loading production-failure seeds..."):
                seed_scenarios = scenario_lib.load_production_seeds(trace_result, agent_map)
            console.print(
                f"  Production seeds: [green]{len(seed_scenarios)}[/green] scenarios from "
                f"[green]{len(failure_patterns)}[/green] failure patterns and "
                f"[green]{n_conversations}[/green] traced conversations"
            )

    # Policy-graph scenarios (Sprint E2): IntellAgent-style weighted random
    # walks over the guardrail policy graph. Graph construction and walk
    # sampling are fully offline; user-goal naturalisation uses the LLM
    # only when AI mode is on. Maps without guardrails skip this step.
    _guardrails = agent_map.get("guardrails") or {}
    if _guardrails.get("total_rules", 0) > 0 or _guardrails.get("rules"):
        with console.status("[bold green]Generating policy-graph scenarios..."):
            policy_scenarios = scenario_lib.generate_policy_graph_scenarios(
                count=min(scenario_count, 15),
                naturalise=(not skip_ai and has_api_key),
            )
        console.print(
            f"  Policy-graph scenarios: [green]{len(policy_scenarios)}[/green] "
            f"from [green]{len(_guardrails.get('rules', []) or [])}[/green] guardrail rules"
        )

    # Guardrail compliance/violation test pairs (Sprint E11): one compliance
    # + one-or-more violation-provocation tests per numbered rule, scaled by
    # complexity, with condition-met/not-met and language-mismatch handling.
    # Structural generation and oracle attachment are fully offline; only the
    # provocation naturalisation uses the LLM. Maps without guardrails no-op.
    if _guardrails.get("total_rules", 0) > 0 or _guardrails.get("rules"):
        with console.status("[bold green]Generating guardrail test pairs..."):
            guardrail_scenarios = scenario_lib.generate_guardrail_pairs(
                naturalise=(not skip_ai and has_api_key),
            )
        console.print(
            f"  Guardrail test pairs: [green]{len(guardrail_scenarios)}[/green] "
            f"from [green]{len(_guardrails.get('rules', []) or [])}[/green] guardrail rules"
        )

    # AI-generated scenarios
    if scenario_count > 0 and not skip_ai and has_api_key:
        with console.status(f"[bold green]Generating {scenario_count} AI scenarios..."):
            actual = scenario_lib.generate_scenarios(count=scenario_count)
        console.print(f"  Generated [green]{len(actual)}[/green] AI scenarios")
    elif scenario_count > 0 and (skip_ai or not has_api_key):
        reason = "--skip-ai" if skip_ai else "ANTHROPIC_API_KEY not set"
        console.print(f"  [yellow]AI scenario generation skipped ({reason})[/yellow]")

    # Variant expansion
    if variants > 0:
        bases = [s for s in scenario_lib.scenarios if s.base_scenario_id is None]
        total_variants = 0
        if skip_ai or not has_api_key:
            for base in bases:
                v = scenario_lib.generate_offline_variants(base)
                total_variants += len(v)
        else:
            for base in bases:
                with console.status(f"[green]  Generating variants for {base.title}..."):
                    v = scenario_lib.generate_variants(base, count=variants)
                total_variants += len(v)
        console.print(f"  Variants generated: [green]{total_variants}[/green]")

    # Non-LLM oracle attachment (Sprint E4): derive deterministic
    # success/failure checks from Phase A postconditions, guardrails,
    # taint flows, side effects, and dependency edges — no LLM judge.
    with console.status("[bold green]Attaching non-LLM oracles..."):
        oracle_counts = scenario_lib.attach_oracles(agent_map)
    console.print(
        f"  Oracles attached: [green]{oracle_counts['oracles']}[/green] "
        f"(+ [green]{oracle_counts['metamorphic_relations']}[/green] metamorphic relations)"
    )

    # Risk-guided adversarial scenarios (Sprint E5): taint-flow leakage
    # probes and taxonomy-mapped attacks (OWASP LLM01/LLM02/LLM06,
    # ASI03/ASI05) derived from risk_flags. Generated AFTER attach_oracles
    # so each attack keeps its own deterministic TAINT_FLOW /
    # GUARDRAIL_VIOLATION oracle. Fully offline — no LLM required.
    with console.status("[bold green]Generating risk-guided adversarial scenarios..."):
        adversarial_scenarios = scenario_lib.generate_adversarial_scenarios(agent_map)
    if adversarial_scenarios:
        _adv_tags = sorted({
            t for s in adversarial_scenarios for t in s.tags
            if t[:3] in ("LLM", "ASI")
        })
        console.print(
            f"  Adversarial scenarios: [green]{len(adversarial_scenarios)}[/green] "
            f"covering [cyan]{', '.join(_adv_tags) or 'n/a'}[/cyan]"
        )

    catalog = scenario_lib.export_catalog()
    scenario_path = output_dir / "scenario_catalog.json"
    with open(scenario_path, "w") as f:
        json.dump(catalog.model_dump(), f, indent=2, default=str)

    console.print(
        f"  [green]Done[/green] — {catalog.total_scenarios_count} scenarios → [cyan]{scenario_path}[/cyan]"
    )

    # ── B4: Test suite generation ──
    console.print()
    console.print(Panel(
        "[bold]Step 4/4: Test Suite Generation[/bold]\n"
        "Combine personas, scenarios, and coverage goals into executable tests",
        style="blue",
    ))

    with console.status(f"[bold green]Generating {count} test cases..."):
        generator = TestSuiteGenerator(
            agent_map=agent_map,
            personas=library.personas,
            scenarios=catalog.scenarios,
            coverage_goals=config.coverage_goals,
            sandbox_config=config.sandbox_config,
            trace_result=trace_result,
        )
        suite = generator.generate(target_count=count)

    suite_path = output_dir / "test_suite.json"
    with open(suite_path, "w") as f:
        json.dump(suite.model_dump(), f, indent=2, default=str)

    console.print(
        f"  [green]Done[/green] — {suite.summary.total_tests} test cases → [cyan]{suite_path}[/cyan]"
    )

    # Sprint E8: estimated APFD of the prioritised ordering (proxy for real
    # faults, computed over the static potential-fault matrix). Offline; the
    # full --evaluate harness reports the same metric with more detail.
    try:
        from src.evaluation.apfd import calculate_apfd
        from src.evaluation.harness import build_fault_matrix

        _order = [tc.test_id for tc in sorted(suite.test_cases, key=lambda t: t.test_number)]
        _apfd = calculate_apfd(_order, build_fault_matrix(suite))
        console.print(f"  Estimated APFD (prioritised order): [green]{_apfd:.4f}[/green]")
    except Exception as _e:  # never let reporting break generation
        console.print(f"  [yellow]APFD reporting skipped: {_e}[/yellow]")

    # Phase B token/cost summary (when AI was used)
    if usage_tracker and usage_tracker.total_tokens() > 0:
        tbl = Table(title="Phase B API usage (tokens & cost)")
        tbl.add_column("Metric", style="cyan")
        tbl.add_column("Value", justify="right")
        tbl.add_row("Input tokens", f"{usage_tracker.input_tokens:,}")
        tbl.add_row("Output tokens", f"{usage_tracker.output_tokens:,}")
        tbl.add_row("Total tokens", f"{usage_tracker.total_tokens():,}")
        tbl.add_row("Estimated cost (USD)", f"${usage_tracker.cost_usd():.4f}")
        console.print()
        console.print(tbl)

    return str(suite_path)


@click.command()
@click.argument("agent_map_file", type=click.Path(exists=True))
@click.option("--output-dir", "-o", default="generated", help="Output directory for all generated files")
@click.option("--skip-ai", is_flag=True, help="Skip all AI generation (offline mode)")
@click.option("--count", "-c", default=150, type=int, help="Target number of test cases (default 150)")
@click.option("--persona-count", default=8, type=int, help="Number of AI-generated personas (default 8)")
@click.option("--scenario-count", default=10, type=int, help="Number of AI-generated scenarios (default 10)")
@click.option("--variants", default=3, type=int, help="Variants per base scenario (default 3)")
@click.option("--seed", default=None, type=int, help="Random seed for reproducibility")
@click.option("--language", "-l", default=None, help="Language for generated content")
@click.option("--use-tlahuac", is_flag=True, help="Load personas and scenarios from tlahuac data (auto-detects sibling directory or uses --tlahuac-dir)")
@click.option("--tlahuac-dir", default=None, type=click.Path(exists=True), help="Path to tlahuac persona pack directory (default: auto-detect ../tlahuac_simulator_agent)")
@click.option("--tlahuac-endpoint", default="http://localhost:8000", help="Tlahuac API endpoint (fallback if no directory found)")
@click.option("--tlahuac-personas", multiple=True, help="Specific tlahuac persona IDs to load (repeatable)")
@click.option("--include-templates", is_flag=True, help="Include built-in template personas and scenarios (required for offline --skip-ai runs)")
@click.option("--evaluate", is_flag=True, help="Run the suite-quality measurement harness after generation and save evaluation_report.json")
@click.option("--use-traces", is_flag=True, help="Seed scenarios from production failure traces (reads --traces-file or the agent map's trace_analysis; offline, no Langfuse credentials needed)")
@click.option("--traces-file", default=None, type=click.Path(exists=True), help="JSON file with production trace data ({conversations, failure_patterns} or a list of conversations)")
def main(
    agent_map_file: str,
    output_dir: str,
    skip_ai: bool,
    count: int,
    persona_count: int,
    scenario_count: int,
    variants: int,
    seed: int | None,
    language: str | None,
    use_tlahuac: bool,
    tlahuac_dir: str | None,
    tlahuac_endpoint: str,
    tlahuac_personas: tuple,
    include_templates: bool,
    evaluate: bool,
    use_traces: bool,
    traces_file: str | None,
):
    """Run unified Phase B: generate test suite from agent map (B1→B2→B3→B4)."""
    start = time.time()

    console.print(Panel(
        "[bold]Phase B: Test Generation Pipeline[/bold]\n"
        "Coverage → Personas → Scenarios → Test Suite",
        style="blue",
    ))

    # Load agent map
    with open(agent_map_file) as f:
        agent_map = json.load(f)

    agent_type = agent_map.get("metadata", {}).get("type", "custom")
    console.print(f"  Agent type:    [cyan]{agent_type}[/cyan]")
    console.print(f"  Output dir:    [cyan]{output_dir}[/cyan]")
    console.print(f"  Target tests:  [bold]{count}[/bold]")
    console.print(f"  AI mode:       [bold]{'off' if skip_ai else 'on'}[/bold]")
    console.print()

    usage_tracker = (
        PhaseBUsageTracker() if not skip_ai and os.environ.get("ANTHROPIC_API_KEY") else None
    )
    suite_path = _run_phase_b(
        agent_map=agent_map,
        output_dir=Path(output_dir),
        skip_ai=skip_ai,
        count=count,
        persona_count=persona_count,
        scenario_count=scenario_count,
        variants=variants,
        seed=seed,
        language=language,
        use_tlahuac=use_tlahuac,
        tlahuac_endpoint=tlahuac_endpoint,
        tlahuac_personas=list(tlahuac_personas) if tlahuac_personas else None,
        tlahuac_dir=tlahuac_dir,
        usage_tracker=usage_tracker,
        include_templates=include_templates,
        use_traces=use_traces,
        traces_file=traces_file,
    )

    # ── Optional: suite-quality measurement harness (Sprint E12) ──
    if evaluate:
        from src.evaluation.harness import evaluate_suite
        from src.generator.models import TestSuite

        console.print()
        console.print(Panel(
            "[bold]Evaluation: Suite-Quality Measurement Harness[/bold]\n"
            "APFD, diversity, taxonomy coverage, predictive validity, mutants",
            style="blue",
        ))

        with open(suite_path) as f:
            suite = TestSuite.model_validate(json.load(f))

        with console.status("[bold green]Evaluating test suite..."):
            report = evaluate_suite(suite, agent_map)

        report_path = Path(output_dir) / "evaluation_report.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, default=str)

        tbl = Table(title="Suite quality report")
        tbl.add_column("Metric", style="cyan")
        tbl.add_column("Value", justify="right")
        tbl.add_row("APFD (potential faults)", f"{report['apfd']['apfd']:.4f}")
        tbl.add_row("Weighted APFD", f"{report['apfd']['weighted_apfd']:.4f}")
        tbl.add_row("Potential faults", str(report["apfd"]["n_potential_faults"]))
        tbl.add_row("Overall diversity", f"{report['diversity']['overall_diversity']:.4f}")
        tbl.add_row("Tool-pair coverage", f"{report['diversity']['tool_pair_coverage']:.4f}")
        tbl.add_row("Taxonomy coverage", f"{report['taxonomy_coverage']['coverage']:.4f}")
        pv = report["predictive_validity"]
        if pv is not None:
            tbl.add_row("Precision vs production", f"{pv['precision']:.4f}")
            tbl.add_row("Recall vs production", f"{pv['recall']:.4f}")
            tbl.add_row("F1 vs production", f"{pv['f1']:.4f}")
        else:
            tbl.add_row("Predictive validity", "[dim]n/a (no production signals)[/dim]")
        tbl.add_row("Mutants generated", str(report["mutation"]["total_mutants"]))
        console.print(tbl)
        console.print(f"  [green]Saved[/green] → [cyan]{report_path}[/cyan]")

    elapsed = time.time() - start

    # Final summary
    console.print()
    console.print(Panel(
        f"  Test configuration: [cyan]{output_dir}/test_configuration.json[/cyan]\n"
        f"  Persona library:    [cyan]{output_dir}/persona_library.json[/cyan]\n"
        f"  Scenario catalog:   [cyan]{output_dir}/scenario_catalog.json[/cyan]\n"
        f"  Test suite:         [cyan]{suite_path}[/cyan]",
        title="[bold green]Phase B Complete[/bold green]",
        style="green",
    ))
    console.print(f"[dim]{elapsed:.1f}s[/dim]")


if __name__ == "__main__":
    main()
