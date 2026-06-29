"""Unit tests for behavioural_model.py — Sprint 8."""

import pytest

from src.graph.behavioural_model import (
    DependencyEdge,
    BehaviouralModel,
    build_dependency_graph,
    analyze_graph_properties,
    generate_coverage_targets,
    build_behavioural_model,
)


def _make_agent_map(tools=None, deps=None):
    """Helper to build a minimal agent map dict."""
    tools = tools or []
    m = {"components": {"tools": tools}}
    if deps:
        m["_raw_dependency_analysis"] = deps
    return m


class TestDependencyGraphFromToolDeps:
    def test_builds_edges_from_tool_dependencies(self):
        agent_map = _make_agent_map(tools=[
            {"name": "process_refund", "dependencies": ["check_order"], "risk_level": "critical"},
            {"name": "check_order", "dependencies": [], "risk_level": "low"},
        ])
        edges = build_dependency_graph(agent_map)
        assert len(edges) >= 1
        req_edges = [e for e in edges if e.edge_type == "requires"]
        assert any(e.source_tool == "check_order" and e.target_tool == "process_refund" for e in req_edges)

    def test_no_edges_for_independent_tools(self):
        agent_map = _make_agent_map(tools=[
            {"name": "search", "dependencies": [], "risk_level": "low"},
            {"name": "lookup", "dependencies": [], "risk_level": "low"},
        ])
        edges = build_dependency_graph(agent_map)
        assert edges == []


class TestDependencyGraphFromAI:
    def test_builds_edges_from_ai_dependencies(self):
        agent_map = _make_agent_map(
            tools=[
                {"name": "refund", "dependencies": [], "risk_level": "high"},
                {"name": "verify", "dependencies": [], "risk_level": "low"},
            ],
            deps={
                "dependencies": [
                    {"tool": "refund", "requires": ["verify"], "reason": "Must verify first"}
                ],
                "mutually_exclusive": [["search", "browse"]],
                "common_sequences": [["verify", "refund"]],
            },
        )
        edges = build_dependency_graph(agent_map)
        types = {e.edge_type for e in edges}
        assert "requires" in types
        assert "mutually_exclusive" in types
        assert "commonly_precedes" in types


class TestDependencyGraphFromPreconditions:
    def test_matches_precondition_to_postcondition(self):
        agent_map = _make_agent_map(tools=[
            {
                "name": "process_refund",
                "dependencies": [],
                "risk_level": "high",
                "preconditions": ["order status must be verified"],
                "postconditions": [],
            },
            {
                "name": "check_order",
                "dependencies": [],
                "risk_level": "low",
                "preconditions": [],
                "postconditions": ["order status is verified"],
            },
        ])
        edges = build_dependency_graph(agent_map)
        static_edges = [e for e in edges if e.evidence == "static"]
        assert len(static_edges) >= 1
        assert any(
            e.source_tool == "check_order" and e.target_tool == "process_refund"
            for e in static_edges
        )


class TestEdgeMerging:
    def test_duplicate_edges_merged(self):
        agent_map = _make_agent_map(
            tools=[
                {
                    "name": "refund", "dependencies": ["verify"], "risk_level": "high",
                    "preconditions": ["order status must be verified"],
                    "postconditions": [],
                },
                {
                    "name": "verify", "dependencies": [], "risk_level": "low",
                    "preconditions": [],
                    "postconditions": ["order status is verified"],
                },
            ],
        )
        edges = build_dependency_graph(agent_map)
        # Tool dependencies (ai_inferred) + precondition matching (static) → combined
        req_edges = [
            e for e in edges
            if e.source_tool == "verify" and e.target_tool == "refund" and e.edge_type == "requires"
        ]
        assert len(req_edges) == 1
        assert req_edges[0].evidence == "combined"


