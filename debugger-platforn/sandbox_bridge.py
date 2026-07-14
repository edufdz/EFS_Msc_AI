#!/usr/bin/env python3
"""
Sandbox Bridge CLI
~~~~~~~~~~~~~~~~~~

Serve a production agent behind a TEST endpoint with mocked tools and
deterministic failure injection, and replay recorded production
conversations to measure the sandbox's behavioural fidelity.

Usage:
    python3 sandbox_bridge.py serve --agent-map tech_repair_whatsapp_map.json \\
        --mode echo --port 8099 --trace-dir sandbox_traces/

    python3 sandbox_bridge.py replay --agent-map tech_repair_whatsapp_map.json \\
        --export ../docs/tech_repair-conversations-export.json \\
        --mode echo --sample 20 --output fidelity_report.json
"""

from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.sandbox.bridge import create_bridge_app
from src.sandbox.mock_tools import MockToolRegistry
from src.sandbox.models import SandboxBridgeConfig
from src.sandbox.replay import replay_batch

console = Console()


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_config(
    agent_map: dict,
    mode: str,
    upstream_url: str | None,
    trace_dir: str | None,
    error_rate: float,
    empty_rate: float,
    latency_ms: int,
    seed: int,
) -> SandboxBridgeConfig:
    """Build a bridge config with mocks derived from the agent map."""
    registry = MockToolRegistry.from_agent_map(
        agent_map,
        seed=seed,
        error_rate=error_rate,
        empty_rate=empty_rate,
        latency_ms=latency_ms,
    )
    language = (
        agent_map.get("metadata", {})
        .get("language", {})
        .get("primary_language", "Spanish")
        if isinstance(agent_map.get("metadata", {}).get("language"), dict)
        else agent_map.get("metadata", {}).get("language", "Spanish")
    )
    return SandboxBridgeConfig(
        mode=mode,  # type: ignore[arg-type]
        upstream_url=upstream_url,
        mock_tools=[registry.get(n) for n in registry.tool_names],  # type: ignore[misc]
        trace_dir=trace_dir,
        language=language or "Spanish",
        seed=seed,
    )


@click.group()
def cli() -> None:
    """Sandbox Bridge: test endpoint wrapper + replay fidelity harness."""


@cli.command()
@click.option("--agent-map", "agent_map_path", required=True, type=click.Path(exists=True), help="Phase A agent map JSON.")
@click.option("--mode", type=click.Choice(["echo", "http"]), default="echo", show_default=True, help="Upstream mode.")
@click.option("--upstream-url", default=None, help="Real agent endpoint (http mode).")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8099, show_default=True, type=int)
@click.option("--trace-dir", default="sandbox_traces", show_default=True, help="Directory for the trace JSONL.")
@click.option("--error-rate", default=0.0, show_default=True, type=float, help="Injected tool error rate [0..1].")
@click.option("--empty-rate", default=0.0, show_default=True, type=float, help="Injected empty-response rate [0..1].")
@click.option("--latency-ms", default=0, show_default=True, type=int, help="Injected tool latency (ms).")
@click.option("--seed", default=42, show_default=True, type=int, help="Seed for deterministic failure injection.")
def serve(
    agent_map_path: str,
    mode: str,
    upstream_url: str | None,
    host: str,
    port: int,
    trace_dir: str,
    error_rate: float,
    empty_rate: float,
    latency_ms: int,
    seed: int,
) -> None:
    """Run the sandbox bridge server (uvicorn)."""
    import uvicorn

    agent_map = _load_json(agent_map_path)
    config = _build_config(
        agent_map, mode, upstream_url, trace_dir,
        error_rate, empty_rate, latency_ms, seed,
    )
    app = create_bridge_app(config)

    n_tools = len(config.mock_tools)
    console.print(
        Panel(
            f"[bold]Sandbox Bridge[/bold]\n"
            f"Agent map:  {agent_map_path}\n"
            f"Mode:       [cyan]{mode}[/cyan]"
            + (f"  →  {upstream_url}" if upstream_url else "")
            + f"\nMock tools: {n_tools}  (error_rate={error_rate}, "
            f"empty_rate={empty_rate}, latency={latency_ms}ms, seed={seed})\n"
            f"Traces:     {trace_dir}/sandbox_traces.jsonl\n"
            f"Endpoint:   http://{host}:{port}/chat",
            title="serve",
            border_style="green",
        )
    )
    uvicorn.run(app, host=host, port=port)


