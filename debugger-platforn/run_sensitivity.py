#!/usr/bin/env python3
"""
Sensitivity sweep for the RQ3 result: vary min_score, holdout_fraction, and
the RNG seed one at a time and check the feedback-vs-blind delta survives.

    python3 run_sensitivity.py \
        --export ../docs/tech_repair-conversations-anonymized.json \
        --agent-map tech_repair_whatsapp_map.json
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

load_dotenv(Path(__file__).parent / ".env")

from src.experiments import ExperimentConfig
from src.experiments.sensitivity import run_sensitivity

console = Console()


@click.command()
@click.option("--export", "export_path", required=True, type=click.Path(exists=True))
@click.option("--agent-map", "agent_map_path", required=True, type=click.Path(exists=True))
@click.option("--output-dir", default=None)
@click.option("--budget", default=100, show_default=True)
@click.option("--min-score", default=3.0, show_default=True)
@click.option("--holdout-fraction", default=0.3, show_default=True)
@click.option("--seed", "rng_seed", default=42, show_default=True)
def main(export_path, agent_map_path, output_dir, budget, min_score,
         holdout_fraction, rng_seed):
    """Check RQ3 robustness across analysis-parameter choices."""
    if output_dir is None:
        output_dir = f"experiments_output/sensitivity_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    console.print(Panel(
        "[bold]Sensitivity Analysis[/bold]\n"
        "min_score ∈ {2,3,4,5} · holdout ∈ {0.2,0.3,0.4} · seeds 41–45 "
        "(one at a time, static mode, blind vs feedback)",
        style="blue",
    ))

    base = ExperimentConfig(
        export_path=export_path,
        agent_map_path=agent_map_path,
        output_dir=output_dir,
        budget=budget,
        min_score=min_score,
        holdout_fraction=holdout_fraction,
        rng_seed=rng_seed,
    )
    summary = run_sensitivity(base, output_dir=output_dir,
                              on_progress=lambda m: console.print(f"  {m}"))

    verdict = "[green]ROBUST[/green]" if summary["robust"] else "[yellow]NOT UNIFORMLY ROBUST[/yellow]"
    console.print(
        f"\n{verdict} — Δ positive in {summary['n_delta_positive']}/{summary['n_configurations']}, "
        f"significant in {summary['n_significant']}/{summary['n_configurations']}, "
        f"Δ range {summary['delta_range'][0]:+.3f}…{summary['delta_range'][1]:+.3f}, "
        f"max p {summary['max_p_value']:.4f}"
    )
    console.print(f"[green]Artefacts:[/green] {output_dir}/sensitivity.json, SENSITIVITY.md, sensitivity_deltas.png")


if __name__ == "__main__":
    main()
