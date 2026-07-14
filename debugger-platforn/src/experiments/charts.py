"""Chart rendering for experiment results (matplotlib, headless)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

_ARM_COLORS = {"blind": "#64748b", "feedback": "#2563eb",
               "template": "#64748b", "naive_llm": "#f59e0b", "gan": "#10b981"}


def _color(arm: str) -> str:
    return _ARM_COLORS.get(arm, "#9333ea")


def render_charts(results: Dict[str, Any], out_dir: Path) -> List[Path]:
    out_dir = Path(out_dir)
    charts_dir = out_dir / "charts"
    charts_dir.mkdir(exist_ok=True)
    paths: List[Path] = []

    paths.append(_per_category_recall(results, charts_dir))
    paths.append(_recall_vs_budget(results, charts_dir))
    rq3 = results.get("rq3_production_feedback") or {}
    if rq3.get("available"):
        paths.append(_arm_comparison(results, charts_dir))
    paths.append(_ground_truth_distribution(results, charts_dir))
    return [p for p in paths if p is not None]


def _per_category_recall(results: Dict[str, Any], charts_dir: Path) -> Path:
    per_cat = results["rq1_predictive_validity"]["per_category"]
    cats = [c for c, s in per_cat.items() if s["n_production_signals"] > 0]
    cats.sort(key=lambda c: -per_cat[c]["n_production_signals"])
    recalls = [per_cat[c]["recall"] for c in cats]
    counts = [per_cat[c]["n_production_signals"] for c in cats]

    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.barh(cats[::-1], recalls[::-1], color="#2563eb")
    for bar, count in zip(bars, counts[::-1]):
        ax.text(bar.get_width() + 0.01, bar.get_y() + bar.get_height() / 2,
                f"n={count}", va="center", fontsize=8, color="#475569")
    ax.set_xlabel("Recall against production signals")
    ax.set_xlim(0, 1.05)
    ax.set_title(
        f"RQ1: per-category recall of synthetic testing "
        f"({results['rq1_predictive_validity']['arm']} arm)"
    )
    fig.tight_layout()
    path = charts_dir / "rq1_per_category_recall.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _recall_vs_budget(results: Dict[str, Any], charts_dir: Path) -> Path:
    curves = results["rq4_recall_vs_budget"]["curves"]
    fig, ax = plt.subplots(figsize=(8, 5))
    for arm, curve in curves.items():
        xs = [p["budget"] for p in curve]
        ys = [p["recall"] for p in curve]
        ax.plot(xs, ys, marker="o", label=arm, color=_color(arm))
    ax.set_xlabel("Testing budget (number of test conversations)")
    ax.set_ylabel("Recall of held-out production failures")
    ax.set_ylim(0, 1.05)
    ax.set_title("RQ4: recall versus testing budget")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    path = charts_dir / "rq4_recall_vs_budget.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _arm_comparison(results: Dict[str, Any], charts_dir: Path) -> Path:
    comparison = results["rq3_production_feedback"]["comparison"]
    arms = list(comparison["arms"])
    recalls = [comparison["arms"][a]["recall"] for a in arms]
    cis = [comparison["arms"][a]["recall_ci"] for a in arms]
    errs = [
        [r - ci["ci_low"] for r, ci in zip(recalls, cis)],
        [ci["ci_high"] - r for r, ci in zip(recalls, cis)],
    ]
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.bar(arms, recalls, yerr=errs, capsize=6,
           color=[_color(a) for a in arms])
    test_key = next(iter(comparison.get("tests", {})), None)
    if test_key:
        t = comparison["tests"][test_key]
        ax.set_title(
            f"RQ3: held-out recall — Δ={t['delta']:+.3f}, p={t['p_value']:.4f}"
        )
    else:
        ax.set_title("RQ3: held-out recall by arm")
    ax.set_ylabel("Recall of held-out production failures")
    ax.set_ylim(0, 1.05)
    fig.tight_layout()
    path = charts_dir / "rq3_arm_comparison.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _ground_truth_distribution(results: Dict[str, Any], charts_dir: Path) -> Path:
    by_cat = results["ground_truth"]["by_production_category"]
    cats = sorted(by_cat, key=by_cat.get)
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.barh(cats, [by_cat[c] for c in cats], color="#0f766e")
    ax.set_xlabel("Conversations")
    ax.set_title(
        f"Production ground truth: {results['ground_truth']['n_failures']} failed "
        f"conversations by category (of {results['ground_truth']['n_conversations_analysed']})"
    )
    fig.tight_layout()
    path = charts_dir / "ground_truth_categories.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path
