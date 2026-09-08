#!/usr/bin/env python3
"""Trigger-level attribution of the `loop_stall` failure flag.

READ-ONLY. Imports the production scorer and the sim->production adapter
verbatim (no monkey-patching, no edits), then re-derives the two disjuncts of
the loop_stall predicate (scoring.py:235) per conversation:

    loop_stall  <=>  message_count > 40  OR  repeated_ai >= 3

Corpora
  REAL  docs/tech_repair-conversations-anonymized.json          (1,299 convs)
  FIXED debugger-platforn/results_tech_repair_live_v4/conversations.json (v4 40)
        + docs/results/simulated_runs/{run_web_150tests, run_200tests_recovered} (390)
  SCALE debugger-platforn/results_scale_study/N*/conversations.json (2,560)

Usage:  python3 loop_stall_attribution.py --out <dir>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

REPO = Path("/Users/eduardo7/Desktop/dos-agent-debugger/MSC_AI_Project")
PLATFORM = REPO / "debugger-platforn"
sys.path.insert(0, str(PLATFORM))

from compare_real_vs_sim import adapt_sim_conversation          # noqa: E402
from src.production.ground_truth import DEFAULT_MIN_SCORE       # noqa: E402
from src.production.loader import load_export                   # noqa: E402
from src.production.scoring import _norm, score_conversation    # noqa: E402

MIN_SCORE = DEFAULT_MIN_SCORE          # 3.0
LENGTH_THRESHOLD = 40                  # scoring.py:235  message_count > 40
REPEAT_THRESHOLD = 3                   # scoring.py:235  repeated_ai >= 3


# ----------------------------------------------------------------------
# Re-derivation of the two loop_stall disjuncts, mirroring scoring.py:229-240
# ----------------------------------------------------------------------

def loop_stall_signals(conv: Dict[str, Any]) -> Dict[str, Any]:
    """Recompute the loop_stall inputs exactly as scoring.py does, plus two
    extra diagnostics the scorer does not keep (longest *consecutive* verbatim
    run, and the repeated text itself)."""
    messages = conv.get("messages") or []
    ai_msgs = [m for m in messages if m.get("source") == "ai_agent"]

    # scoring.py:229-234 — normalised, non-empty agent texts; multiplicity of
    # the most frequent one (NOT a consecutive run).
    ai_texts = [
        _norm(m.get("text_body") or "")
        for m in ai_msgs
        if (m.get("text_body") or "").strip()
    ]
    seen: Counter = Counter(ai_texts)
    repeated_ai = max(seen.values()) if seen else 0
    top_text = seen.most_common(1)[0][0] if seen else ""

    # Extra: longest run of *consecutive* identical agent texts.
    longest_run = 0
    run = 0
    prev = None
    for t in ai_texts:
        run = run + 1 if t == prev else 1
        longest_run = max(longest_run, run)
        prev = t

    # scoring.py:121 — message_count prefers the export's own field.
    message_count = int(conv.get("message_count") or len(messages))

    return {
        "message_count": message_count,
        "ai_message_count": len(ai_msgs),
        "repeated_ai": repeated_ai,
        "longest_consecutive_run": longest_run,
        "length_fired": message_count > LENGTH_THRESHOLD,
        "repetition_fired": repeated_ai >= REPEAT_THRESHOLD,
        "repeated_text_prefix": top_text[:90],
    }


def analyse(conversations: List[Dict[str, Any]], corpus: str) -> Dict[str, Any]:
    rows = []
    for conv in conversations:
        s = score_conversation(conv)
        failed = s.failure_score >= MIN_SCORE and bool(s.categories)
        sig = loop_stall_signals(conv)
        flagged = "loop_stall" in s.categories
        # Sanity: our re-derivation must agree with the scorer's own predicate.
        assert flagged == (sig["length_fired"] or sig["repetition_fired"]), (
            f"{corpus}/{s.conversation_id}: disjunct re-derivation disagrees "
            f"with scorer"
        )
        rows.append({
            "corpus": corpus,
            "id": s.conversation_id,
            "failure_score": s.failure_score,
            "failed": failed,
            "categories": s.categories,
            "loop_stall_flagged": flagged,
            "loop_stall_counted": flagged and failed,
            **sig,
        })
    return rows


def attribution(rows: List[Dict[str, Any]], gate: str) -> Dict[str, Any]:
    """Counts/percentages for the four mutually exclusive trigger buckets.

    gate = "loop_stall_counted"  -> flags that count as failures (min_score=3),
                                    the basis of every published number
    gate = "loop_stall_flagged"  -> category fired regardless of failure score
    """
    flagged = [r for r in rows if r[gate]]
    n = len(flagged)
    buckets = {
        "length_only": [r for r in flagged if r["length_fired"] and not r["repetition_fired"]],
        "repetition_only": [r for r in flagged if r["repetition_fired"] and not r["length_fired"]],
        "both": [r for r in flagged if r["length_fired"] and r["repetition_fired"]],
        "neither": [r for r in flagged if not r["length_fired"] and not r["repetition_fired"]],
    }
    return {
        "n_conversations": len(rows),
        "n_failures": sum(1 for r in rows if r["failed"]),
        "n_loop_stall": n,
        "buckets": {
            k: {"count": len(v), "pct_of_loop_stall": round(100 * len(v) / n, 2) if n else 0.0}
            for k, v in buckets.items()
        },
        "max_message_count": max((r["message_count"] for r in rows), default=0),
        "max_repeated_ai": max((r["repeated_ai"] for r in rows), default=0),
    }


def hist(values: List[int]) -> Dict[str, int]:
    return {str(k): v for k, v in sorted(Counter(values).items())}


def five_number(values: List[int]) -> Dict[str, float]:
    if not values:
        return {}
    v = sorted(values)
    def q(p):
        i = p * (len(v) - 1)
        lo, hi = int(i), min(int(i) + 1, len(v) - 1)
        return round(v[lo] + (v[hi] - v[lo]) * (i - lo), 2)
    return {"n": len(v), "min": v[0], "q1": q(0.25), "median": q(0.5),
            "q3": q(0.75), "max": v[-1],
            "mean": round(sum(v) / len(v), 2)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    sources = {
        "real": [REPO / "docs/tech_repair-conversations-anonymized.json"],
        "fixed_390": [
            REPO / "debugger-platforn/results_tech_repair_live_v4/conversations.json",
            REPO / "docs/results/simulated_runs/run_web_150tests.json",
            REPO / "docs/results/simulated_runs/run_200tests_recovered.json",
        ],
        "scale_2560": [
            REPO / f"debugger-platforn/results_scale_study/{b}/conversations.json"
            for b in ("N0010", "N0050", "N0100", "N0200", "N0400", "N0800", "N1000")
        ],
    }

    all_rows: Dict[str, List[Dict[str, Any]]] = {}
    per_file: Dict[str, Dict[str, Any]] = {}

    # REAL — production schema, scored directly.
    real_convs = load_export(sources["real"][0])
    all_rows["real"] = analyse(real_convs, "real")
    per_file[str(sources["real"][0].relative_to(REPO))] = {
        "n": len(real_convs), **attribution(all_rows["real"], "loop_stall_counted")}

    # SIM — adapted to the production schema first.
    for corpus in ("fixed_390", "scale_2560"):
        rows: List[Dict[str, Any]] = []
        for path in sources[corpus]:
            data = json.load(open(path))
            convs = [adapt_sim_conversation(c) for c in data.get("conversations", [])]
            batch = analyse(convs, f"{corpus}:{path.parent.name}/{path.name}")
            # tag raw turn-list length for the length/budget analysis
            for row, raw in zip(batch, data["conversations"]):
                row["raw_total_turns"] = raw.get("total_turns")
                row["raw_len_turns"] = len(raw.get("turns", []))
                row["loop_iterations"] = max(
                    (t.get("turn_number", 0) for t in raw.get("turns", [])), default=0)
                row["status"] = raw.get("status")
                row["outcome"] = raw.get("outcome")
                row["failure_reason"] = raw.get("failure_reason")
            rows.extend(batch)
            per_file[str(path.relative_to(REPO))] = {
                "n": len(convs), **attribution(batch, "loop_stall_counted")}
        all_rows[corpus] = rows

    results: Dict[str, Any] = {
        "scorer": "debugger-platforn/src/production/scoring.py (unmodified)",
        "adapter": "debugger-platforn/compare_real_vs_sim.py::adapt_sim_conversation",
        "min_score": MIN_SCORE,
        "predicate": "loop_stall <=> message_count > 40 OR repeated_ai >= 3  (scoring.py:235)",
        "per_file": per_file,
        "attribution_failure_gated": {
            k: attribution(v, "loop_stall_counted") for k, v in all_rows.items()},
        "attribution_category_only": {
            k: attribution(v, "loop_stall_flagged") for k, v in all_rows.items()},
    }

    # --- repetition-triggered sim flags: repeat-run distributions ---------
    for corpus in ("fixed_390", "scale_2560", "real"):
        rows = all_rows[corpus]
        rep = [r for r in rows if r["loop_stall_counted"] and r["repetition_fired"]]
        results.setdefault("repetition_distributions", {})[corpus] = {
            "n_repetition_triggered": len(rep),
            "max_identical_agent_messages (scorer signal)": {
                "histogram": hist([r["repeated_ai"] for r in rep]),
                "summary": five_number([r["repeated_ai"] for r in rep]),
            },
            "longest_consecutive_verbatim_run": {
                "histogram": hist([r["longest_consecutive_run"] for r in rep]),
                "summary": five_number([r["longest_consecutive_run"] for r in rep]),
            },
        }

    # --- conversation length: flagged vs unflagged ------------------------
    for corpus in ("fixed_390", "scale_2560", "real"):
        rows = all_rows[corpus]
        fl = [r["message_count"] for r in rows if r["loop_stall_counted"]]
        un = [r["message_count"] for r in rows if not r["loop_stall_counted"]]
        results.setdefault("length_distributions", {})[corpus] = {
            "flagged_loop_stall": {"summary": five_number(fl), "histogram": hist(fl)},
            "not_flagged": {"summary": five_number(un), "histogram": hist(un)},
            "n_over_40_messages": sum(1 for r in rows if r["message_count"] > 40),
            "n_at_exactly_40_messages": sum(1 for r in rows if r["message_count"] == 40),
        }

    # --- budget reachability check on the sim corpora ---------------------
    for corpus in ("fixed_390", "scale_2560"):
        rows = all_rows[corpus]
        results.setdefault("budget_check", {})[corpus] = {
            "max_loop_iterations_observed": max(r["loop_iterations"] for r in rows),
            "max_raw_turn_entries": max(r["raw_len_turns"] for r in rows),
            "max_adapted_message_count": max(r["message_count"] for r in rows),
            "n_hitting_20_iterations": sum(1 for r in rows if r["loop_iterations"] >= 20),
            "n_with_max_turns_exceeded_reason": sum(
                1 for r in rows if "Max turns exceeded" in (r.get("failure_reason") or "")),
            "iteration_histogram_top": dict(sorted(
                Counter(r["loop_iterations"] for r in rows).items())[-8:]),
        }

    # --- the 18-turn deflection case (200-run) ----------------------------
    two_hundred = [r for r in all_rows["fixed_390"]
                   if "run_200tests_recovered" in r["corpus"]]
    top = sorted(two_hundred, key=lambda r: -r["repeated_ai"])[:6]
    results["case_hunt_200run"] = {
        "top_repetition_conversations": [
            {k: r[k] for k in ("id", "failure_score", "failed", "categories",
                               "loop_stall_counted", "message_count",
                               "loop_iterations", "repeated_ai",
                               "longest_consecutive_run", "length_fired",
                               "repetition_fired", "outcome", "failure_reason",
                               "repeated_text_prefix")}
            for r in top],
        "loop_stall_flagged_ids": [r["id"] for r in two_hundred if r["loop_stall_counted"]],
    }

    (out / "loop_stall_attribution.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    # per-conversation dump for the flagged ones (audit trail)
    flagged_rows = [r for rows in all_rows.values() for r in rows if r["loop_stall_counted"]]
    (out / "loop_stall_flagged_conversations.json").write_text(
        json.dumps(flagged_rows, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps({k: results[k] for k in
                      ("attribution_failure_gated", "budget_check")}, indent=2))
    print(f"\nWrote {out}/loop_stall_attribution.json "
          f"({len(flagged_rows)} flagged conversations dumped)")


if __name__ == "__main__":
    main()
