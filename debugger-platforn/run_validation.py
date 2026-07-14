#!/usr/bin/env python3
"""
Ground-truth validation workflow.

    # 1. Build the blind annotation packet (50 conversations)
    python3 run_validation.py sample \
        --export ../docs/tech_repair-conversations-anonymized.json \
        --output-dir validation_packet

    # 2a. HUMAN annotation (the number the dissertation reports)
    python3 run_validation.py annotate --packet validation_packet

    # 2b. LLM pilot annotation (preliminary check ONLY)
    python3 run_validation.py llm-annotate --packet validation_packet

    # 3. Agreement statistics
    python3 run_validation.py agree --packet validation_packet \
        --annotations validation_packet/annotations.json
"""

from __future__ import annotations

import json
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv(Path(__file__).parent / ".env")

from src.production import build_ground_truth, load_export
from src.production.validation import (
    CATEGORY_DEFINITIONS,
    build_validation_sample,
    compute_agreement,
    items_from_packet,
    llm_annotate,
    write_packet,
)

console = Console()


@click.group()
def cli():
    """Validate the heuristic ground truth against an independent annotator."""


@cli.command()
@click.option("--export", "export_path", required=True, type=click.Path(exists=True))
@click.option("--output-dir", default="validation_packet", show_default=True)
@click.option("--n-flagged", default=40, show_default=True)
@click.option("--n-clean", default=10, show_default=True)
@click.option("--min-score", default=3.0, show_default=True)
@click.option("--seed", default=42, show_default=True)
def sample(export_path, output_dir, n_flagged, n_clean, min_score, seed):
    """Build the stratified blind annotation packet."""
    console.print("[bold]Building validation sample...[/bold]")
    conversations = load_export(export_path)
    ground_truth = build_ground_truth(conversations, min_score=min_score)
    items = build_validation_sample(
        conversations, ground_truth,
        n_flagged=n_flagged, n_clean=n_clean, seed=seed,
    )
    out = write_packet(items, output_dir)
    console.print(Panel(
        f"{len(items)} conversations written to [cyan]{out}[/cyan]\n"
        "- ANNOTATION_GUIDE.md — read this first\n"
        "- items.json — the blind transcripts\n"
        "- annotations.json — fill via `annotate` (interactive) or by hand\n"
        "- answer_key.json — [red]do not open until you have finished[/red]",
        title="Packet ready", style="green",
    ))


@cli.command()
@click.option("--packet", default="validation_packet", show_default=True,
              type=click.Path(exists=True))
def annotate(packet):
    """Interactive HUMAN annotation in the terminal (resumable)."""
    items = items_from_packet(packet)
    ann_path = Path(packet) / "annotations.json"
    annotations = json.loads(ann_path.read_text())
    by_id = {a["conversation_id"]: a for a in annotations}

    console.print(Panel(
        (Path(packet) / "ANNOTATION_GUIDE.md").read_text()[:1500],
        title="Protocol (see ANNOTATION_GUIDE.md for the rest)",
    ))
    cats = list(CATEGORY_DEFINITIONS)

    done = sum(1 for a in annotations if a.get("did_fail") in ("yes", "partial", "no"))
    console.print(f"[bold]{done}/{len(items)} already annotated — resuming.[/bold]\n")

    for idx, item in enumerate(items, 1):
        record = by_id[item.conversation_id]
        if record.get("did_fail") in ("yes", "partial", "no"):
            continue
        console.rule(f"[bold]{idx}/{len(items)}[/bold] · status={item.status} · {item.message_count} messages")
        for turn in item.transcript:
            style = {"customer": "cyan", "ai_agent": "white", "human_agent": "yellow"}.get(
                turn["source"], "dim")
            console.print(f"[{style}]{turn['source']:>12}[/{style}] {turn['text'][:400]}")

        answer = click.prompt(
            "\nDid the agent fail? [y]es / [p]artial / [n]o / [q]uit-and-save",
            type=click.Choice(["y", "p", "n", "q"]), show_choices=False,
        )
        if answer == "q":
            break
        record["did_fail"] = {"y": "yes", "p": "partial", "n": "no"}[answer]
        if answer in ("y", "p"):
            console.print("Categories: " + "  ".join(
                f"[bold]{i}[/bold]={c}" for i, c in enumerate(cats, 1)))
            raw = click.prompt("Numbers (comma-separated, empty for none)",
                               default="", show_default=False)
            picked = []
            for token in raw.split(","):
                token = token.strip()
                if token.isdigit() and 1 <= int(token) <= len(cats):
                    picked.append(cats[int(token) - 1])
            record["categories"] = picked
        record["note"] = click.prompt("Note (optional)", default="", show_default=False)
        ann_path.write_text(json.dumps(annotations, indent=2, ensure_ascii=False))

    ann_path.write_text(json.dumps(annotations, indent=2, ensure_ascii=False))
    done = sum(1 for a in annotations if a.get("did_fail") in ("yes", "partial", "no"))
    console.print(f"\n[green]Saved.[/green] {done}/{len(items)} annotated → {ann_path}")
    if done == len(items):
        console.print("Run: [cyan]python3 run_validation.py agree --packet "
                      f"{packet}[/cyan]")


