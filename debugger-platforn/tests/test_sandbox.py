"""
Tests for the Sandbox Bridge subsystem (mock tools, bridge app, replay).

All tests run offline and in-process: the FastAPI app is driven through
starlette's TestClient, the replay harness through its in-process transport,
and the CLI through click's CliRunner against a tiny synthetic export.
No network calls, no LLM.
"""

from __future__ import annotations

import json
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.sandbox.bridge import create_bridge_app
from src.sandbox.mock_tools import MockToolRegistry
from src.sandbox.models import MockToolConfig, SandboxBridgeConfig
from src.sandbox.replay import (
    ReplayResult,
    fidelity_score,
    replay_batch,
    replay_conversation,
)


# ---------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------


AGENT_MAP = {
    "agent_id": "test-agent",
    "components": {
        "tools": [
            {"name": "lookupOrder", "description": "Look up a service order."},
            {"name": "shouldEscalate", "description": "Escalation check."},
            {"name": "getCustomerInfo", "description": "Customer info."},
            {"name": None, "description": "null-name tool (real maps have these)"},
            {"name": "lookupOrder", "description": "duplicate"},
        ]
    },
}


def make_config(tmp_path=None, **overrides) -> SandboxBridgeConfig:
    registry = MockToolRegistry.from_agent_map(AGENT_MAP, seed=overrides.pop("seed", 42))
    defaults = dict(
        mode="echo",
        mock_tools=[registry.get(n) for n in registry.tool_names],
        trace_dir=str(tmp_path) if tmp_path is not None else None,
        language="Spanish",
        seed=42,
    )
    defaults.update(overrides)
    return SandboxBridgeConfig(**defaults)


def make_production_conv(
    conv_id: str = "conv-1",
    escalated: bool = False,
    tool_names: list[str] | None = None,
) -> dict:
    """Minimal conversation in the TechRepair WhatsApp export schema."""
    tool_calls = [{"name": n} for n in (tool_names or [])]
    messages = [
        {"source": "customer", "text_body": "Hola, quiero saber de mi orden 12345"},
        {
            "source": "ai_agent",
            "text_body": "Recibí tu mensaje sobre tu orden. Con gusto te ayudo.",
            "ai_tool_calls": tool_calls,
        },
        {
            "source": "customer",
            "text_body": "Quiero hablar con un agente" if escalated else "Gracias",
        },
        {
            "source": "ai_agent",
            "text_body": (
                "Escalando tu caso a un agente humano (escalating)."
                if escalated
                else "Con gusto, que tengas buen día."
            ),
            "ai_tool_calls": [{"name": "shouldEscalate"}] if escalated else [],
        },
    ]
    return {
        "id": conv_id,
        "escalated_at": "2026-01-01T00:00:00Z" if escalated else None,
        "messages": messages,
    }


# ---------------------------------------------------------------
# MockToolRegistry
# ---------------------------------------------------------------


