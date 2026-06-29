"""
Behavioural Model Layer (Sprint 8).

Builds a tool-dependency graph with typed edges and generates coverage
targets for Phase B.  When trace data is available, the FSM inference
module (``fsm_inference.py``) adds state/transition information.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class DependencyEdge:
    source_tool: str
    target_tool: str
    edge_type: str          # requires | commonly_precedes | mutually_exclusive | enables
    weight: float           # 0.0–1.0
    evidence: str           # static | ai_inferred | trace_mined | combined
    description: str = ""


@dataclass
class FSMState:
    state_id: str
    name: str
    description: str = ""
    tools_available: list[str] = field(default_factory=list)
    is_initial: bool = False
    is_terminal: bool = False


@dataclass
class FSMTransition:
    from_state: str
    to_state: str
    trigger: str            # tool name or event
    guard: str | None = None
    frequency: float = 0.0


@dataclass
class BehaviouralModel:
    dependency_graph: list[DependencyEdge] = field(default_factory=list)
    states: list[FSMState] | None = None
    transitions: list[FSMTransition] | None = None
    graph_properties: dict = field(default_factory=dict)
    coverage_targets: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Dependency graph construction
# ---------------------------------------------------------------------------

def _edges_from_ai_dependencies(agent_map: dict) -> list[DependencyEdge]:
    """Extract edges from AI-inferred dependency_analysis already in the map."""
    edges: list[DependencyEdge] = []

    # Explicit dependency_analysis (from SemanticAnalysisResult)
    deps = agent_map.get("_raw_dependency_analysis")
    if not deps:
        return edges

    for dep in deps.get("dependencies", []):
        tool = dep.get("tool", "")
        for req in dep.get("requires", []):
            edges.append(DependencyEdge(
                source_tool=req,
                target_tool=tool,
                edge_type="requires",
                weight=0.7,
                evidence="ai_inferred",
                description=dep.get("reason", f"{tool} requires {req}"),
            ))

    for pair in deps.get("mutually_exclusive", []):
        if isinstance(pair, (list, tuple)) and len(pair) >= 2:
            edges.append(DependencyEdge(
                source_tool=pair[0],
                target_tool=pair[1],
                edge_type="mutually_exclusive",
                weight=0.7,
                evidence="ai_inferred",
                description=f"{pair[0]} and {pair[1]} are mutually exclusive",
            ))

    for seq in deps.get("common_sequences", []):
        for i in range(len(seq) - 1):
            edges.append(DependencyEdge(
                source_tool=seq[i],
                target_tool=seq[i + 1],
                edge_type="commonly_precedes",
                weight=0.7,
                evidence="ai_inferred",
                description=f"{seq[i]} commonly precedes {seq[i + 1]}",
            ))

    return edges


def _edges_from_tool_dependencies(agent_map: dict) -> list[DependencyEdge]:
    """Extract edges from per-tool 'dependencies' field in the map."""
    edges: list[DependencyEdge] = []
    for tool in agent_map.get("components", {}).get("tools", []):
        name = tool.get("name", "")
        for dep in tool.get("dependencies", []):
            edges.append(DependencyEdge(
                source_tool=dep,
                target_tool=name,
                edge_type="requires",
                weight=0.7,
                evidence="ai_inferred",
                description=f"{name} depends on {dep}",
            ))
    return edges


def _edges_from_preconditions(agent_map: dict) -> list[DependencyEdge]:
    """Infer requires edges where one tool's postconditions satisfy another's preconditions."""
    edges: list[DependencyEdge] = []
    tools = agent_map.get("components", {}).get("tools", [])

    # Build postcondition → tool name index
    post_index: dict[str, str] = {}
    for tool in tools:
        for post in tool.get("postconditions", []):
            post_lower = post.lower()
            post_index[post_lower] = tool["name"]

    # Match preconditions against postconditions
    for tool in tools:
        for pre in tool.get("preconditions", []):
            pre_lower = pre.lower()
            for post_text, post_tool in post_index.items():
                if post_tool == tool["name"]:
                    continue
                # Simple word-overlap heuristic
                pre_words = set(pre_lower.split())
                post_words = set(post_text.split())
                overlap = pre_words & post_words - {"must", "be", "is", "the", "a", "an", "to"}
                if len(overlap) >= 2:
                    edges.append(DependencyEdge(
                        source_tool=post_tool,
                        target_tool=tool["name"],
                        edge_type="requires",
                        weight=1.0,
                        evidence="static",
                        description=f"{tool['name']} precondition '{pre}' satisfied by {post_tool} postcondition '{post_text}'",
                    ))

    return edges


def _edges_from_traces(trace_result) -> list[DependencyEdge]:
    """Extract edges from trace-mined sequence data."""
    edges: list[DependencyEdge] = []
    if trace_result is None:
        return edges

    n_convs = len(trace_result.conversations) if trace_result.conversations else 1

    for seq, count in trace_result.tool_sequences:
        if len(seq) == 2:
            freq = count / n_convs
            edges.append(DependencyEdge(
                source_tool=seq[0],
                target_tool=seq[1],
                edge_type="commonly_precedes",
                weight=round(min(freq, 1.0), 3),
                evidence="trace_mined",
                description=f"{seq[0]} → {seq[1]} observed {count} times",
            ))

    return edges


def _merge_edges(all_edges: list[DependencyEdge]) -> list[DependencyEdge]:
    """Deduplicate edges, combining evidence when the same pair appears from multiple sources."""
    key_map: dict[tuple[str, str, str], DependencyEdge] = {}

    for e in all_edges:
        key = (e.source_tool, e.target_tool, e.edge_type)
        if key in key_map:
            existing = key_map[key]
            existing.weight = max(existing.weight, e.weight)
            if existing.evidence != e.evidence:
                existing.evidence = "combined"
            if e.description and len(e.description) > len(existing.description):
                existing.description = e.description
        else:
            key_map[key] = DependencyEdge(
                source_tool=e.source_tool,
                target_tool=e.target_tool,
                edge_type=e.edge_type,
                weight=e.weight,
                evidence=e.evidence,
                description=e.description,
            )

    return list(key_map.values())


def build_dependency_graph(
    agent_map: dict,
    trace_result=None,
) -> list[DependencyEdge]:
    """Build a typed tool-dependency graph from all available sources."""
    all_edges: list[DependencyEdge] = []

    all_edges.extend(_edges_from_ai_dependencies(agent_map))
    all_edges.extend(_edges_from_tool_dependencies(agent_map))
    all_edges.extend(_edges_from_preconditions(agent_map))
    all_edges.extend(_edges_from_traces(trace_result))

    return _merge_edges(all_edges)


# ---------------------------------------------------------------------------
# Graph property analysis
# ---------------------------------------------------------------------------

def analyze_graph_properties(edges: list[DependencyEdge], tools: list[dict]) -> dict:
    """Compute structural properties of the dependency graph."""
    import networkx as nx

    all_tool_names = {t.get("name", "") for t in tools}

    # Build directed graph from requires + commonly_precedes edges
    g = nx.DiGraph()
    for t in tools:
        g.add_node(t.get("name", ""))

    for e in edges:
        if e.edge_type in ("requires", "commonly_precedes", "enables"):
            g.add_edge(e.source_tool, e.target_tool, weight=e.weight, edge_type=e.edge_type)

    # Circular dependencies
    cycles = list(nx.simple_cycles(g))

    # Bottleneck tools (high in-degree)
    in_deg = dict(g.in_degree())
    bottlenecks = sorted(
        [n for n, d in in_deg.items() if d >= 2],
        key=lambda n: in_deg[n],
        reverse=True,
    )

    # Orphan tools (no edges at all)
    connected = {e.source_tool for e in edges} | {e.target_tool for e in edges}
    orphans = sorted(all_tool_names - connected)

    # Longest chain (longest path in DAG; skip if cycles exist)
    longest_chain: list[str] = []
    if not cycles:
        try:
            longest_chain = list(nx.dag_longest_path(g))
        except (nx.NetworkXUnfeasible, nx.NetworkXError):
            pass

    # Critical paths: chains passing through high-risk tools
    high_risk_tools = {t["name"] for t in tools if t.get("risk_level") in ("high", "critical")}
    critical_paths: list[list[str]] = []
    if longest_chain and high_risk_tools & set(longest_chain):
        critical_paths.append(longest_chain)

    return {
        "circular_dependencies": [list(c) for c in cycles[:10]],
        "bottleneck_tools": bottlenecks[:10],
        "orphan_tools": orphans,
        "longest_chain": longest_chain,
        "critical_paths": critical_paths,
    }


# ---------------------------------------------------------------------------
# Coverage target generation
# ---------------------------------------------------------------------------

def generate_coverage_targets(model: BehaviouralModel) -> dict:
    """Generate testing coverage criteria for Phase B."""
    targets: dict = {}

    # Transition coverage (FSM)
    if model.transitions:
        targets["transition_coverage"] = {
            "total_transitions": len(model.transitions),
            "description": "Test every state transition at least once",
        }

    # Dependency chain coverage
    chains: list[list[str]] = []
    props = model.graph_properties
    if props.get("longest_chain"):
        chains.append(props["longest_chain"])
    for path in props.get("critical_paths", []):
        if path not in chains:
            chains.append(path)

    if chains:
        targets["dependency_chain_coverage"] = {
            "chains": chains,
            "description": "Test every tool dependency chain end-to-end",
        }

    # Negative coverage
    neg: dict = {}
    if props.get("circular_dependencies"):
        neg["circular_deps"] = props["circular_dependencies"]

    me_edges = [e for e in model.dependency_graph if e.edge_type == "mutually_exclusive"]
    if me_edges:
        neg["mutually_exclusive_violations"] = [
            [e.source_tool, e.target_tool] for e in me_edges
        ]

    if neg:
        neg["description"] = "Test what happens when dependency constraints are violated"
        targets["negative_coverage"] = neg

    # Path coverage
    if props.get("critical_paths"):
        targets["path_coverage"] = {
            "critical_paths": props["critical_paths"],
            "description": "Test every path through high-risk tools",
        }

    return targets


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_behavioural_model(
    agent_map: dict,
    trace_result=None,
    trace_conversations=None,
) -> BehaviouralModel:
    """Build the full behavioural model from an agent map and optional traces.

    Parameters
    ----------
    agent_map : dict
        The (partially built) agent map with components.tools, etc.
    trace_result : TraceAnalysisResult | None
        Mined trace data (Sprint 7).
    trace_conversations : list[TraceConversation] | None
        Raw parsed conversations for FSM inference.
    """
    edges = build_dependency_graph(agent_map, trace_result)
    tools = agent_map.get("components", {}).get("tools", [])
    props = analyze_graph_properties(edges, tools)

    states = None
    transitions = None

    # FSM inference from traces (optional)
    if trace_conversations:
        try:
            from src.graph.fsm_inference import infer_fsm
            states, transitions = infer_fsm(trace_conversations, agent_map)
        except Exception:
            pass  # Traces may not be available or FSM inference may fail

    model = BehaviouralModel(
        dependency_graph=edges,
        states=states,
        transitions=transitions,
        graph_properties=props,
    )

    model.coverage_targets = generate_coverage_targets(model)

    return model
