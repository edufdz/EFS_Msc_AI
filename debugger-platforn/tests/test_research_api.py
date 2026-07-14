"""Tests for the /api/research routes (in-process, offline)."""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from web.api.app import app

client = TestClient(app)

AGENT_MAP = {
    "agent_id": "api-test-agent",
    "metadata": {"type": "support", "conversation_language": "Spanish"},
    "components": {
        "tools": [{"name": "get_order_status", "description": "d", "parameters": []}],
        "prompts": [],
    },
    "risk_flags": {"all_risks": []},
}


def _export(n_fail=8, n_ok=4):
    convs = []
    for i in range(n_fail):
        month = (i % 6) + 1
        convs.append({
            "id": f"fail-{i}", "status": "closed",
            "escalated_at": f"2026-{month:02d}-02T10:00:00+00:00",
            "escalation_reason": "El cliente solicitó hablar con un agente.",
            "message_count": 6,
            "created_at": f"2026-{month:02d}-01T10:00:00+00:00",
            "messages": [
                {"source": "customer", "text_body": "Estado de mi orden, correo x@y.com",
                 "created_at": f"2026-{month:02d}-01T10:00:00+00:00"},
                {"source": "ai_agent", "text_body": "Un momento",
                 "ai_confidence_score": 0.9,
                 "created_at": f"2026-{month:02d}-01T10:00:05+00:00"},
            ],
        })
    for i in range(n_ok):
        convs.append({
            "id": f"ok-{i}", "status": "closed", "message_count": 2,
            "created_at": "2026-03-01T10:00:00+00:00",
            "messages": [],
        })
    return {"exported_at": "2026-06-28", "total_conversations": len(convs),
            "total_messages": 1, "conversations": convs}


@pytest.fixture
def paths(tmp_path):
    export_path = tmp_path / "export.json"
    export_path.write_text(json.dumps(_export()))
    map_path = tmp_path / "map.json"
    map_path.write_text(json.dumps(AGENT_MAP))
    return export_path, map_path


def _wait_for_run(run_id: str, timeout: float = 120.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = client.get(f"/api/research/runs/{run_id}").json()
        if state["status"] in ("completed", "error"):
            return state
        time.sleep(0.3)
    raise TimeoutError(f"run {run_id} did not finish")


class TestProjectionEndpoint:
    def test_projection_table(self):
        resp = client.get("/api/research/projection")
        assert resp.status_code == 200
        data = resp.json()
        assert data["taxonomy_version"].startswith("1.0")
        assert len(data["categories"]) == 16
        assert len(data["production_to_shared"]) == 8


class TestGroundTruthPreview:
    def test_preview(self, paths):
        export_path, _ = paths
        resp = client.get("/api/research/ground-truth/preview",
                          params={"export_path": str(export_path)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["n_failures"] == 8
        assert data["by_category"]["resolution"] == 8
        assert len(data["worst"]) <= 10

    def test_missing_export_400(self):
        resp = client.get("/api/research/ground-truth/preview",
                          params={"export_path": "/nonexistent.json"})
        assert resp.status_code == 400


class TestExperimentRun:
    def test_full_run(self, paths, tmp_path, monkeypatch):
        import web.api.routes.research as research_module
        monkeypatch.setattr(research_module, "_EXPERIMENTS_DIR", tmp_path / "exp")

        export_path, map_path = paths
        resp = client.post("/api/research/experiments/run", json={
            "export_path": str(export_path),
            "agent_map_path": str(map_path),
            "budget": 10,
        })
        assert resp.status_code == 200
        run_id = resp.json()["run_id"]

        state = _wait_for_run(run_id)
        assert state["status"] == "completed", state.get("error")
        results = state["results"]
        assert results["rq3_production_feedback"]["available"]
        assert (tmp_path / "exp" / run_id / "results.json").exists()

        # Run appears in the registry listing
        runs = client.get("/api/research/runs").json()["runs"]
        assert any(r["run_id"] == run_id for r in runs)

    def test_bad_paths_400(self):
        resp = client.post("/api/research/experiments/run", json={
            "export_path": "/nope.json", "agent_map_path": "/nope2.json",
        })
        assert resp.status_code == 400


class TestAnonymizeRun:
    def test_anonymize(self, paths, tmp_path):
        export_path, _ = paths
        out_path = tmp_path / "anon.json"
        resp = client.post("/api/research/anonymize/run", json={
            "input_path": str(export_path),
            "output_path": str(out_path),
        })
        assert resp.status_code == 200
        state = _wait_for_run(resp.json()["run_id"])
        assert state["status"] == "completed", state.get("error")
        data = json.loads(out_path.read_text())
        text = json.dumps(data)
        assert "x@y.com" not in text
        assert all("phone_number" not in c for c in data["conversations"])
