"""Markdown results report for the predictive-validity experiment."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


def write_markdown_report(results: Dict[str, Any], out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    lines: list[str] = []
    add = lines.append

    cfg = results["config"]
    gt = results["ground_truth"]
    rq1 = results["rq1_predictive_validity"]
    rq2 = results["rq2_coverage_gaps"]
    rq3 = results["rq3_production_feedback"]
    rq4 = results["rq4_recall_vs_budget"]

    add("# Predictive-Validity Experiment Report")
    add("")
    add(f"Generated: {results['generated_at']}  ")
    add(f"Taxonomy: `{results['taxonomy_version']}`  ")
    add(f"Mode: **{cfg['mode']}**"
        + (" (pre-execution approximation — measures suite targeting, not observed behaviour)"
           if cfg["mode"] == "static" else " (executed against agent)"))
    add(f"Anonymisation: `{results['anonymisation_level']}`")
    add("")

    add("## Ground truth")
    add("")
    add(f"- Conversations analysed: **{gt['n_conversations_analysed']}**")
    add(f"- Failures (score ≥ {cfg['min_score']}): **{gt['n_failures']}** "
        f"— train {gt['n_train']} / held-out {gt['n_holdout']} "
        f"(holdout fraction {cfg['holdout_fraction']})")
    add("")
    add("| Production category | Conversations |")
    add("|---|---|")
    for cat, n in sorted(gt["by_production_category"].items(), key=lambda x: -x[1]):
        add(f"| {cat} | {n} |")
    add("")

    add("## RQ1 — Predictive validity")
    add("")
    o = rq1["overall"]
    ci = rq1["recall_ci"]
    add(f"Synthetic testing ({rq1['arm']} arm, {results['arms'][rq1['arm']]['n_tests']} tests) "
        f"vs **all** {o['n_production_signals']} production signals:")
    add("")
    add(f"- **Recall: {o['recall']:.3f}** (95% CI {ci['ci_low']:.3f}–{ci['ci_high']:.3f})")
    add(f"- **Precision: {o['precision']:.3f}**")
    add(f"- F1: {o['f1']:.3f}")
    add("")
    add("| Category | Severity | Production signals | Recall | Precision |")
    add("|---|---|---|---|---|")
    for cat, s in sorted(rq1["per_category"].items(),
                         key=lambda x: -x[1]["n_production_signals"]):
        if s["n_production_signals"] == 0:
            continue
        add(f"| {cat} | {s['severity']} | {s['n_production_signals']} "
            f"| {s['recall']:.3f} | {s['precision']:.3f} |")
    add("")

    add("## RQ2 — Coverage gaps")
    add("")
    if rq2["gaps"]:
        add(f"Categories with recall < {rq2['recall_threshold']}:")
        add("")
        for gap in rq2["gaps"]:
            add(f"### {gap['category']} (severity {gap['severity']}, "
                f"{gap['n_production_signals']} signals, recall {gap['recall']:.3f})")
            ch = gap.get("characterisation")
            if ch:
                add("")
                add(f"- {ch['n_conversations']} conversations, "
                    f"avg {ch['avg_message_count']} messages "
                    f"(long-horizon share {ch['long_horizon_share']:.0%})")
                add(f"- escalated: {ch['escalated_share']:.0%}, "
                    f"avg failure score {ch['avg_failure_score']}")
            add("")
    else:
        add("No category fell below the recall threshold.")
        add("")

    add("## RQ3 — Production feedback")
    add("")
    if rq3.get("available"):
        comp = rq3["comparison"]
        add(f"Held-out window: {rq3['holdout_period']['start']} → {rq3['holdout_period']['end']} "
            f"({rq3['n_holdout_signals']} signals). Both arms at the same budget "
            f"({cfg['budget']} tests); feedback arm seeded ONLY with train-split failures "
            f"(leakage guard passed).")
        add("")
        add("| Arm | Held-out recall | 95% CI | Precision |")
        add("|---|---|---|---|")
        for arm, s in comp["arms"].items():
            add(f"| {arm} | {s['recall']:.3f} "
                f"| {s['recall_ci']['ci_low']:.3f}–{s['recall_ci']['ci_high']:.3f} "
                f"| {s['precision']:.3f} |")
        add("")
        for name, t in comp["tests"].items():
            verdict = "significant" if t["p_value"] < 0.05 else "not significant"
            add(f"**{name}**: Δrecall = {t['delta']:+.3f}, "
                f"p = {t['p_value']:.4f} ({verdict}; sign-flip permutation, "
                f"{t['n_discordant']} discordant signals)")
        add("")
    else:
        add("Not computed (needs both blind and feedback arms).")
        add("")

    add("## RQ4 — Recall per testing budget")
    add("")
    add(f"Arm ranking at budget {cfg['budget']}: " + " > ".join(rq4["ranking"]))
    add("")
    add("| Budget | " + " | ".join(rq4["curves"].keys()) + " |")
    add("|---" * (len(rq4["curves"]) + 1) + "|")
    n_points = max(len(c) for c in rq4["curves"].values())
    for i in range(n_points):
        row = []
        budget = None
        for curve in rq4["curves"].values():
            if i < len(curve):
                budget = curve[i]["budget"]
                row.append(f"{curve[i]['recall']:.3f}")
            else:
                row.append("—")
        add(f"| {budget} | " + " | ".join(row) + " |")
    add("")

    add("## Method notes")
    add("")
    add("- Ground truth is built exclusively from human-process signals "
        "(escalations, human takeovers, delivery failures, structured intent/"
        "confidence telemetry) — no LLM judge anywhere in the criterion.")
    add("- Both failure sources are projected onto the frozen shared taxonomy "
        "(see `projection` in results.json for the full mapping tables).")
    add("- The RQ3 split is chronological: the feedback arm only ever sees "
        "failures that occurred before the held-out window.")
    if cfg["mode"] == "static":
        add("- **Static mode caveat**: synthetic failures are the categories each "
            "test is *designed to detect* (pre-execution approximation). Run with "
            "`--mode execute` against the sandboxed agent for behavioural results.")

    path = out_dir / "REPORT.md"
    path.write_text("\n".join(lines))
    return path