class TestMockToolRegistry:
    def test_from_agent_map_builds_mock_per_tool(self):
        registry = MockToolRegistry.from_agent_map(AGENT_MAP)
        # null-named and duplicate tools are skipped/deduped
        assert registry.tool_names == ["lookupOrder", "shouldEscalate", "getCustomerInfo"]

    def test_default_mock_echoes_arguments(self):
        registry = MockToolRegistry.from_agent_map(AGENT_MAP)
        result, injected = registry.call("lookupOrder", {"order_id": "12345"})
        assert injected is None
        assert result == {"status": "ok", "tool": "lookupOrder", "data": {"order_id": "12345"}}

    def test_error_rate_one_always_injects(self):
        registry = MockToolRegistry.from_agent_map(AGENT_MAP, error_rate=1.0, seed=7)
        for _ in range(10):
            result, injected = registry.call("lookupOrder", {})
            assert injected == "error"
            assert result["status"] == "error"

    def test_error_rate_zero_never_injects(self):
        registry = MockToolRegistry.from_agent_map(AGENT_MAP, error_rate=0.0, seed=7)
        assert all(
            registry.call("lookupOrder", {})[1] is None for _ in range(20)
        )

    def test_empty_rate_one_always_injects_empty(self):
        registry = MockToolRegistry.from_agent_map(AGENT_MAP, empty_rate=1.0)
        result, injected = registry.call("getCustomerInfo", {"x": 1})
        assert injected == "empty_response"
        assert result == {}

    def test_seeded_injection_is_deterministic(self):
        def run(seed):
            reg = MockToolRegistry.from_agent_map(AGENT_MAP, error_rate=0.5, seed=seed)
            return [reg.call("lookupOrder", {})[1] for _ in range(30)]

        assert run(123) == run(123)
        # Mid-rate injection should produce a mix of outcomes
        outcomes = set(run(123))
        assert "error" in outcomes and None in outcomes

    def test_custom_error_payload_and_variants(self):
        registry = MockToolRegistry(
            [
                MockToolConfig(
                    name="t",
                    response={"v": 0},
                    response_variants=[{"v": 1}, {"v": 2}],
                    error_payload={"boom": True},
                )
            ]
        )
        r1, _ = registry.call("t", {})
        r2, _ = registry.call("t", {})
        r3, _ = registry.call("t", {})
        assert [r1, r2, r3] == [{"v": 1}, {"v": 2}, {"v": 1}]

    def test_unregistered_tool_returns_stub(self):
        registry = MockToolRegistry()
        result, injected = registry.call("ghostTool", {"a": 1})
        assert injected is None
        assert result["unregistered"] is True


# ---------------------------------------------------------------
# Bridge (echo mode)
# ---------------------------------------------------------------


class TestBridgeEchoMode:
    @pytest.fixture()
    def client(self, tmp_path):
        app = create_bridge_app(make_config(tmp_path))
        with TestClient(app) as c:
            yield c

    def test_chat_contract_shape(self, client):
        resp = client.post("/chat", json={"message": "Hola", "session_id": None})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["response"], str) and data["response"]
        assert isinstance(data["tool_calls"], list)

    def test_session_state_persists_across_turns(self, client):
        r1 = client.post("/chat", json={"message": "Hola", "session_id": "s1"})
        r2 = client.post("/chat", json={"message": "orden 999", "session_id": "s1"})
        assert r1.status_code == r2.status_code == 200
        trace = client.get("/sessions/s1/trace").json()
        # 2 user + 2 assistant turns accumulated in one session
        assert len(trace["turns"]) == 4
        assert [t["role"] for t in trace["turns"]] == [
            "user", "assistant", "user", "assistant",
        ]

    def test_keyword_routing_order_calls_order_tool(self, client):
        resp = client.post(
            "/chat", json={"message": "Cual es el estado de mi orden 12345?", "session_id": "s2"}
        )
        names = [tc["tool_name"] for tc in resp.json()["tool_calls"]]
        assert "lookupOrder" in names

    def test_keyword_routing_escalation(self, client):
        resp = client.post(
            "/chat", json={"message": "Quiero hablar con un agente humano", "session_id": "s3"}
        )
        data = resp.json()
        names = [tc["tool_name"] for tc in data["tool_calls"]]
        assert "shouldEscalate" in names
        assert "escala" in data["response"].lower()

    def test_no_keywords_no_tool_calls(self, client):
        resp = client.post("/chat", json={"message": "Hola buenos dias", "session_id": "s4"})
        assert resp.json()["tool_calls"] == []

    def test_health(self, client):
        data = client.get("/health").json()
        assert data["status"] == "ok"
        assert data["mode"] == "echo"
        assert "lookupOrder" in data["tools"]

    def test_trace_endpoint_returns_turns_and_tool_calls(self, client):
        client.post("/chat", json={"message": "estado de orden 42", "session_id": "s5"})
        trace = client.get("/sessions/s5/trace").json()
        assert trace["session_id"] == "s5"
        assert trace["metadata"]["upstream_mode"] == "echo"
        assert len(trace["turns"]) == 2
        assert len(trace["tool_calls"]) == 1
        tc = trace["tool_calls"][0]
        assert set(tc) >= {"name", "arguments", "result", "injected_failure", "latency_ms"}
        assert tc["injected_failure"] is None

    def test_trace_endpoint_404_for_unknown_session(self, client):
        assert client.get("/sessions/nope/trace").status_code == 404

    def test_trace_jsonl_written(self, client, tmp_path):
        client.post("/chat", json={"message": "orden 77", "session_id": "s6"})
        client.post("/reset", json={"session_id": "s6"})
        trace_file = tmp_path / "sandbox_traces.jsonl"
        assert trace_file.exists()
        lines = [json.loads(l) for l in trace_file.read_text().splitlines() if l.strip()]
        record = next(t for t in lines if t["session_id"] == "s6")
        assert record["ended_at"] is not None
        assert len(record["turns"]) == 2

    def test_reset_clears_session(self, client):
        client.post("/chat", json={"message": "hola", "session_id": "s7"})
        client.post("/reset", json={"session_id": "s7"})
        assert client.get("/sessions/s7/trace").status_code == 404


