"""Tests for the sensitivity sweep (offline, tiny fixture)."""

from __future__ import annotations

import json

import pytest

from src.experiments import ExperimentConfig
from src.experiments.sensitivity import run_sensitivity

AGENT_MAP = {
    "agent_id": "sens-test-agent",
    "metadata": {"type": "support", "conversation_language": "Spanish"},
    "components": {
        "tools": [{"name": "get_order_status", "description": "d", "parameters": []}],
        "prompts": [],
    },
    "risk_flags": {"all_risks": []},
}


def _conv(cid, month, escalated):
    return {
        "id": cid, "status": "closed",
        "escalated_at": f"2026-{month:02d}-02T10:00:00+00:00" if escalated else None,
        "escalation_reason": "El cliente solicitó hablar con un agente." if escalated else None,
        "message_count": 6,
        "created_at": f"2026-{month:02d}-01T10:00:00+00:00",
        "messages": [
            {"source": "customer", "text_body": "Estado de mi orden",
             "created_at": f"2026-{month:02d}-01T10:00:00+00:00"},
            {"source": "ai_agent", "text_body": "Un momento", "ai_confidence_score": 0.9,
             "created_at": f"2026-{month:02d}-01T10:00:05+00:00"},
        ],
    }


@pytest.fixture
def paths(tmp_path):
    convs = [_conv(f"fail-{i}", (i % 6) + 1, True) for i in range(12)]
    convs += [_conv(f"ok-{i}", (i % 6) + 1, False) for i in range(4)]
    export_path = tmp_path / "export.json"
    export_path.write_text(json.dumps({
        "exported_at": "x", "total_conversations": len(convs),
        "total_messages": 2, "conversations": convs,
    }))
    map_path = tmp_path / "map.json"
    map_path.write_text(json.dumps(AGENT_MAP))
    return export_path, map_path


def test_sweep_produces_summary_and_artifacts(paths, tmp_path):
    export_path, map_path = paths
    base = ExperimentConfig(
        export_path=str(export_path),
        agent_map_path=str(map_path),
        output_dir="ignored",
        budget=10,
        rng_seed=7,
    )
    out = tmp_path / "sens"
    summary = run_sensitivity(
        base,
        sweeps={"rng_seed": [7, 8], "min_score": [3.0, 5.0]},
        output_dir=out,
    )
    # baseline + seed 8 + min_score 5.0 (defaults 7 / 3.0 are skipped as duplicates)
    assert summary["n_configurations"] == 3
    params = {(r["param"], r["value"]) for r in summary["rows"]}
    assert ("baseline", "default") in params
    assert ("rng_seed", 8) in params and ("min_score", 5.0) in params
    assert ("rng_seed", 7) not in params  # duplicate of baseline

    for row in summary["rows"]:
        assert 0.0 <= row["rq1_recall"] <= 1.0
        if "delta" in row:
            assert 0.0 <= row["p_value"] <= 1.0

    assert (out / "sensitivity.json").exists()
    assert (out / "SENSITIVITY.md").exists()
    md = (out / "SENSITIVITY.md").read_text()
    assert "Verdict" in md and "baseline" in md


def test_sweep_forces_static_two_arm_mode(paths, tmp_path):
    export_path, map_path = paths
    base = ExperimentConfig(
        export_path=str(export_path),
        agent_map_path=str(map_path),
        output_dir="ignored",
        budget=8,
        mode="execute",                       # must be overridden to static
        arms=["blind", "feedback", "naive_llm"],  # LLM arm must be dropped
    )
    summary = run_sensitivity(
        base, sweeps={}, output_dir=tmp_path / "s2",
    )
    assert summary["n_configurations"] == 1
    run_dir = (tmp_path / "s2" / "runs" / "baseline_default")
    results = json.loads((run_dir / "results.json").read_text())
    assert results["config"]["mode"] == "static"
    assert set(results["config"]["arms"]) == {"blind", "feedback"}
