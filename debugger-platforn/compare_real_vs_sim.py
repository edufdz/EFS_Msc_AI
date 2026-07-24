#!/usr/bin/env python3
"""
Real-vs-Simulated failure comparison (docs/REAL_VS_SIM_COMPARISON_PLAN.md).

Runs the SAME structured-signal failure scorer (src/production/scoring.py —
no LLM anywhere) over both corpora:

  REAL — the anonymised production export (1,299 TechRepair WhatsApp convs)
  SIM  — Phase C ``conversations.json`` exports from live-agent runs

Simulated conversations are adapted to the production message schema first,
so scorer parity holds by construction. Both category sets are projected onto
the frozen shared taxonomy, then compared three ways:

  1. Category distributions: counts/rates, Jensen-Shannon divergence with
     bootstrap CIs, anchored by a split-half noise floor and a uniform
     baseline.
  2. Reachability matrix: unreachable / reachable-found / reachable-missed
     per production category (delivery has no transport layer in sim, and
     intent/confidence telemetry does not exist there).
  3. Per-category rates among failures, both vocabularies.

Usage:
    python3 compare_real_vs_sim.py \
        --real ../docs/tech_repair-conversations-anonymized.json \
        --sim results_tech_repair_live_v4/conversations.json \
        --sim pipeline_output/session-636fc721/results/conversations.json \
        -o ../docs/results/real_vs_sim
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.evaluation.projection import (
    PRODUCTION_CATEGORIES,
    project_production_category,
)
from src.evaluation.taxonomy import TAXONOMY_VERSION
from src.production.ground_truth import DEFAULT_MIN_SCORE
from src.production.loader import load_export
from src.production.scoring import score_conversation

# ----------------------------------------------------------------------
# Reachability: which production failure categories CAN the simulator
# produce at all, given the signals available in Phase C conversations?
# Pre-registered in docs/REAL_VS_SIM_COMPARISON_PLAN.md §3/§5.
# ----------------------------------------------------------------------
REACHABILITY: Dict[str, Tuple[str, str]] = {
    "comprehension": (
        "partial",
        "customer-repeat signal observable; intent/confidence telemetry does not exist in sim",
    ),
    "resolution": ("reachable", "personas ask for humans; escalation observable"),
    "data_gap": ("partial", "single fake customer bounds the reachable data-gap space"),
    "loop_stall": ("reachable", "turn counts and repeated agent messages observable"),
    "delivery_infra": ("unreachable", "no WhatsApp transport layer in simulation"),
    "missed_escalation": ("reachable", "frustration wording and escalation both observable"),
    "silent_abandonment": ("reachable", "persona abandonment maps to expiry without closure"),
    "hallucination": ("reachable", "customer-pushback wording observable"),
}


# ----------------------------------------------------------------------
# Adapter: Phase C conversations.json -> production conversation schema
# ----------------------------------------------------------------------

def adapt_sim_conversation(conv: Dict[str, Any]) -> Dict[str, Any]:
    """Map one Phase C conversation to the shape score_conversation() reads.

    Only fields with a faithful production analogue are set; telemetry that
    does not exist in simulation (intent detection, confidence, delivery
    status) is left absent so the scorer sees it as missing, exactly as it
    would for a production conversation without those fields.
    """
    messages: List[Dict[str, Any]] = []
    for turn in conv.get("turns", []):
        role = turn.get("role")
        if role == "user":
            messages.append({"source": "customer", "text_body": turn.get("message", "")})
        elif role == "agent":
            messages.append({
                "source": "ai_agent",
                "text_body": turn.get("message", ""),
                "ai_tool_calls": [
                    {"name": tc.get("tool_name")}
                    for tc in (turn.get("tool_calls") or [])
                    if tc.get("tool_name")
                ],
            })
        # role == "system" (chaos annotations) has no production analogue

    outcome = conv.get("outcome")
    escalated = (
        outcome == "escalated_to_human"
        or "escalate_to_human" in (conv.get("tools_called_sequence") or [])
    )
    abandoned = outcome == "user_abandoned" or conv.get("status") in ("failed", "timeout")

    return {
        "id": conv.get("test_id", ""),
        "message_count": len(messages),
        "messages": messages,
        # Production semantics: escalated_at set when a hand-off was filed.
        "escalated_at": "sim" if escalated else None,
        "escalation_reason": None,
        "taken_over_at": None,
        "is_human_handling": False,
        # Persona abandonment == conversation expired without closure.
        "status": "expired" if (abandoned and not escalated) else "closed",
    }


# ----------------------------------------------------------------------
# Scoring both corpora with the identical scorer
# ----------------------------------------------------------------------

def score_corpus(
    conversations: List[Dict[str, Any]],
    min_score: float,
) -> List[Dict[str, Any]]:
    """Score every conversation; return per-conversation records with the
    production categories and shared-taxonomy projections of the failures."""
    records = []
    for conv in conversations:
        s = score_conversation(conv)
        failed = s.failure_score >= min_score and bool(s.categories)
        records.append({
            "id": s.conversation_id,
            "failure_score": s.failure_score,
            "failed": failed,
            "categories": s.categories if failed else [],
            "shared": sorted({project_production_category(c).value for c in s.categories})
            if failed else [],
        })
    return records


def category_counts(records: List[Dict[str, Any]], key: str) -> Counter:
    c: Counter = Counter()
    for r in records:
        for cat in r[key]:
            c[cat] += 1
    return c


# ----------------------------------------------------------------------
# Jensen-Shannon divergence + resampling
# ----------------------------------------------------------------------

def _distribution(counter: Counter, support: List[str]) -> List[float]:
    total = sum(counter.get(c, 0) for c in support)
    if total == 0:
        return [0.0] * len(support)
    return [counter.get(c, 0) / total for c in support]


def js_divergence(p: List[float], q: List[float]) -> float:
    """JSD in bits (log base 2); bounded [0, 1]; symmetric."""
    def _kl(a, b):
        return sum(x * math.log2(x / y) for x, y in zip(a, b) if x > 0 and y > 0)
    m = [(x + y) / 2 for x, y in zip(p, q)]
    return 0.5 * _kl(p, m) + 0.5 * _kl(q, m)


def bootstrap_jsd(
    real: List[Dict[str, Any]],
    sim: List[Dict[str, Any]],
    support: List[str],
    key: str,
    n_iter: int = 1000,
    seed: int = 42,
) -> Dict[str, float]:
    rng = random.Random(seed)
    samples = []
    for _ in range(n_iter):
        rr = [rng.choice(real) for _ in real]
        ss = [rng.choice(sim) for _ in sim]
        samples.append(js_divergence(
            _distribution(category_counts(rr, key), support),
            _distribution(category_counts(ss, key), support),
        ))
    samples.sort()
    return {
        "point": js_divergence(
            _distribution(category_counts(real, key), support),
            _distribution(category_counts(sim, key), support),
        ),
        "ci_low": samples[int(0.025 * n_iter)],
        "ci_high": samples[int(0.975 * n_iter)],
    }


def split_half_noise_floor(
    records: List[Dict[str, Any]],
    support: List[str],
    key: str,
    n_iter: int = 200,
    seed: int = 42,
) -> Dict[str, float]:
    """JSD between random halves of the SAME corpus — the sampling-noise
    floor any real-vs-sim JSD should be read against."""
    rng = random.Random(seed)
    samples = []
    pool = list(records)
    for _ in range(n_iter):
        rng.shuffle(pool)
        half = len(pool) // 2
        samples.append(js_divergence(
            _distribution(category_counts(pool[:half], key), support),
            _distribution(category_counts(pool[half:], key), support),
        ))
    samples.sort()
    return {
        "mean": sum(samples) / len(samples),
        "p95": samples[int(0.95 * n_iter) - 1],
    }


def wilson_interval(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


# ----------------------------------------------------------------------
# Report
# ----------------------------------------------------------------------

def build_results(
    real_records: List[Dict[str, Any]],
    sim_records: List[Dict[str, Any]],
    min_score: float,
    sim_sources: List[str],
) -> Dict[str, Any]:
    real_failed = [r for r in real_records if r["failed"]]
    sim_failed = [r for r in sim_records if r["failed"]]

    real_prod = category_counts(real_records, "categories")
    sim_prod = category_counts(sim_records, "categories")
    real_shared = category_counts(real_records, "shared")
    sim_shared = category_counts(sim_records, "shared")

    # Reachability matrix over the production vocabulary
    matrix = {}
    for cat in PRODUCTION_CATEGORIES:
        reach, why = REACHABILITY[cat]
        real_n, sim_n = real_prod.get(cat, 0), sim_prod.get(cat, 0)
        if reach == "unreachable":
            status = "unreachable"
        elif real_n == 0:
            status = "not_in_real"
        elif sim_n > 0:
            status = "reachable_found"
        else:
            status = "reachable_missed"
        matrix[cat] = {
            "reachability": reach,
            "rationale": why,
            "real_count": real_n,
            "sim_count": sim_n,
            "status": status,
            "shared_category": project_production_category(cat).value,
        }

    # Coverage among categories that are (at least partially) reachable and
    # actually occur in the real corpus
    candidates = [c for c, m in matrix.items()
                  if m["reachability"] != "unreachable" and m["real_count"] > 0]
    found = [c for c in candidates if matrix[c]["sim_count"] > 0]

    # Distribution comparison on the shared taxonomy, restricted to the
    # reachable support (pre-registered) and unrestricted (for transparency)
    reachable_support = sorted({matrix[c]["shared_category"] for c in candidates})
    full_support = sorted(set(real_shared) | set(sim_shared))

    jsd_reachable = bootstrap_jsd(real_records, sim_records, reachable_support, "shared")
    jsd_full = bootstrap_jsd(real_records, sim_records, full_support, "shared")
    noise_floor = split_half_noise_floor(real_records, reachable_support, "shared")
    uniform = [1 / len(reachable_support)] * len(reachable_support)
    jsd_uniform = js_divergence(
        _distribution(category_counts(real_records, "shared"), reachable_support), uniform
    )

    def rate_table(counter: Counter, n_failed: int) -> Dict[str, Any]:
        out = {}
        for cat, k in sorted(counter.items(), key=lambda kv: -kv[1]):
            lo, hi = wilson_interval(k, n_failed)
            out[cat] = {"count": k, "rate_of_failures": round(k / n_failed, 4) if n_failed else 0,
                        "wilson_95": [round(lo, 4), round(hi, 4)]}
        return out

    return {
        "taxonomy_version": TAXONOMY_VERSION,
        "min_score": min_score,
        "scorer": "src/production/scoring.py (identical for both corpora; no LLM)",
        "sim_sources": sim_sources,
        "corpus_sizes": {
            "real_conversations": len(real_records),
            "real_failures": len(real_failed),
            "real_failure_rate": round(len(real_failed) / len(real_records), 4),
            "sim_conversations": len(sim_records),
            "sim_failures": len(sim_failed),
            "sim_failure_rate": round(len(sim_failed) / len(sim_records), 4) if sim_records else 0,
        },
        "reachability_matrix": matrix,
        "category_coverage": {
            "reachable_real_categories": candidates,
            "reproduced_in_sim": found,
            "coverage": round(len(found) / len(candidates), 4) if candidates else None,
        },
        "distribution_comparison": {
            "support_reachable": reachable_support,
            "jsd_reachable_support": jsd_reachable,
            "jsd_full_support": {"support": full_support, **jsd_full},
            "split_half_noise_floor_real": noise_floor,
            "jsd_real_vs_uniform_baseline": round(jsd_uniform, 4),
            "note": "JSD in bits, bounded [0,1]. Compare real-vs-sim against the noise floor (lower bound) and the uniform baseline (upper anchor).",
        },
        "per_category_rates": {
            "real_production_vocab": rate_table(real_prod, len(real_failed)),
            "sim_production_vocab": rate_table(sim_prod, len(sim_failed)),
            "real_shared_taxonomy": rate_table(real_shared, len(real_failed)),
            "sim_shared_taxonomy": rate_table(sim_shared, len(sim_failed)),
        },
    }


def write_report(results: Dict[str, Any], out_dir: Path) -> None:
    r = results
    cs = r["corpus_sizes"]
    dc = r["distribution_comparison"]
    lines = [
        "# Real vs Simulated Failures — Comparison Report",
        "",
        f"Taxonomy `{r['taxonomy_version']}` · scorer parity: {r['scorer']} · "
        f"failure threshold min_score={r['min_score']}",
        "",
        f"Sim sources: {', '.join(r['sim_sources'])}",
        "",
        "## Corpora",
        "",
        f"| | conversations | failures | failure rate |",
        f"|---|---|---|---|",
        f"| Real | {cs['real_conversations']} | {cs['real_failures']} | {cs['real_failure_rate']:.1%} |",
        f"| Simulated | {cs['sim_conversations']} | {cs['sim_failures']} | {cs['sim_failure_rate']:.1%} |",
        "",
        "## Reachability matrix (production vocabulary)",
        "",
        "| category | reachability | real | sim | status |",
        "|---|---|---|---|---|",
    ]
    for cat, m in r["reachability_matrix"].items():
        lines.append(
            f"| {cat} | {m['reachability']} | {m['real_count']} | {m['sim_count']} | **{m['status']}** |"
        )
    cov = r["category_coverage"]
    lines += [
        "",
        f"**Coverage: {len(cov['reproduced_in_sim'])}/{len(cov['reachable_real_categories'])} "
        f"reachable real categories reproduced in simulation "
        f"({cov['coverage']:.0%}).**" if cov["coverage"] is not None else "",
        "",
        "## Distribution correspondence (shared taxonomy, reachable support)",
        "",
        f"- JSD(real, sim) = **{dc['jsd_reachable_support']['point']:.4f}** "
        f"(95% bootstrap CI {dc['jsd_reachable_support']['ci_low']:.4f}–"
        f"{dc['jsd_reachable_support']['ci_high']:.4f})",
        f"- Split-half noise floor (real vs real): mean {dc['split_half_noise_floor_real']['mean']:.4f}, "
        f"p95 {dc['split_half_noise_floor_real']['p95']:.4f}",
        f"- Real vs uniform baseline: {dc['jsd_real_vs_uniform_baseline']:.4f}",
        f"- Full-support JSD (incl. unreachable categories): "
        f"{dc['jsd_full_support']['point']:.4f}",
        "",
        "## Per-category rates among failures (shared taxonomy)",
        "",
        "| category | real rate | sim rate |",
        "|---|---|---|",
    ]
    real_rates = r["per_category_rates"]["real_shared_taxonomy"]
    sim_rates = r["per_category_rates"]["sim_shared_taxonomy"]
    for cat in sorted(set(real_rates) | set(sim_rates)):
        rr = real_rates.get(cat, {}).get("rate_of_failures", 0)
        sr = sim_rates.get(cat, {}).get("rate_of_failures", 0)
        lines.append(f"| {cat} | {rr:.1%} | {sr:.1%} |")
    lines += [
        "",
        "_Generated by compare_real_vs_sim.py. See docs/REAL_VS_SIM_COMPARISON_PLAN.md "
        "for the pre-registered design and validity threats._",
    ]
    (out_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def write_chart(results: Dict[str, Any], out_dir: Path) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    real_rates = results["per_category_rates"]["real_shared_taxonomy"]
    sim_rates = results["per_category_rates"]["sim_shared_taxonomy"]
    cats = sorted(set(real_rates) | set(sim_rates))
    rv = [real_rates.get(c, {}).get("rate_of_failures", 0) for c in cats]
    sv = [sim_rates.get(c, {}).get("rate_of_failures", 0) for c in cats]
    x = range(len(cats))
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.bar([i - 0.2 for i in x], rv, width=0.4, label="Real", color="#1f4e63")
    ax.bar([i + 0.2 for i in x], sv, width=0.4, label="Simulated", color="#2e8ba8")
    ax.set_xticks(list(x))
    ax.set_xticklabels(cats, rotation=30, ha="right")
    ax.set_ylabel("Share of failed conversations")
    ax.set_title("Failure-category rates: real production vs live-agent simulation")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "category_comparison.png", dpi=150)
    plt.close(fig)
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--real", required=True, help="Anonymised production export JSON")
    ap.add_argument("--sim", action="append", required=True,
                    help="Phase C conversations.json (repeatable)")
    ap.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE,
                    help=f"Failure threshold (default {DEFAULT_MIN_SCORE}, as ground truth)")
    ap.add_argument("-o", "--output", default="../docs/results/real_vs_sim",
                    help="Output directory")
    args = ap.parse_args()

    real_convs = load_export(args.real)
    print(f"Real corpus: {len(real_convs)} conversations")

    sim_convs: List[Dict[str, Any]] = []
    for path in args.sim:
        data = json.load(open(path))
        batch = [adapt_sim_conversation(c) for c in data.get("conversations", [])]
        sim_convs.extend(batch)
        print(f"Sim corpus: +{len(batch)} from {path}")

    real_records = score_corpus(real_convs, args.min_score)
    sim_records = score_corpus(sim_convs, args.min_score)

    results = build_results(real_records, sim_records, args.min_score, args.sim)

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "real_vs_sim.json", "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    write_report(results, out_dir)
    charted = write_chart(results, out_dir)

    cs = results["corpus_sizes"]
    cov = results["category_coverage"]
    jsd = results["distribution_comparison"]["jsd_reachable_support"]
    nf = results["distribution_comparison"]["split_half_noise_floor_real"]
    print(f"\nReal failures: {cs['real_failures']}/{cs['real_conversations']} "
          f"({cs['real_failure_rate']:.1%}) | Sim failures: {cs['sim_failures']}/"
          f"{cs['sim_conversations']} ({cs['sim_failure_rate']:.1%})")
    print(f"Category coverage: {len(cov['reproduced_in_sim'])}/"
          f"{len(cov['reachable_real_categories'])} reachable real categories reproduced")
    print(f"JSD(real, sim) = {jsd['point']:.4f} [{jsd['ci_low']:.4f}, {jsd['ci_high']:.4f}] "
          f"| noise floor {nf['mean']:.4f} (p95 {nf['p95']:.4f})")
    print(f"\nOutputs: {out_dir}/real_vs_sim.json, REPORT.md"
          + (", category_comparison.png" if charted else " (matplotlib missing — no chart)"))


if __name__ == "__main__":
    main()