class TestFailureInjectionInTrace:
    def test_injected_failure_recorded_in_trace_and_response(self, tmp_path):
        registry = MockToolRegistry.from_agent_map(AGENT_MAP, error_rate=1.0, seed=1)
        config = SandboxBridgeConfig(
            mode="echo",
            mock_tools=[registry.get(n) for n in registry.tool_names],
            trace_dir=str(tmp_path),
            seed=1,
        )
        app = create_bridge_app(config)
        with TestClient(app) as client:
            resp = client.post(
                "/chat", json={"message": "estado de mi orden 5", "session_id": "f1"}
            )
            tc = resp.json()["tool_calls"][0]
            assert tc["injected_failure"] == "error"

            trace = client.get("/sessions/f1/trace").json()
            assert trace["tool_calls"][0]["injected_failure"] == "error"
            assert trace["tool_calls"][0]["result"]["status"] == "error"


# ---------------------------------------------------------------
# Callable mode (in-process upstream)
# ---------------------------------------------------------------


class TestCallableMode:
    def test_callable_upstream_with_mock_overlay(self):
        def upstream(message: str, session_id: str | None) -> dict:
            return {
                "response": f"upstream saw: {message}",
                "tool_calls": [{"name": "lookupOrder", "arguments": {"q": message}}],
            }

        config = make_config(mode="callable", upstream_callable=upstream)
        app = create_bridge_app(config)
        with TestClient(app) as client:
            data = client.post(
                "/chat", json={"message": "hola", "session_id": "c1"}
            ).json()
            assert data["response"].startswith("upstream saw:")
            tc = data["tool_calls"][0]
            # Mock overlay replaced the result deterministically
            assert tc["result"]["tool"] == "lookupOrder"
            assert tc["injected_failure"] is None


# ---------------------------------------------------------------
# Replay harness + fidelity scoring
# ---------------------------------------------------------------


