"""Integration test for the RQ1-RQ4 experiment runner (offline, synthetic data)."""

from __future__ import annotations

import json

import pytest

from src.experiments import ExperimentConfig, run_experiment


AGENT_MAP = {
    "agent_id": "exp-test-agent",
    "metadata": {"type": "support", "conversation_language": "Spanish"},
    "components": {
        "tools": [
            {"name": "get_order_status", "description": "Look up an order",
             "parameters": [{"name": "order_id", "type": "string"}]},
            {"name": "escalate_to_human", "description": "Escalate", "parameters": []},
        ],
        "prompts": [],
    },
    "risk_flags": {"all_risks": []},
}


def _conv(cid: str, month: int, escalated: bool):
    base = {
        "id": cid,
        "status": "closed",
        "escalated_at": f"2026-{month:02d}-02T10:00:00+00:00" if escalated else None,
        "escalation_reason": (
            "El cliente solicitó hablar con un agente." if escalated else None
        ),
        "is_human_handling": False,
        "taken_over_at": None,
        "message_count": 6,
        "created_at": f"2026-{month:02d}-01T10:00:00+00:00",
        "messages": [
            {"source": "customer", "text_body": "Estado de mi orden 55511122",
             "ai_intent_detected": "order_status",
             "created_at": f"2026-{month:02d}-01T10:00:00+00:00"},
            {"source": "ai_agent", "text_body": "Su orden está en proceso",
             "ai_confidence_score": 0.9,
             "created_at": f"2026-{month:02d}-01T10:00:05+00:00"},
        ],
    }
    return base


@pytest.fixture
def experiment_paths(tmp_path):
    # 12 failing + 6 clean conversations spread over 6 months
    convs = []
    for i in range(12):
        convs.append(_conv(f"fail-{i}", month=(i % 6) + 1, escalated=True))
    for i in range(6):
        convs.append(_conv(f"ok-{i}", month=(i % 6) + 1, escalated=False))
    export = {
        "exported_at": "2026-06-28", "total_conversations": len(convs),
        "total_messages": sum(len(c["messages"]) for c in convs),
        "conversations": convs,
    }
    export_path = tmp_path / "export.json"
    export_path.write_text(json.dumps(export))
    map_path = tmp_path / "agent_map.json"
    map_path.write_text(json.dumps(AGENT_MAP))
    return export_path, map_path


def test_static_experiment_end_to_end(experiment_paths, tmp_path):
    export_path, map_path = experiment_paths
    config = ExperimentConfig(
        export_path=str(export_path),
        agent_map_path=str(map_path),
        output_dir=str(tmp_path / "out"),
        budget=20,
        holdout_fraction=0.3,
        rng_seed=7,
    )
    results = run_experiment(config)

    # Ground truth found the escalated conversations
    assert results["ground_truth"]["n_failures"] == 12
    assert results["ground_truth"]["n_train"] + results["ground_truth"]["n_holdout"] == 12

    # All four RQ sections present and well-formed
    rq1 = results["rq1_predictive_validity"]
    assert 0.0 <= rq1["overall"]["recall"] <= 1.0
    assert rq1["recall_ci"]["ci_low"] <= rq1["overall"]["recall"] <= rq1["recall_ci"]["ci_high"]

    assert isinstance(results["rq2_coverage_gaps"]["gaps"], list)

    rq3 = results["rq3_production_feedback"]
    assert rq3["available"]
    assert set(rq3["comparison"]["arms"]) == {"blind", "feedback"}
    assert "feedback_vs_blind" in rq3["comparison"]["tests"]

    rq4 = results["rq4_recall_vs_budget"]
    for curve in rq4["curves"].values():
        recalls = [p["recall"] for p in curve]
        assert recalls == sorted(recalls)

    # Artefacts persisted
    out = tmp_path / "out"
    assert (out / "results.json").exists()
    assert (out / "REPORT.md").exists()
    assert (out / "ground_truth.json").exists()
    assert (out / "suite_blind.json").exists()
    assert (out / "suite_feedback.json").exists()

    # Projection tables embedded for the dissertation
    assert results["projection"]["taxonomy_version"] == results["taxonomy_version"]


def test_execute_mode_with_mock_connector(experiment_paths, tmp_path):
    export_path, map_path = experiment_paths
    config = ExperimentConfig(
        export_path=str(export_path),
        agent_map_path=str(map_path),
        output_dir=str(tmp_path / "out_exec"),
        budget=8,
        mode="execute",
        connector="mock",
        rng_seed=7,
    )
    results = run_experiment(config)
    assert results["config"]["mode"] == "execute"
    # Executed mode still yields a full RQ report
    assert results["rq3_production_feedback"]["available"]
