"""
Experiment runner: answers RQ1-RQ4 end to end.

  RQ1 (predictive validity)  How well do synthetic failures match real
      production failures over the shared taxonomy?
  RQ2 (coverage gaps)        Which production categories does synthetic
      testing miss, and what characterises them?
  RQ3 (production feedback)  Does seeding generation with train-split real
      failures improve held-out recall vs blind generation?
  RQ4 (generation method)    Which arm achieves the best recall per unit of
      testing budget?

Two synthetic-failure modes:

  "static"   pre-execution approximation — each test contributes the failure
             categories it is *designed to detect*
             (:func:`src.evaluation.harness.infer_detectable_failures`).
             Fully offline and deterministic; measures the *targeting* of the
             suite, not observed agent behaviour.
  "execute"  runs the suite against an agent connector (mock, or a sandbox
             bridge URL), diagnoses the failures with Phase D (offline mode),
             and projects root causes onto the shared taxonomy.  This is the
             full closed loop.

Both modes are recorded in the results so numbers are never mixed silently.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.evaluation.harness import _TOOL_SCOPED_CATEGORIES, _test_tools, infer_detectable_failures
from src.evaluation.measurement import (
    bootstrap_recall_ci,
    compare_arms,
    coverage_gaps,
    per_category_validity,
    recall_vs_budget,
)
from src.evaluation.predictive_validity import ProductionSignal, compute_predictive_validity
from src.evaluation.projection import project_diagnosis_report, projection_table
from src.evaluation.taxonomy import TAXONOMY_VERSION
from src.feedback import (
    build_feedback_corpus,
    generate_blind_suite,
    generate_feedback_suite,
    verify_no_leakage,
)
from src.generator.models import TestSuite
from src.production import (
    build_ground_truth,
    load_export,
    time_split,
    to_production_signals,
)
from src.production.anonymize import get_anonymiser


@dataclass
class ExperimentConfig:
    export_path: str
    agent_map_path: str
    output_dir: str = "experiments_output"
    budget: int = 100                         # tests per arm
    budget_points: Optional[List[int]] = None  # for RQ4 curves; default 10..budget
    holdout_fraction: float = 0.3
    min_score: float = 3.0
    per_category_cap: int = 25
    rng_seed: int = 42
    mode: str = "static"                      # "static" | "execute"
    connector: str = "mock"                   # "mock" | sandbox URL (execute mode)
    language: Optional[str] = None
    seed_budget_fraction: float = 0.35
    mutations_per_seed: int = 2
    arms: List[str] = field(default_factory=lambda: ["blind", "feedback"])


# ----------------------------------------------------------------------
# Synthetic failures per test
# ----------------------------------------------------------------------


def _static_failures_per_test(suite: TestSuite) -> List[List[Dict[str, Any]]]:
    """Per-test detectable failures, in prioritised (test_number) order."""
    per_test: List[List[Dict[str, Any]]] = []
    for tc in sorted(suite.test_cases, key=lambda t: t.test_number):
        tools = sorted(_test_tools(tc)) or [None]
        failures: List[Dict[str, Any]] = []
        for category in infer_detectable_failures(tc):
            scoped = tools if category in _TOOL_SCOPED_CATEGORIES else [None]
            for tool in scoped:
                failures.append({
                    "failure_category": category.value,
                    "tool_involved": tool,
                    "example_test_id": tc.test_id,
                })
        per_test.append(failures)
    return per_test


def _executed_failures_per_test(
    suite: TestSuite,
    agent_map: Dict[str, Any],
    connector_spec: str,
    language: str,
    workdir: Path,
) -> List[List[Dict[str, Any]]]:
    """Execute the suite offline and project diagnosed failures.

    Uses AI-free personas (scripted openers) and the offline Phase D
    diagnosis so the whole loop runs without API keys.  Per-test attribution:
    each diagnosed cluster's failures are attributed to the test IDs in its
    failure examples.
    """
    from src.diagnosis.engine import DiagnosisEngine
    from src.execution.agent_connector import APIAgentConnector, MockAgentConnector
    from src.execution.aggregator import ResultsAggregator
    from src.execution.runner import TestExecutionEngine

    suite_dict = json.loads(suite.model_dump_json())

    if connector_spec == "mock":
        connector = MockAgentConnector(agent_map)
    else:
        connected_map = dict(agent_map)
        connected_map["api_endpoint"] = connector_spec
        connector = APIAgentConnector(connected_map)

    engine = TestExecutionEngine(
        test_suite=suite_dict,
        agent_connector=connector,
        max_workers=8,
        use_ai_personas=False,
        traces_dir=str(workdir / "traces"),
        language=language,
        agent_map=agent_map,
    )
    started_at = datetime.now(timezone.utc)
    results = asyncio.run(engine.run_all())

    aggregator = ResultsAggregator(suite_dict, results)
    report = aggregator.generate_report(started_at)
    inbox = aggregator.generate_failure_inbox()

    diagnosis = DiagnosisEngine(use_ai=False).diagnose(
        failure_inbox=inbox,
        test_run_report=json.loads(report.model_dump_json()),
        agent_map=agent_map,
    )
    diagnosis_dict = json.loads(diagnosis.model_dump_json())
    (workdir / "diagnosis_report.json").write_text(json.dumps(diagnosis_dict, indent=2))

    projected = project_diagnosis_report(diagnosis_dict)

    # Attribute each cluster's projected failure to its example test IDs
    failures_by_test: Dict[str, List[Dict[str, Any]]] = {}
    clusters_by_id = {c.get("cluster_id"): c for c in diagnosis_dict.get("clusters", [])}
    for failure in projected:
        cluster = clusters_by_id.get(failure.get("cluster_id")) or {}
        test_ids = [
            ex.get("test_id") for ex in cluster.get("failure_examples", []) or []
            if ex.get("test_id")
        ] or ["__unattributed__"]
        for tid in test_ids:
            failures_by_test.setdefault(tid, []).append(failure)

    ordered = sorted(suite.test_cases, key=lambda t: t.test_number)
    per_test = [failures_by_test.get(tc.test_id, []) for tc in ordered]
    # Failures whose test could not be attributed still count once, at the end
    if "__unattributed__" in failures_by_test:
        per_test.append(failures_by_test["__unattributed__"])
    return per_test


def _flatten(per_test: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    seen: set = set()
    flat: List[Dict[str, Any]] = []
    for failures in per_test:
        for f in failures:
            key = (f.get("failure_category"), f.get("tool_involved"))
            if key not in seen:
                seen.add(key)
                flat.append(f)
    return flat


# ----------------------------------------------------------------------
# Main experiment
# ----------------------------------------------------------------------


def run_experiment(config: ExperimentConfig, on_progress=None) -> Dict[str, Any]:
    """Run the full RQ1-RQ4 experiment and write artefacts to output_dir."""
    progress = on_progress or (lambda msg: None)
    out = Path(config.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # ---------- Ground truth ----------
    progress("Loading production export...")
    conversations = load_export(config.export_path)
    agent_map = json.loads(Path(config.agent_map_path).read_text())

    progress("Building ground truth from human-process signals...")
    ground_truth = build_ground_truth(conversations, min_score=config.min_score)
    train, held_out = time_split(ground_truth, holdout_fraction=config.holdout_fraction)

    all_signals = to_production_signals(ground_truth.failures)
    holdout_signals = to_production_signals(held_out)

    anonymise, anonymisation_level = get_anonymiser()
    progress(
        f"Ground truth: {len(ground_truth.failures)} failures "
        f"({len(train)} train / {len(held_out)} held-out); "
        f"anonymisation={anonymisation_level}"
    )

    # ---------- Arms ----------
    workdir = out / "work"
    workdir.mkdir(exist_ok=True)
    suites: Dict[str, TestSuite] = {}
    used_by_arm: Dict[str, set] = {}

    if "blind" in config.arms:
        progress(f"Generating blind arm ({config.budget} tests)...")
        suites["blind"] = generate_blind_suite(
            agent_map, target_count=config.budget,
            rng_seed=config.rng_seed, language=config.language,
        )
        used_by_arm["blind"] = set()

    if "feedback" in config.arms:
        progress("Building feedback seed corpus from train-split failures...")
        corpus, provenance = build_feedback_corpus(
            train, conversations,
            per_category_cap=config.per_category_cap,
            anonymise=anonymise,
        )
        progress(f"Seed corpus: {corpus.total_seeds} seeds; generating feedback arm...")
        suites["feedback"], used = generate_feedback_suite(
            agent_map, corpus, provenance,
            target_count=config.budget,
            mutations_per_seed=config.mutations_per_seed,
            rng_seed=config.rng_seed,
            language=config.language,
            seed_budget_fraction=config.seed_budget_fraction,
        )
        used_by_arm["feedback"] = used

    # ---------- Leakage guard (before any measurement) ----------
    for arm, used in used_by_arm.items():
        verify_no_leakage(used, held_out)
    progress("Leakage guard passed: no held-out conversation reached generation.")

    # ---------- Synthetic failures ----------
    failures_per_test: Dict[str, List[List[Dict[str, Any]]]] = {}
    for arm, suite in suites.items():
        progress(f"Deriving synthetic failures for arm '{arm}' (mode={config.mode})...")
        if config.mode == "execute":
            arm_dir = workdir / arm
            arm_dir.mkdir(exist_ok=True)
            failures_per_test[arm] = _executed_failures_per_test(
                suite, agent_map, config.connector,
                config.language or "Spanish", arm_dir,
            )
        else:
            failures_per_test[arm] = _static_failures_per_test(suite)

    arm_failures = {arm: _flatten(per_test) for arm, per_test in failures_per_test.items()}

    # ---------- RQ1: predictive validity (primary arm = blind) ----------
    progress("Computing RQ1 predictive validity...")
    rq1_arm = "blind" if "blind" in arm_failures else next(iter(arm_failures))
    rq1_overall = compute_predictive_validity(arm_failures[rq1_arm], all_signals)
    rq1 = {
        "arm": rq1_arm,
        "n_ground_truth_failures": len(ground_truth.failures),
        "overall": {k: rq1_overall[k] for k in ("precision", "recall", "f1",
                                                "n_synthetic_failures", "n_production_signals")},
        "recall_ci": bootstrap_recall_ci(
            [sid in set(rq1_overall["matched_signals"]) for sid in
             [s.signal_id for s in all_signals]]
        ),
        "per_category": per_category_validity(arm_failures[rq1_arm], all_signals),
    }

    # ---------- RQ2: coverage gaps ----------
    progress("Characterising RQ2 coverage gaps...")
    rq2 = {
        "arm": rq1_arm,
        "recall_threshold": 0.25,
        "gaps": coverage_gaps(
            arm_failures[rq1_arm], all_signals,
            ground_truth_failures=ground_truth.failures,
        ),
    }

    # ---------- RQ3: feedback vs blind on held-out ----------
    rq3: Dict[str, Any] = {"available": False}
    if {"blind", "feedback"} <= set(arm_failures):
        progress("Comparing feedback vs blind on held-out failures (RQ3)...")
        comparison = compare_arms(
            {arm: arm_failures[arm] for arm in ("blind", "feedback")},
            holdout_signals,
            baseline_arm="blind",
        )
        rq3 = {
            "available": True,
            "n_holdout_signals": len(holdout_signals),
            "holdout_period": {
                "start": min((f.timestamp for f in held_out if f.timestamp), default=None),
                "end": max((f.timestamp for f in held_out if f.timestamp), default=None),
            },
            "comparison": comparison,
        }

    # ---------- RQ4: recall vs budget ----------
    progress("Computing RQ4 recall-vs-budget curves...")
    budget_points = config.budget_points or [
        b for b in (5, 10, 20, 30, 50, 75, 100, 150, 200) if b <= config.budget
    ]
    rq4 = {
        "budget_points": budget_points,
        "curves": {
            arm: recall_vs_budget(per_test, holdout_signals, budget_points=budget_points)
            for arm, per_test in failures_per_test.items()
        },
        "note": "Budget unit = one test conversation; recall over held-out signals.",
    }
    # Rank arms by recall at the largest common budget
    final = {arm: curve[-1]["recall"] for arm, curve in rq4["curves"].items()}
    rq4["ranking"] = sorted(final, key=final.get, reverse=True)

    # ---------- Assemble ----------
    results: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "taxonomy_version": TAXONOMY_VERSION,
        "config": {
            **{k: getattr(config, k) for k in (
                "budget", "holdout_fraction", "min_score", "per_category_cap",
                "rng_seed", "mode", "connector", "seed_budget_fraction",
                "mutations_per_seed", "arms",
            )},
            "export_path": str(config.export_path),
            "agent_map_path": str(config.agent_map_path),
        },
        "anonymisation_level": anonymisation_level,
        "ground_truth": {
            "n_conversations_analysed": ground_truth.n_conversations_analysed,
            "n_failures": len(ground_truth.failures),
            "n_train": len(train),
            "n_holdout": len(held_out),
            "by_production_category": ground_truth.by_category,
            "by_shared_category": ground_truth.by_shared_category,
        },
        "projection": projection_table(),
        "arms": {
            arm: {
                "n_tests": len(suite.test_cases),
                "n_seed_tests": sum(
                    1 for t in suite.test_cases if t.coverage_goal == "production_seed"
                ),
                "n_synthetic_failures": len(arm_failures[arm]),
            }
            for arm, suite in suites.items()
        },
        "rq1_predictive_validity": rq1,
        "rq2_coverage_gaps": rq2,
        "rq3_production_feedback": rq3,
        "rq4_recall_vs_budget": rq4,
    }

    # ---------- Persist ----------
    results_path = out / "results.json"
    results_path.write_text(json.dumps(results, indent=2, default=str))
    (out / "ground_truth.json").write_text(
        json.dumps(ground_truth.to_dict(), indent=2, default=str)
    )
    for arm, suite in suites.items():
        (out / f"suite_{arm}.json").write_text(suite.model_dump_json(indent=2))

    progress(f"Results written to {results_path}")

    # ---------- Charts + report ----------
    try:
        from src.experiments.charts import render_charts
        chart_paths = render_charts(results, out)
        results["charts"] = [str(p) for p in chart_paths]
        results_path.write_text(json.dumps(results, indent=2, default=str))
    except Exception as e:  # charts are best-effort; results.json is the artefact
        progress(f"Chart rendering skipped: {e}")

    from src.experiments.report import write_markdown_report
    report_path = write_markdown_report(results, out)
    progress(f"Report written to {report_path}")

    return results
