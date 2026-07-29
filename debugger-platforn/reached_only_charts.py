#!/usr/bin/env python3
"""
Reached-only category charts — companion to compare_real_vs_sim.py.

Reads docs/results/real_vs_sim/real_vs_sim.json (produced by
compare_real_vs_sim.py) and generates charts restricted to the FIVE
categories the simulator actually reproduced (reachable_found), with
percentages renormalised over that 5-category support so real and sim
composition can be compared like-for-like.  Also renders an overview
chart of all seven reachable categories that highlights the two the
simulator never reached (comprehension, data_gap).

Outputs to docs/results/real_vs_sim/reached_only/:
  reachability_overview.png   7 reachable categories, unreached ones flagged
  reached_only_rates.png      rates among failures, 5 reached categories
  reached_only_shares.png     renormalised shares over the 5-category support
  reached_only_composition.png  side-by-side composition pies
  reached_only.json           all numbers used in the charts + 5-support JSD

Usage: python3 reached_only_charts.py
       [--input ../docs/results/real_vs_sim/real_vs_sim.json]
       [-o ../docs/results/real_vs_sim/reached_only]
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

REAL_COLOR = "#1f4e63"
SIM_COLOR = "#2e8ba8"
MISS_COLOR = "#c0504d"

# Shared-taxonomy names of the five reachable_found categories, ordered by
# real-corpus count (descending) so the dominant modes read left to right.
REACHED = [
    "infinite_loop",
    "resolution_failure",
    "hallucination",
    "escalation_failure",
    "premature_exit",
]
# The two reachable-but-never-reached categories, for the overview chart.
UNREACHED = ["comprehension_failure", "data_gap"]

LABELS = {
    "infinite_loop": "loop_stall\n(infinite_loop)",
    "resolution_failure": "resolution",
    "hallucination": "hallucination",
    "escalation_failure": "missed_escalation",
    "premature_exit": "silent_abandonment\n(premature_exit)",
    "comprehension_failure": "comprehension",
    "data_gap": "data_gap",
}


def jsd_bits(p: list[float], q: list[float]) -> float:
    """Jensen-Shannon divergence in bits over a shared support."""
    m = [(pi + qi) / 2 for pi, qi in zip(p, q)]

    def kl(a, b):
        return sum(ai * math.log2(ai / bi) for ai, bi in zip(a, b) if ai > 0)

    return 0.5 * kl(p, m) + 0.5 * kl(q, m)


def annotate_bars(ax, bars, fmt="{:.1f}%"):
    for bar in bars:
        h = bar.get_height()
        ax.annotate(fmt.format(h), (bar.get_x() + bar.get_width() / 2, h),
                    ha="center", va="bottom", fontsize=8)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--input", default="../docs/results/real_vs_sim/real_vs_sim.json")
    ap.add_argument("-o", "--output", default="../docs/results/real_vs_sim/reached_only")
    args = ap.parse_args()

    results = json.load(open(args.input))
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    real = results["per_category_rates"]["real_shared_taxonomy"]
    sim = results["per_category_rates"]["sim_shared_taxonomy"]

    real_counts = {c: real.get(c, {}).get("count", 0) for c in REACHED + UNREACHED}
    sim_counts = {c: sim.get(c, {}).get("count", 0) for c in REACHED + UNREACHED}
    real_total5 = sum(real_counts[c] for c in REACHED)
    sim_total5 = sum(sim_counts[c] for c in REACHED)
    real_share = {c: real_counts[c] / real_total5 for c in REACHED}
    sim_share = {c: sim_counts[c] / sim_total5 for c in REACHED}
    jsd5 = jsd_bits([real_share[c] for c in REACHED], [sim_share[c] for c in REACHED])

    # ---- Chart 1: seven reachable categories, unreached flagged ------------
    cats7 = REACHED + UNREACHED
    order7 = sorted(cats7, key=lambda c: -real[c]["rate_of_failures"])
    x = range(len(order7))
    fig, ax = plt.subplots(figsize=(11, 5.5))
    rb = ax.bar([i - 0.2 for i in x],
                [real[c]["rate_of_failures"] * 100 for c in order7],
                width=0.4, label="Real", color=REAL_COLOR)
    sim_vals = [sim.get(c, {}).get("rate_of_failures", 0) * 100 for c in order7]
    sim_colors = [MISS_COLOR if c in UNREACHED else SIM_COLOR for c in order7]
    sb = ax.bar([i + 0.2 for i in x], sim_vals, width=0.4, label="Simulated",
                color=sim_colors)
    annotate_bars(ax, rb)
    annotate_bars(ax, sb)
    for i, c in enumerate(order7):
        if c in UNREACHED:
            ax.annotate("never\nreached", (i + 0.2, 1.5), ha="center",
                        va="bottom", fontsize=8, color=MISS_COLOR,
                        fontweight="bold")
            ax.axvspan(i - 0.45, i + 0.45, color=MISS_COLOR, alpha=0.07)
    ax.set_xticks(list(x))
    ax.set_xticklabels([LABELS[c] for c in order7], fontsize=9)
    ax.set_ylabel("% of failed conversations flagged")
    ax.set_title("Seven reachable failure categories — the two the simulator never reached")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "reachability_overview.png", dpi=150)
    plt.close(fig)

    # ---- Chart 2: rates among failures, reached categories only ------------
    x = range(len(REACHED))
    fig, ax = plt.subplots(figsize=(10, 5))
    rb = ax.bar([i - 0.2 for i in x],
                [real[c]["rate_of_failures"] * 100 for c in REACHED],
                width=0.4, label="Real (n=376 failures)", color=REAL_COLOR)
    sb = ax.bar([i + 0.2 for i in x],
                [sim.get(c, {}).get("rate_of_failures", 0) * 100 for c in REACHED],
                width=0.4, label="Simulated (n=82 failures)", color=SIM_COLOR)
    annotate_bars(ax, rb)
    annotate_bars(ax, sb)
    ax.set_xticks(list(x))
    ax.set_xticklabels([LABELS[c] for c in REACHED], fontsize=9)
    ax.set_ylabel("% of failed conversations flagged")
    ax.set_title("Reached categories only — flag rate among failures (multi-label)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "reached_only_rates.png", dpi=150)
    plt.close(fig)

    # ---- Chart 3: renormalised shares over the 5-category support ----------
    fig, ax = plt.subplots(figsize=(10, 5))
    rb = ax.bar([i - 0.2 for i in x], [real_share[c] * 100 for c in REACHED],
                width=0.4, label=f"Real ({real_total5} flags)", color=REAL_COLOR)
    sb = ax.bar([i + 0.2 for i in x], [sim_share[c] * 100 for c in REACHED],
                width=0.4, label=f"Simulated ({sim_total5} flags)", color=SIM_COLOR)
    annotate_bars(ax, rb)
    annotate_bars(ax, sb)
    ax.set_xticks(list(x))
    ax.set_xticklabels([LABELS[c] for c in REACHED], fontsize=9)
    ax.set_ylabel("Share of category flags (renormalised, %)")
    ax.set_title(f"Failure composition over the five reached categories "
                 f"(JSD = {jsd5:.3f} bits)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "reached_only_shares.png", dpi=150)
    plt.close(fig)

    # ---- Chart 4: composition pies -----------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    pie_colors = ["#1f4e63", "#2e8ba8", "#7fb3c8", "#b5d1dd", "#d9e6ec"]
    for ax, shares, title in (
        (axes[0], real_share, f"Real ({real_total5} flags)"),
        (axes[1], sim_share, f"Simulated ({sim_total5} flags)"),
    ):
        vals = [shares[c] * 100 for c in REACHED]
        labels = [LABELS[c].replace("\n", " ") if shares[c] >= 0.03 else ""
                  for c in REACHED]
        ax.pie(vals, labels=labels, colors=pie_colors, startangle=90,
               autopct=lambda p: f"{p:.1f}%" if p >= 3 else "",
               textprops={"fontsize": 8})
        ax.set_title(title, fontsize=10)
    fig.suptitle("Composition of failures across the five reached categories",
                 fontsize=12)
    fig.tight_layout()
    fig.savefig(out_dir / "reached_only_composition.png", dpi=150)
    plt.close(fig)

    payload = {
        "source": str(args.input),
        "taxonomy_version": results["taxonomy_version"],
        "reached_categories": REACHED,
        "unreached_categories": UNREACHED,
        "real_counts": real_counts,
        "sim_counts": sim_counts,
        "real_total_flags_5": real_total5,
        "sim_total_flags_5": sim_total5,
        "real_shares_5": {c: round(real_share[c], 4) for c in REACHED},
        "sim_shares_5": {c: round(sim_share[c], 4) for c in REACHED},
        "jsd_5_support_bits": round(jsd5, 4),
        "note": ("Shares renormalised over category flags on the 5-category "
                 "reached support; flags are multi-label, so shares describe "
                 "flag composition, not conversation composition."),
    }
    with open(out_dir / "reached_only.json", "w") as f:
        json.dump(payload, f, indent=2)
    print(f"Wrote 4 charts + reached_only.json to {out_dir}  (JSD5={jsd5:.4f})")


if __name__ == "__main__":
    main()