class TestGraphProperties:
    def test_detects_circular_dependency(self):
        edges = [
            DependencyEdge("A", "B", "requires", 1.0, "static"),
            DependencyEdge("B", "A", "requires", 1.0, "static"),
        ]
        tools = [{"name": "A", "risk_level": "low"}, {"name": "B", "risk_level": "low"}]
        props = analyze_graph_properties(edges, tools)
        assert len(props["circular_dependencies"]) > 0

    def test_detects_bottleneck(self):
        edges = [
            DependencyEdge("auth", "refund", "requires", 1.0, "static"),
            DependencyEdge("auth", "update", "requires", 1.0, "static"),
            DependencyEdge("auth", "delete", "requires", 1.0, "static"),
        ]
        tools = [
            {"name": "auth", "risk_level": "low"},
            {"name": "refund", "risk_level": "high"},
            {"name": "update", "risk_level": "low"},
            {"name": "delete", "risk_level": "low"},
        ]
        props = analyze_graph_properties(edges, tools)
        # auth has in-degree 0 but out-degree 3 — refund/update/delete each have in-degree 1
        # Bottleneck = nodes with in-degree >= 2
        # Actually auth→X means X depends on auth, so auth has out-degree 3
        # In the networkx digraph: edges go auth→refund, auth→update, auth→delete
        # in-degree of refund, update, delete = 1 each (< 2), auth in-degree = 0
        # No bottleneck here. Let me adjust the test.
        # A bottleneck is a tool many others depend on (high IN-degree on the target).
        # Need multiple tools pointing TO the same target.
        pass

    def test_detects_bottleneck_correctly(self):
        edges = [
            DependencyEdge("tool_a", "shared_auth", "requires", 1.0, "static"),
            DependencyEdge("tool_b", "shared_auth", "requires", 1.0, "static"),
            DependencyEdge("tool_c", "shared_auth", "requires", 1.0, "static"),
        ]
        tools = [
            {"name": "shared_auth", "risk_level": "low"},
            {"name": "tool_a", "risk_level": "low"},
            {"name": "tool_b", "risk_level": "low"},
            {"name": "tool_c", "risk_level": "low"},
        ]
        props = analyze_graph_properties(edges, tools)
        assert "shared_auth" in props["bottleneck_tools"]

    def test_detects_orphan_tools(self):
        edges = [
            DependencyEdge("A", "B", "requires", 1.0, "static"),
        ]
        tools = [
            {"name": "A", "risk_level": "low"},
            {"name": "B", "risk_level": "low"},
            {"name": "C", "risk_level": "low"},
        ]
        props = analyze_graph_properties(edges, tools)
        assert "C" in props["orphan_tools"]

    def test_longest_chain(self):
        edges = [
            DependencyEdge("A", "B", "requires", 1.0, "static"),
            DependencyEdge("B", "C", "requires", 1.0, "static"),
            DependencyEdge("C", "D", "requires", 1.0, "static"),
        ]
        tools = [{"name": n, "risk_level": "low"} for n in "ABCD"]
        props = analyze_graph_properties(edges, tools)
        assert len(props["longest_chain"]) == 4


class TestCoverageTargets:
    def test_generates_chain_coverage(self):
        model = BehaviouralModel(
            dependency_graph=[],
            graph_properties={"longest_chain": ["A", "B", "C"], "critical_paths": []},
        )
        targets = generate_coverage_targets(model)
        assert "dependency_chain_coverage" in targets
        assert ["A", "B", "C"] in targets["dependency_chain_coverage"]["chains"]

    def test_generates_negative_coverage_for_cycles(self):
        model = BehaviouralModel(
            dependency_graph=[],
            graph_properties={
                "longest_chain": [],
                "critical_paths": [],
                "circular_dependencies": [["A", "B"]],
            },
        )
        targets = generate_coverage_targets(model)
        assert "negative_coverage" in targets
        assert "circular_deps" in targets["negative_coverage"]

    def test_generates_negative_coverage_for_mutex(self):
        model = BehaviouralModel(
            dependency_graph=[
                DependencyEdge("X", "Y", "mutually_exclusive", 0.7, "ai_inferred"),
            ],
            graph_properties={"longest_chain": [], "critical_paths": []},
        )
        targets = generate_coverage_targets(model)
        assert "negative_coverage" in targets
        assert "mutually_exclusive_violations" in targets["negative_coverage"]


class TestBuildBehaviouralModel:
    def test_produces_model_without_traces(self):
        agent_map = _make_agent_map(tools=[
            {"name": "search", "dependencies": [], "risk_level": "low"},
        ])
        model = build_behavioural_model(agent_map)
        assert isinstance(model, BehaviouralModel)
        assert model.states is None
        assert model.transitions is None
        assert isinstance(model.graph_properties, dict)
        assert isinstance(model.coverage_targets, dict)
