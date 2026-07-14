#!/usr/bin/env python3
"""
Run the RQ1-RQ4 predictive-validity experiments.

Examples:

    # Full offline run on the production export (static targeting mode)
    python3 run_experiments.py \
        --export ../docs/tech_repair-conversations-export.json \
        --agent-map tech_repair_whatsapp_map.json \
        --budget 100

    # Closed-loop run: execute both arms against the sandbox bridge
    python3 sandbox_bridge.py serve --agent-map tech_repair_whatsapp_map.json --port 8099 &
    python3 run_experiments.py --export ... --agent-map ... \
        --mode execute --connector http://localhost:8099
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv(Path(__file__).parent / ".env")

from src.experiments import ExperimentConfig, run_experiment

console = Console()


@click.command()
@click.option("--export", "export_path", required=True,
              type=click.Path(exists=True), help="Production conversation export JSON")
@click.option("--agent-map", "agent_map_path", required=True,
              type=click.Path(exists=True), help="Phase A agent map for the agent under test")
@click.option("--output-dir", default=None,
              help="Output directory (default experiments_output/<timestamp>)")
@click.option("--budget", default=100, show_default=True, help="Tests per arm")
@click.option("--holdout-fraction", default=0.3, show_default=True,
              help="Chronological fraction of failures held out for measurement")
@click.option("--min-score", default=3.0, show_default=True,
              help="Structured failure-score threshold for ground truth")
@click.option("--per-category-cap", default=25, show_default=True,
              help="Max seeds per failure category in the feedback corpus")
@click.option("--seed", "rng_seed", default=42, show_default=True, help="RNG seed")
@click.option("--mode", type=click.Choice(["static", "execute"]), default="static",
              show_default=True,
              help="static = pre-execution targeting; execute = run suites against an agent")
@click.option("--connector", default="mock", show_default=True,
              help="execute mode: 'mock' or a sandbox bridge URL (http://...)")
@click.option("--language", default=None, help="Conversation language override")
@click.option("--seed-budget-fraction", default=0.35, show_default=True,
              help="Feedback arm: fraction of budget reserved for seed reproductions")
@click.option("--arms", default="blind,feedback", show_default=True,
              help="Comma-separated arms: blind|template, feedback, naive_llm, gan "
                   "(LLM arms need ANTHROPIC_API_KEY)")
def main(export_path, agent_map_path, output_dir, budget, holdout_fraction,
         min_score, per_category_cap, rng_seed, mode, connector, language,
         seed_budget_fraction, arms):
    """Answer RQ1-RQ4: predictive validity, coverage gaps, feedback value,
    and recall-per-budget — grounded in real production failures."""
    if output_dir is None:
        output_dir = f"experiments_output/{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    console.print(Panel(
        "[bold]Predictive-Validity Experiments (RQ1-RQ4)[/bold]\n"
        "Ground truth from human-process signals → blind vs feedback arms → "
        "measurement over the frozen shared taxonomy",
        style="blue",
    ))

    config = ExperimentConfig(
        export_path=export_path,
        agent_map_path=agent_map_path,
        output_dir=output_dir,
        budget=budget,
        holdout_fraction=holdout_fraction,
        min_score=min_score,
        per_category_cap=per_category_cap,
        rng_seed=rng_seed,
        mode=mode,
        connector=connector,
        language=language,
        seed_budget_fraction=seed_budget_fraction,
        arms=[a.strip() for a in arms.split(",") if a.strip()],
    )

    results = run_experiment(config, on_progress=lambda msg: console.print(f"  {msg}"))

    # ---- Summary ----
    rq1 = results["rq1_predictive_validity"]
    table = Table(title="Headline results")
    table.add_column("Question")
    table.add_column("Answer")
    table.add_row(
        "RQ1 predictive validity",
        f"recall {rq1['overall']['recall']:.3f} "
        f"(CI {rq1['recall_ci']['ci_low']:.3f}-{rq1['recall_ci']['ci_high']:.3f}), "
        f"precision {rq1['overall']['precision']:.3f}",
    )
    gaps = results["rq2_coverage_gaps"]["gaps"]
    table.add_row(
        "RQ2 coverage gaps",
        ", ".join(g["category"] for g in gaps) or "none below threshold",
    )
    rq3 = results["rq3_production_feedback"]
    if rq3.get("available"):
        t = next(iter(rq3["comparison"]["tests"].values()))
        arms = rq3["comparison"]["arms"]
        table.add_row(
            "RQ3 feedback vs blind (held-out)",
            f"blind {arms['blind']['recall']:.3f} → feedback {arms['feedback']['recall']:.3f} "
            f"(Δ {t['delta']:+.3f}, p={t['p_value']:.4f})",
        )
    table.add_row("RQ4 ranking", " > ".join(results["rq4_recall_vs_budget"]["ranking"]))
    console.print(table)

    console.print(f"\n[green]Artefacts:[/green] {output_dir}/results.json, REPORT.md, charts/")


if __name__ == "__main__":
    main()
