"""
Sprint T — Tests for Sprint 7 (Dynamic Trace Integration / Langfuse).

Uses synthetic trace data — no live Langfuse instance needed.
"""

import pytest
from datetime import datetime

from src.traces.trace_parser import (
    TraceToolCall,
    TraceConversation,
    TraceAnalysisResult,
    parse_trace_detail,
    parse_langfuse_traces,
)
from src.traces.sequence_miner import mine_tool_sequences, mine_decision_patterns
from src.traces.comparator import compare_static_dynamic
from src.traces.langfuse_client import LangfuseTraceIngester


# ── Helpers ──

def _tc(name: str, success: bool = True, ts: str = "2025-01-01T00:00:00Z") -> TraceToolCall:
    return TraceToolCall(
        tool_name=name,
        arguments={},
        result=None,
        success=success,
        duration_ms=100.0,
        timestamp=datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"),
    )


def _conv(
    trace_id: str,
    tools: list[str],
    outcome: str = "success",
) -> TraceConversation:
    return TraceConversation(
        trace_id=trace_id,
        tool_calls=[_tc(t) for t in tools],
        tool_sequence=tools,
        total_turns=1,
        total_duration_ms=len(tools) * 100.0,
        outcome=outcome,
    )


# ── Langfuse client ──

class TestLangfuseClient:
    def test_unavailable_without_credentials(self, monkeypatch):
        """No credentials → client unavailable, methods return empty."""
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_HOST", raising=False)
        monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
        ingester = LangfuseTraceIngester(public_key="", secret_key="")
        assert not ingester.available
        assert ingester.fetch_traces() == []
        assert ingester.fetch_trace_detail("x") == {}

    def test_graceful_without_langfuse_package(self):
        """Even if credentials set but package missing, should not crash."""
        # With fake keys, it will try to import langfuse and fail gracefully
        ingester = LangfuseTraceIngester(
            public_key="fake_pk", secret_key="fake_sk", host="http://fake"
        )
        # Either available=False (import failed) or it works — either way no crash
        assert isinstance(ingester.available, bool)


# ── Trace parser ──

class TestTraceParser:
    def test_parse_trace_detail_with_tool_observations(self):
        detail = {
            "trace": {"id": "t1", "name": "test", "input": None, "output": None, "status": None},
            "observations": [
                {
                    "id": "o1", "type": "tool", "name": "search",
                    "start_time": "2025-01-01T00:00:00Z",
                    "end_time": "2025-01-01T00:00:01Z",
                    "input": {"query": "test"}, "output": {"result": "found"},
                    "metadata": {}, "status_message": None, "level": None,
                },
                {
                    "id": "o2", "type": "tool", "name": "respond",
                    "start_time": "2025-01-01T00:00:02Z",
                    "end_time": "2025-01-01T00:00:03Z",
                    "input": {}, "output": {},
                    "metadata": {}, "status_message": None, "level": None,
                },
            ],
        }
        conv = parse_trace_detail(detail)
        assert conv is not None
        assert conv.trace_id == "t1"
        assert len(conv.tool_calls) == 2
        assert conv.tool_sequence == ["search", "respond"]

    def test_parse_empty_trace(self):
        detail = {"trace": {}, "observations": []}
        conv = parse_trace_detail(detail)
        assert conv is None

    def test_parse_langfuse_traces_batch(self):
        details = [
            {
                "trace": {"id": f"t{i}", "name": "test", "input": None, "output": None, "status": None},
                "observations": [
                    {"id": "o", "type": "tool", "name": "search",
                     "start_time": "2025-01-01T00:00:00Z", "end_time": "2025-01-01T00:00:01Z",
                     "input": {}, "output": {}, "metadata": {}, "status_message": None, "level": None},
                ],
            }
            for i in range(5)
        ]
        convs = parse_langfuse_traces(details)
        assert len(convs) == 5

    def test_failure_outcome_detection(self):
        detail = {
            "trace": {"id": "t1", "name": "test", "input": None, "output": None, "status": None},
            "observations": [
                {"id": "o1", "type": "tool", "name": "search",
                 "start_time": "2025-01-01T00:00:00Z", "end_time": "2025-01-01T00:00:01Z",
                 "input": {}, "output": {}, "metadata": {},
                 "status_message": "Error: timeout", "level": "ERROR"},
            ],
        }
        conv = parse_trace_detail(detail)
        assert conv.outcome == "failure"


# ── Sequence miner ──

