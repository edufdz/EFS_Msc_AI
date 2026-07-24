#!/usr/bin/env python3
"""
Scale study: how does simulation power grow with batch size?

Takes the results_scale_study/N* batches (independent live-agent runs at
N = 10, 50, 100, 200, 400, 800, 1000), scores every simulated conversation
with the production scorer (scorer parity — see compare_real_vs_sim.py),
and reports, per batch size and cumulatively:

  - failure count / failure rate
  - unique production categories found + coverage of the reachable real ones
  - JSD(real, sim) on the reachable shared-taxonomy support
  - wall-clock duration and persona cost (from each batch's run report)

Outputs curves (PNG), scale_curves.json, and SCALE_REPORT.md.

Usage:
    python3 scale_curves.py \
        --real ../docs/tech_repair-conversations-anonymized.json \
        --batches results_scale_study \
        -o ../docs/results/real_vs_sim/scale
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from compare_real_vs_sim import (
    REACHABILITY,
    adapt_sim_conversation,
    bootstrap_jsd,
    category_counts,
    score_corpus,
    split_half_noise_floor,
)
from src.production.ground_truth import DEFAULT_MIN_SCORE
from src.production.loader import load_export
from src.evaluation.projection import project_production_category


def batch_metrics(
    sim_records: List[Dict[str, Any]],
    real_records: List[Dict[str, Any]],
    reachable_support: List[str],
    reachable_real_cats: List[str],
) -> Dict[str, Any]:
    failed = [r for r in sim_records if r["failed"]]
    prod = category_counts(sim_records, "categories")
    found = [c for c in reachable_real_cats if prod.get(c, 0) > 0]
    jsd = bootstrap_jsd(real_records, sim_records, reachable_support, "shared",
                        n_iter=500)
    return {
        "conversations": len(sim_records),
        "failures": len(failed),
        "failure_rate": round(len(failed) / len(sim_records), 4) if sim_records else 0,
        "production_categories_found": sorted(prod),
        "n_categories_found": len(prod),
        "coverage_of_reachable_real": round(len(found) / len(reachable_real_cats), 4)
        if reachable_real_cats else None,
        "jsd_vs_real": jsd,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", required=True)
    ap.add_argument("--batches", default="results_scale_study")
    ap.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE)
    ap.add_argument("-o", "--output", default="../docs/results/real_vs_sim/scale")
    args = ap.parse_args()

    real_records = score_corpus(load_export(args.real), args.min_score)
    real_prod = category_counts(real_records, "categories")
    reachable_real = [c for c, (reach, _) in REACHABILITY.items()
                      if reach != "unreachable" and real_prod.get(c, 0) > 0]
    reachable_support = sorted({project_production_category(c).value for c in reachable_real})
    noise = split_half_noise_floor(real_records, reachable_support, "shared")

    batch_dirs = sorted(
        (p for p in Path(args.batches).iterdir()
         if p.is_dir() and re.fullmatch(r"N\d+", p.name)),
        key=lambda p: int(p.name[1:]),
    )

    per_batch: Dict[int, Dict[str, Any]] = {}
    cumulative: Dict[int, Dict[str, Any]] = {}
    pooled: List[Dict[str, Any]] = []
    for bd in batch_dirs:
        conv_file = bd / "conversations.json"
        if not conv_file.exists():
            print(f"skip {bd.name}: no conversations.json")
            continue
        n = int(bd.name[1:])
        convs = [adapt_sim_conversation(c)
                 for c in json.load(open(conv_file))["conversations"]]
        records = score_corpus(convs, args.min_score)
        m = batch_metrics(records, real_records, reachable_support, reachable_real)
        report_file = bd / "test_run_report.json"
        if report_file.exists():
            rep = json.load(open(report_file))
            m["duration_sec"] = rep.get("total_duration_sec")
            m["persona_cost_usd"] = rep.get("total_cost_usd")
            m["pass_rate_oracle"] = rep.get("pass_rate")
        per_batch[n] = m
        pooled.extend(records)
        cumulative[len(pooled)] = batch_metrics(
            pooled, real_records, reachable_support, reachable_real)
        print(f"batch N={n}: {m['failures']}/{m['conversations']} failures, "
              f"{m['n_categories_found']} categories, "
              f"coverage {m['coverage_of_reachable_real']:.0%}, "
              f"JSD {m['jsd_vs_real']['point']:.4f}")

    results = {
        "min_score": args.min_score,
        "reachable_real_categories": reachable_real,
        "reachable_support": reachable_support,
        "split_half_noise_floor_real": noise,
        "per_batch": per_batch,
        "cumulative_pooled": cumulative,
    }
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "scale_curves.json", "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    _write_report(results, out)
    _write_charts(results, out)
    print(f"\nOutputs: {out}/scale_curves.json, SCALE_REPORT.md, scale_curves.png")


def _write_report(results: Dict[str, Any], out: Path) -> None:
    lines = [
        "# Simulation Scale Study — coverage and correspondence vs batch size",
        "",
        f"Independent live-agent batches; identical production scorer both sides "
        f"(min_score={results['min_score']}). Reachable real categories: "
        f"{', '.join(results['reachable_real_categories'])}. "
        f"Real split-half JSD noise floor: "
        f"{results['split_half_noise_floor_real']['mean']:.4f}.",
        "",
        "## Per batch (independent runs)",
        "",
        "| N | failures | fail rate | categories | coverage | JSD vs real (95% CI) | conv-min (sum) | persona $ |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for n, m in results["per_batch"].items():
        j = m["jsd_vs_real"]
        dur = f"{m['duration_sec']/60:.0f}" if m.get("duration_sec") else "—"
        cost = f"{m['persona_cost_usd']:.2f}" if m.get("persona_cost_usd") is not None else "—"
        lines.append(
            f"| {n} | {m['failures']} | {m['failure_rate']:.1%} | "
            f"{m['n_categories_found']} | {m['coverage_of_reachable_real']:.0%} | "
            f"{j['point']:.4f} ({j['ci_low']:.4f}–{j['ci_high']:.4f}) | {dur} | {cost} |"
        )
    lines += ["", "## Cumulative (batches pooled in ascending order)", "",
              "| total N | failures | coverage | JSD vs real |", "|---|---|---|---|"]
    for n, m in results["cumulative_pooled"].items():
        lines.append(f"| {n} | {m['failures']} | "
                     f"{m['coverage_of_reachable_real']:.0%} | "
                     f"{m['jsd_vs_real']['point']:.4f} |")
    lines += ["", "_Generated by scale_curves.py._"]
    (out / "SCALE_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def _write_charts(results: Dict[str, Any], out: Path) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    pb = results["per_batch"]
    ns = sorted(pb)
    cum = results["cumulative_pooled"]
    cns = sorted(cum)

    fig, axes = plt.subplots(2, 2, figsize=(13, 9))

    ax = axes[0][0]
    ax.plot(ns, [pb[n]["coverage_of_reachable_real"] * 100 for n in ns],
            "o-", color="#1f4e63", label="independent batch")
    ax.plot(cns, [cum[n]["coverage_of_reachable_real"] * 100 for n in cns],
            "s--", color="#2e8ba8", label="cumulative pooled")
    ax.set_xscale("log")
    ax.set_xlabel("simulated conversations (N)")
    ax.set_ylabel("% of reachable real categories found")
    ax.set_title("Failure-category coverage vs scale")
    ax.set_ylim(0, 105)
    ax.legend()

    ax = axes[0][1]
    pts = [pb[n]["jsd_vs_real"]["point"] for n in ns]
    los = [pb[n]["jsd_vs_real"]["ci_low"] for n in ns]
    his = [pb[n]["jsd_vs_real"]["ci_high"] for n in ns]
    ax.plot(ns, pts, "o-", color="#1f4e63", label="JSD(real, sim)")
    ax.fill_between(ns, los, his, alpha=0.2, color="#1f4e63")
    ax.axhline(results["split_half_noise_floor_real"]["mean"], ls=":",
               color="grey", label="real split-half noise floor")
    ax.set_xscale("log")
    ax.set_xlabel("simulated conversations (N)")
    ax.set_ylabel("JSD (bits)")
    ax.set_title("Distribution gap vs scale")
    ax.legend()

    ax = axes[1][0]
    ax.plot(ns, [pb[n]["failures"] for n in ns], "o-", color="#1f4e63")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("simulated conversations (N)")
    ax.set_ylabel("failures found (same scorer as production)")
    ax.set_title("Failures found vs scale")

    ax = axes[1][1]
    dur = [pb[n].get("duration_sec") or 0 for n in ns]
    ax.plot(ns, [d / 60 for d in dur], "o-", color="#1f4e63", label="conv-minutes (sum)")
    ax2 = ax.twinx()
    ax2.plot(ns, [pb[n].get("persona_cost_usd") or 0 for n in ns],
             "s--", color="#b3611f", label="persona $")
    ax.set_xscale("log")
    ax.set_xlabel("simulated conversations (N)")
    ax.set_ylabel("summed conversation-minutes (÷6 workers ≈ wall)")
    ax2.set_ylabel("persona cost (USD)")
    ax.set_title("Cost of scale")
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper left")

    fig.suptitle("Live-agent simulation: power vs number of simulations", y=0.995)
    fig.tight_layout()
    fig.savefig(out / "scale_curves.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    main()