@cli.command()
@click.option("--agent-map", "agent_map_path", required=True, type=click.Path(exists=True), help="Phase A agent map JSON.")
@click.option("--export", "export_path", required=True, type=click.Path(exists=True), help="Production conversations export JSON.")
@click.option("--mode", type=click.Choice(["echo", "http"]), default="echo", show_default=True)
@click.option("--upstream-url", default=None, help="Real agent endpoint (http mode).")
@click.option("--sample", default=20, show_default=True, type=int, help="Number of conversations to replay.")
@click.option("--max-turns", default=10, show_default=True, type=int)
@click.option("--seed", default=42, show_default=True, type=int, help="Seed for sampling and failure injection.")
@click.option("--error-rate", default=0.0, show_default=True, type=float)
@click.option("--trace-dir", default=None, help="Optional directory for replay traces.")
@click.option("--output", default="fidelity_report.json", show_default=True, help="Where to save the fidelity report.")
def replay(
    agent_map_path: str,
    export_path: str,
    mode: str,
    upstream_url: str | None,
    sample: int,
    max_turns: int,
    seed: int,
    error_rate: float,
    trace_dir: str | None,
    output: str,
) -> None:
    """Replay production conversations in-process and score fidelity."""
    agent_map = _load_json(agent_map_path)

    console.print(f"[dim]Loading export {export_path} ...[/dim]")
    export = _load_json(export_path)
    conversations = export.get("conversations", export if isinstance(export, list) else [])
    # Only conversations that actually have customer messages are replayable.
    replayable = [
        c for c in conversations
        if any(
            m.get("source") == "customer" and (m.get("text_body") or "").strip()
            for m in c.get("messages", []) or []
        )
    ]
    console.print(
        f"Export: [bold]{len(conversations)}[/bold] conversations "
        f"({len(replayable)} replayable)"
    )

    rng = random.Random(seed)
    k = min(sample, len(replayable))
    sampled = rng.sample(replayable, k) if k < len(replayable) else list(replayable)

    config = _build_config(
        agent_map, mode, upstream_url, trace_dir, error_rate, 0.0, 0, seed
    )
    app = create_bridge_app(config)

    with console.status(f"Replaying {len(sampled)} conversations ..."):
        summary = replay_batch(app, sampled, n=len(sampled), max_turns=max_turns)

    table = Table(title="Sandbox Fidelity Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green", justify="right")
    table.add_row("Conversations replayed", str(summary["num_conversations"]))
    table.add_row("Mean overall fidelity", f"{summary['mean_overall']:.3f}")
    table.add_row("Median overall fidelity", f"{summary['median_overall']:.3f}")
    table.add_row("Mean response similarity", f"{summary['mean_response_similarity']:.3f}")
    table.add_row("Mean tool-sequence overlap", f"{summary['mean_tool_sequence_overlap']:.3f}")
    table.add_row("Escalation agreement rate", f"{summary['escalation_agreement_rate']:.3f}")
    console.print(table)

    report = {
        "agent_map": agent_map_path,
        "export": export_path,
        "mode": mode,
        "sample": len(sampled),
        "max_turns": max_turns,
        "seed": seed,
        "error_rate": error_rate,
        "summary": summary,
    }
    Path(output).write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    console.print(
        Panel(f"Fidelity report saved to [bold]{output}[/bold]", border_style="green")
    )


if __name__ == "__main__":
    cli()