class TestReplay:
    @pytest.fixture()
    def app(self, tmp_path):
        return create_bridge_app(make_config(tmp_path))

    def test_replay_conversation_collects_turns(self, app):
        conv = make_production_conv(tool_names=["lookupOrder"])
        result = replay_conversation(app, conv)
        assert len(result.turns) == 2  # two customer messages
        assert len(result.sandbox_responses) == 2
        assert "lookupOrder" in result.sandbox_tool_names

    def test_replay_respects_max_turns(self, app):
        conv = make_production_conv()
        result = replay_conversation(app, conv, max_turns=1)
        assert len(result.turns) == 1

    def test_fidelity_score_fields_and_ranges(self, app):
        conv = make_production_conv(tool_names=["lookupOrder"])
        result = replay_conversation(app, conv)
        score = fidelity_score(conv, result)
        for key in ("response_similarity", "tool_sequence_overlap", "overall"):
            assert 0.0 <= score[key] <= 1.0, key
        assert isinstance(score["escalation_agreement"], bool)
        expected = round(
            0.5 * score["response_similarity"]
            + 0.3 * score["tool_sequence_overlap"]
            + 0.2 * (1.0 if score["escalation_agreement"] else 0.0),
            4,
        )
        assert abs(score["overall"] - expected) <= 0.0002

    def test_escalation_agreement_both_escalate(self, app):
        conv = make_production_conv(escalated=True, tool_names=["lookupOrder"])
        result = replay_conversation(app, conv)
        # Sandbox escalates: "agente" in second customer message
        assert result.escalated is True
        score = fidelity_score(conv, result)
        assert score["escalation_agreement"] is True

    def test_escalation_agreement_neither_escalates(self, app):
        conv = make_production_conv(escalated=False, tool_names=["lookupOrder"])
        result = replay_conversation(app, conv)
        assert result.escalated is False
        assert fidelity_score(conv, result)["escalation_agreement"] is True

    def test_escalation_disagreement_production_only(self, app):
        # Production escalated, but customer messages carry no escalation
        # keywords, so the echo sandbox will not escalate.
        conv = make_production_conv(escalated=True, tool_names=["lookupOrder"])
        conv["messages"][2]["text_body"] = "Sigo esperando respuesta"
        result = replay_conversation(app, conv)
        assert result.escalated is False
        assert fidelity_score(conv, result)["escalation_agreement"] is False

    def test_tool_overlap_excludes_unknown(self, app):
        conv = make_production_conv(tool_names=["unknown"])
        result = ReplayResult(conversation_id="x", session_id="x")
        score = fidelity_score(conv, result)
        # "unknown" excluded on the production side, sandbox called nothing:
        # both-empty is perfect agreement.
        assert score["tool_sequence_overlap"] == 1.0

    def test_replay_batch_summary(self, app):
        convs = [
            make_production_conv("c1", tool_names=["lookupOrder"]),
            make_production_conv("c2", escalated=True),
            make_production_conv("c3"),
        ]
        summary = replay_batch(app, convs, n=2)
        assert summary["num_conversations"] == 2
        assert 0.0 <= summary["mean_overall"] <= 1.0
        assert 0.0 <= summary["median_overall"] <= 1.0
        assert 0.0 <= summary["mean_response_similarity"] <= 1.0
        assert 0.0 <= summary["mean_tool_sequence_overlap"] <= 1.0
        assert 0.0 <= summary["escalation_agreement_rate"] <= 1.0
        assert len(summary["per_conversation"]) == 2


# ---------------------------------------------------------------
# CLI (replay subcommand, offline via CliRunner)
# ---------------------------------------------------------------


class TestCLI:
    def test_replay_command_with_synthetic_export(self, tmp_path):
        from click.testing import CliRunner

        from sandbox_bridge import cli

        agent_map_path = tmp_path / "agent_map.json"
        agent_map_path.write_text(json.dumps(AGENT_MAP), encoding="utf-8")

        export = {
            "total_conversations": 3,
            "conversations": [
                make_production_conv("c1", tool_names=["lookupOrder"]),
                make_production_conv("c2", escalated=True, tool_names=["shouldEscalate"]),
                make_production_conv("c3"),
            ],
        }
        export_path = tmp_path / "export.json"
        export_path.write_text(json.dumps(export), encoding="utf-8")
        output_path = tmp_path / "fidelity.json"

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "replay",
                "--agent-map", str(agent_map_path),
                "--export", str(export_path),
                "--mode", "echo",
                "--sample", "2",
                "--seed", "42",
                "--output", str(output_path),
            ],
        )
        assert result.exit_code == 0, result.output
        assert output_path.exists()
        report = json.loads(output_path.read_text())
        assert report["summary"]["num_conversations"] == 2
        assert 0.0 <= report["summary"]["mean_overall"] <= 1.0
        assert "Fidelity" in result.output or "fidelity" in result.output
