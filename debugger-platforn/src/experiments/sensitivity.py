"""
Sensitivity analysis: is the RQ3 result robust to analysis choices?

Re-runs the (offline, static-mode) experiment varying one parameter at a
time around the default configuration:

  min_score          ground-truth failure threshold      2.0, 3.0, 4.0, 5.0
  holdout_fraction   chronological held-out share        0.2, 0.3, 0.4
  rng_seed           generation randomness               41..45

and reports RQ1 recall, RQ3 delta and p-value per configuration.  If the
headline conclusion (feedback beats blind on held-out recall) only holds at
one threshold or one seed, that is a finding the dissertation must report —
this module makes it impossible to miss.

Static mode only: the sweep isolates *analysis* choices, so the synthetic
side must stay deterministic; execute-mode variance is a property of the
agent under test, not of the analysis.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List

from src.experiments.runner import ExperimentConfig, run_experiment

DEFAULT_SWEEPS: Dict[str, List[Any]] = {
    "min_score": [2.0, 3.0, 4.0, 5.0],
    "holdout_fraction": [0.2, 0.3, 0.4],
    "rng_seed": [41, 42, 43, 44, 45],
}


def _extract_row(param: str, value: Any, results: Dict[str, Any]) -> Dict[str, Any]:
    rq1 = results["rq1_predictive_validity"]
    rq3 = results["rq3_production_feedback"]
    row: Dict[str, Any] = {
        "param": param,
        "value": value,
        "n_failures": results["ground_truth"]["n_failures"],
        "n_holdout_signals": rq3.get("n_holdout_signals"),
        "rq1_recall": rq1["overall"]["recall"],
        "rq1_precision": rq1["overall"]["precision"],
    }
    if rq3.get("available"):
        arms = rq3["comparison"]["arms"]
        test = rq3["comparison"]["tests"]["feedback_vs_blind"]
        row.update({
            "blind_recall": arms["blind"]["recall"],
            "feedback_recall": arms["feedback"]["recall"],
            "delta": test["delta"],
            "p_value": test["p_value"],
            "significant": test["p_value"] < 0.05,
        })
    return row


def run_sensitivity(
    base_config: ExperimentConfig,
    sweeps: Dict[str, List[Any]] | None = None,
    output_dir: str | Path = "experiments_output/sensitivity",
    on_progress: Callable[[str], None] = lambda m: None,
) -> Dict[str, Any]:
    """One-at-a-time sensitivity sweep around *base_config*.

    The default configuration itself runs once; each sweep value that
    differs from the default runs once more.  All runs share the same
    export/agent map and static mode.
    """
    sweeps = DEFAULT_SWEEPS if sweeps is None else sweeps
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    base_config = replace(base_config, mode="static", arms=["blind", "feedback"])

    rows: List[Dict[str, Any]] = []

    def _run_one(param: str, value: Any) -> None:
        label = f"{param}={value}"
        on_progress(f"Running {label}...")
        overrides = {} if param == "baseline" else {param: value}
        config = replace(
            base_config,
            output_dir=str(out / "runs" / label.replace("=", "_")),
            **overrides,
        )
        results = run_experiment(config)
        rows.append(_extract_row(param, value, results))
        row = rows[-1]
        if "delta" in row:
            on_progress(
                f"  {label}: Δ={row['delta']:+.3f} p={row['p_value']:.4f} "
                f"(n_failures={row['n_failures']})"
            )

    # Baseline (counts once, under a synthetic 'baseline' param)
    _run_one("baseline", "default")

    defaults = {
        "min_score": base_config.min_score,
        "holdout_fraction": base_config.holdout_fraction,
        "rng_seed": base_config.rng_seed,
    }
    for param, values in sweeps.items():
        for value in values:
            if value == defaults.get(param):
                continue  # already covered by the baseline run
            _run_one(param, value)

    # ---- Robustness verdict ----
    tested = [r for r in rows if "delta" in r]
    n_positive = sum(1 for r in tested if r["delta"] > 0)
    n_significant = sum(1 for r in tested if r["significant"])
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_config": {
            "export_path": str(base_config.export_path),
            "agent_map_path": str(base_config.agent_map_path),
            "budget": base_config.budget,
            "min_score": base_config.min_score,
            "holdout_fraction": base_config.holdout_fraction,
            "rng_seed": base_config.rng_seed,
        },
        "n_configurations": len(tested),
        "n_delta_positive": n_positive,
        "n_significant": n_significant,
        "robust": n_positive == len(tested) and n_significant == len(tested),
        "delta_range": [
            min((r["delta"] for r in tested), default=None),
            max((r["delta"] for r in tested), default=None),
        ],
        "max_p_value": max((r["p_value"] for r in tested), default=None),
        "rows": rows,
    }

    (out / "sensitivity.json").write_text(json.dumps(summary, indent=2, default=str))
    _write_markdown(summary, out)
    try:
        _render_chart(summary, out)
    except Exception:  # chart is best-effort
        pass
    return summary


def _write_markdown(summary: Dict[str, Any], out: Path) -> Path:
    lines = [
        "# Sensitivity Analysis — RQ3 robustness",
        "",
        f"Generated: {summary['generated_at']}  ",
        f"Configurations tested: {summary['n_configurations']}  ",
        f"Δ(feedback−blind) positive in **{summary['n_delta_positive']}/{summary['n_configurations']}**, "
        f"significant (p<0.05) in **{summary['n_significant']}/{summary['n_configurations']}**  ",
        f"Δ range: {summary['delta_range'][0]:+.3f} … {summary['delta_range'][1]:+.3f}; "
        f"max p-value: {summary['max_p_value']:.4f}",
        "",
        f"**Verdict: {'ROBUST' if summary['robust'] else 'NOT UNIFORMLY ROBUST — report the exceptions'}**",
        "",
        "| Varied | Value | GT failures | Held-out signals | Blind recall | Feedback recall | Δ | p | sig |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in summary["rows"]:
        if "delta" not in r:
            continue
        lines.append(
            f"| {r['param']} | {r['value']} | {r['n_failures']} | {r['n_holdout_signals']} "
            f"| {r['blind_recall']:.3f} | {r['feedback_recall']:.3f} "
            f"| {r['delta']:+.3f} | {r['p_value']:.4f} | {'✓' if r['significant'] else '✗'} |"
        )
    path = out / "SENSITIVITY.md"
    path.write_text("\n".join(lines))
    return path


def _render_chart(summary: Dict[str, Any], out: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = [r for r in summary["rows"] if "delta" in r]
    labels = [f"{r['param']}={r['value']}" for r in rows]
    deltas = [r["delta"] for r in rows]
    colors = ["#2563eb" if r["significant"] else "#94a3b8" for r in rows]

    fig, ax = plt.subplots(figsize=(9, 0.45 * len(rows) + 2))
    ax.barh(labels[::-1], deltas[::-1], color=colors[::-1])
    ax.axvline(0, color="#0f172a", linewidth=1)
    ax.set_xlabel("Δ held-out recall (feedback − blind)")
    ax.set_title("RQ3 delta across analysis configurations (grey = not significant)")
    fig.tight_layout()
    path = out / "sensitivity_deltas.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path