class TestSequenceMiner:
    def test_tool_frequency(self):
        convs = [
            _conv("t1", ["search", "respond"]),
            _conv("t2", ["search", "lookup", "respond"]),
            _conv("t3", ["search", "respond"]),
        ]
        result = mine_tool_sequences(convs)
        assert result.tool_frequency["search"] == 3
        assert result.tool_frequency["respond"] == 3
        assert result.tool_frequency["lookup"] == 1

    def test_frequent_bigrams(self):
        # Create enough conversations for threshold
        convs = [_conv(f"t{i}", ["search", "respond"]) for i in range(20)]
        result = mine_tool_sequences(convs)
        # search→respond should be frequent
        bigram_seqs = [s for s, c in result.tool_sequences if len(s) == 2]
        assert ["search", "respond"] in bigram_seqs

    def test_common_first_and_last_tools(self):
        convs = [
            _conv("t1", ["search", "respond"]),
            _conv("t2", ["search", "lookup", "respond"]),
            _conv("t3", ["search", "respond"]),
        ]
        result = mine_tool_sequences(convs)
        assert "search" in result.common_first_tools
        assert "respond" in result.common_last_tools

    def test_avg_tools_per_conversation(self):
        convs = [
            _conv("t1", ["a", "b"]),       # 2
            _conv("t2", ["a", "b", "c"]),   # 3
            _conv("t3", ["a"]),             # 1
        ]
        result = mine_tool_sequences(convs)
        assert result.avg_tools_per_conversation == 2.0

    def test_tools_not_in_static(self):
        convs = [_conv("t1", ["search", "unknown_tool"])]
        result = mine_tool_sequences(convs, static_tool_names=["search", "respond"])
        assert "unknown_tool" in result.tools_not_in_static

    def test_tools_not_in_traces(self):
        convs = [_conv("t1", ["search"])]
        result = mine_tool_sequences(convs, static_tool_names=["search", "respond"])
        assert "respond" in result.tools_not_in_traces

    def test_empty_conversations(self):
        result = mine_tool_sequences([])
        assert result.tool_frequency == {}
        assert result.avg_tools_per_conversation == 0.0

    def test_failure_patterns(self):
        # Create retry pattern (same tool repeated) correlated with failure
        convs = [_conv(f"t{i}", ["search", "search"], outcome="failure") for i in range(20)]
        convs += [_conv(f"s{i}", ["search", "respond"], outcome="success") for i in range(20)]
        result = mine_tool_sequences(convs)
        retry_patterns = [p for p in result.failure_patterns if p["sequence"] == ["search", "search"]]
        assert len(retry_patterns) >= 1
        assert retry_patterns[0]["failure_rate"] >= 0.5


class TestDecisionPatterns:
    def test_avg_length_by_outcome(self):
        convs = [
            _conv("t1", ["a", "b"], outcome="success"),
            _conv("t2", ["a", "b", "c"], outcome="success"),
            _conv("t3", ["a"], outcome="failure"),
        ]
        patterns = mine_decision_patterns(convs)
        assert patterns["avg_length_by_outcome"]["success"] == 2.5
        assert patterns["avg_length_by_outcome"]["failure"] == 1.0

    def test_retry_tools(self):
        convs = [_conv("t1", ["search", "search", "respond"])]
        patterns = mine_decision_patterns(convs)
        retry_names = [r["tool"] for r in patterns["retry_tools"]]
        assert "search" in retry_names

    def test_empty_conversations(self):
        patterns = mine_decision_patterns([])
        assert patterns["branching_points"] == []


# ── Comparator ──

class TestComparator:
    def test_tools_only_in_static(self):
        agent_map = {"components": {"tools": [
            {"name": "search"}, {"name": "respond"}, {"name": "unused_tool"},
        ]}, "graph": {"nodes": [], "edges": []}}

        result = TraceAnalysisResult(
            conversations=[], tool_frequency={"search": 10, "respond": 5},
            tool_sequences=[], tools_not_in_static=[], tools_not_in_traces=[],
            common_first_tools=[], common_last_tools=[],
            avg_tools_per_conversation=0, failure_patterns=[],
        )
        comparison = compare_static_dynamic(agent_map, result)
        assert "unused_tool" in comparison["tools_only_in_static"]

    def test_tools_only_in_traces(self):
        agent_map = {"components": {"tools": [{"name": "search"}]},
                     "graph": {"nodes": [], "edges": []}}
        result = TraceAnalysisResult(
            conversations=[], tool_frequency={"search": 10, "new_tool": 3},
            tool_sequences=[], tools_not_in_static=[], tools_not_in_traces=[],
            common_first_tools=[], common_last_tools=[],
            avg_tools_per_conversation=0, failure_patterns=[],
        )
        comparison = compare_static_dynamic(agent_map, result)
        assert "new_tool" in comparison["tools_only_in_traces"]

    def test_coverage_calculation(self):
        agent_map = {"components": {"tools": [
            {"name": "a"}, {"name": "b"}, {"name": "c"}, {"name": "d"},
        ]}, "graph": {"nodes": [], "edges": []}}
        result = TraceAnalysisResult(
            conversations=[], tool_frequency={"a": 5, "b": 3},
            tool_sequences=[], tools_not_in_static=[], tools_not_in_traces=[],
            common_first_tools=[], common_last_tools=[],
            avg_tools_per_conversation=0, failure_patterns=[],
        )
        comparison = compare_static_dynamic(agent_map, result)
        assert comparison["static_tools_coverage"] == 0.5  # 2/4


# ── CLI / API config ──

class TestConfig:
    def test_cli_use_traces_flag(self):
        import click.testing
        from analyze import main
        runner = click.testing.CliRunner()
        result = runner.invoke(main, ["--help"])
        assert "--use-traces" in result.output

    def test_api_request_has_use_traces(self):
        from web.api.models.requests import PhaseARequest
        req = PhaseARequest(session_id="test", repo_path="/tmp")
        assert req.use_traces is False
        req2 = PhaseARequest(session_id="test", repo_path="/tmp", use_traces=True)
        assert req2.use_traces is True