@cli.command("llm-annotate")
@click.option("--packet", default="validation_packet", show_default=True,
              type=click.Path(exists=True))
@click.option("--output", default=None,
              help="Default: <packet>/annotations_llm_pilot.json")
def llm_annotate_cmd(packet, output):
    """LLM PILOT annotation — a preliminary consistency check ONLY.

    The dissertation's reported agreement must come from the human pass;
    an LLM annotator would reintroduce the circularity the methodology
    is designed to exclude.
    """
    console.print(Panel(
        "[yellow]PILOT ONLY: these labels are for catching heuristic bugs early.\n"
        "They must NOT be reported as inter-annotator agreement.[/yellow]",
        title="LLM pilot", style="yellow",
    ))
    items = items_from_packet(packet)
    annotations = llm_annotate(items, on_progress=lambda m: console.print(f"  {m}"))
    out = Path(output) if output else Path(packet) / "annotations_llm_pilot.json"
    out.write_text(json.dumps(
        {"annotator_type": "llm_pilot",
         "caveat": "Preliminary check only; not a substitute for human validation.",
         "annotations": [a.__dict__ for a in annotations]},
        indent=2, ensure_ascii=False,
    ))
    console.print(f"[green]Pilot annotations →[/green] {out}")


@cli.command()
@click.option("--packet", default="validation_packet", show_default=True,
              type=click.Path(exists=True))
@click.option("--annotations", "annotations_path", required=True,
              type=click.Path(exists=True))
@click.option("--output", default=None, help="Default: <packet>/agreement[_llm_pilot].json")
def agree(packet, annotations_path, output):
    """Compute agreement between the heuristic labels and an annotator."""
    items = items_from_packet(packet)
    data = json.loads(Path(annotations_path).read_text())
    annotator_type = "human"
    if isinstance(data, dict):
        annotator_type = data.get("annotator_type", "human")
        data = data.get("annotations", [])

    report = compute_agreement(items, data)
    report["annotator_type"] = annotator_type
    if annotator_type != "human":
        report["caveat"] = ("LLM pilot agreement — preliminary check only; "
                            "the dissertation must report the human number.")

    suffix = "" if annotator_type == "human" else f"_{annotator_type}"
    out = Path(output) if output else Path(packet) / f"agreement{suffix}.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    lenient = report["binary_lenient"]
    strict = report["binary_strict"]
    table = Table(title=f"Agreement ({annotator_type}, {report['n_labelled']}/{report['n_items']} labelled)")
    table.add_column("Metric"); table.add_column("Lenient (partial=fail)"); table.add_column("Strict")
    table.add_row("Observed agreement", f"{lenient['observed_agreement']:.3f}", f"{strict['observed_agreement']:.3f}")
    table.add_row("Cohen's κ", f"{lenient['cohens_kappa']:.3f}", f"{strict['cohens_kappa']:.3f}")
    table.add_row("Heuristic precision", str(lenient["heuristic_precision"]), str(strict["heuristic_precision"]))
    table.add_row("Heuristic recall", str(lenient["heuristic_recall"]), str(strict["heuristic_recall"]))
    console.print(table)

    if report["per_category"]:
        cat_table = Table(title="Per-category (conversations either side flagged)")
        cat_table.add_column("Category"); cat_table.add_column("P"); cat_table.add_column("R")
        cat_table.add_column("tp/fp/fn")
        for cat, s in report["per_category"].items():
            cat_table.add_row(cat, str(s["precision"]), str(s["recall"]),
                              f"{s['tp']}/{s['fp']}/{s['fn']}")
        console.print(cat_table)

    if report["disagreements"]:
        console.print(f"[yellow]{len(report['disagreements'])} binary disagreements "
                      f"— review them in {out}[/yellow]")
    console.print(f"[green]Full report →[/green] {out}")


if __name__ == "__main__":
    cli()
