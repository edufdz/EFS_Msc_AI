"""
Graph Construction & Agent Map Output.
Builds the agent architecture graph using NetworkX and produces
the structured Agent Map JSON.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

import networkx as nx

from src.analysis.static_analyzer import FileSymbols
from src.patterns.detector import (
    PatternResult, ToolDefinition, PromptDefinition, MemorySystem,
)
from src.ai_analyzer.analyzer import SemanticAnalysisResult
from src.risk.analyzer import RiskFlag


def _detect_conversation_language(prompts: list[PromptDefinition]) -> str:
    """Detect whether the agent's prompts are in Spanish or English.

    Analyzes prompt content for Spanish language indicators and returns
    "Spanish" or "English" accordingly.
    """
    spanish_words = [
        "bienvenido", "hola", "servicio", "cliente", "ayuda",
        "cita", "gracias", "precio", "disponible", "nombre",
        "correo", "telefono", "teléfono", "dirección", "direccion",
        "consulta", "reserva", "horario", "vehículo", "vehiculo",
        "comprar", "vender", "necesita", "puede", "favor",
        "información", "informacion", "asistente", "agente",
        "buenos días", "buenas tardes", "por favor",
        "lo siento", "cómo", "cuándo", "dónde", "qué",
    ]
    spanish_chars = ["¿", "¡", "ñ", "á", "é", "í", "ó", "ú", "ü"]

    all_text = " ".join(p.content for p in prompts if p.content).lower()

    if not all_text.strip():
        return "English"

    spanish_score = 0
    for word in spanish_words:
        spanish_score += len(re.findall(r'\b' + re.escape(word) + r'\b', all_text))
    for char in spanish_chars:
        spanish_score += all_text.count(char)

    return "Spanish" if spanish_score >= 3 else "English"


def build_architecture_graph(
    pattern_result: PatternResult,
    ai_result: SemanticAnalysisResult | None,
) -> nx.DiGraph:
    """
    Construct a directed graph representing the agent architecture.
    Nodes = components (agent, orchestrator, tools, memory, retrieval).
    Edges = relationships (uses, requires, feeds).
    """
    g = nx.DiGraph()

    # Root: Agent node
    purpose = ""
    domain = ""
    if ai_result and ai_result.goal:
        purpose = ai_result.goal.purpose
        domain = ai_result.goal.domain

    g.add_node("agent", type="agent", framework=pattern_result.framework,
               purpose=purpose, domain=domain)

    # Orchestrator
    strategy = "unknown"
    if ai_result and ai_result.workflow:
        strategy = ai_result.workflow.decision_strategy
    g.add_node("orchestrator", type="orchestrator", strategy=strategy)
    g.add_edge("agent", "orchestrator", relationship="contains")

    # Planner (if plan-and-execute)
    if strategy == "plan-and-execute":
        g.add_node("planner", type="planner")
        g.add_edge("orchestrator", "planner", relationship="delegates")

    # Tools
    dep_lookup: dict[str, list[str]] = {}
    if ai_result and ai_result.dependency_analysis:
        for dep in ai_result.dependency_analysis.dependencies:
            dep_lookup[dep.get("tool", "")] = dep.get("requires", [])

    for tool in pattern_result.tools:
        tid = f"tool_{tool.id}"
        g.add_node(tid, type="tool", name=tool.name,
                   description=tool.description or "",
                   source=tool.source, risk_level=tool.risk_level)
        g.add_edge("orchestrator", tid, relationship="invokes")

        # Tool-to-tool dependencies
        requires = dep_lookup.get(tool.name, [])
        for req_name in requires:
            req_id = f"tool_{req_name.lower().replace(' ', '_')}"
            if req_id not in g:
                g.add_node(req_id, type="tool", name=req_name)
            g.add_edge(req_id, tid, relationship="requires")

    # Memory subsystem
    if pattern_result.memory_systems:
        g.add_node("memory", type="memory_subsystem")
        g.add_edge("agent", "memory", relationship="uses")
        for i, mem in enumerate(pattern_result.memory_systems):
            mid = f"memory_{mem.type}_{i}"
            g.add_node(mid, type="memory", memory_type=mem.type,
                       implementation=mem.implementation)
            g.add_edge("memory", mid, relationship="contains")

    # Retrieval subsystem
    vector_stores = [m for m in pattern_result.memory_systems if m.type == "vector_store"]
    if vector_stores:
        g.add_node("retrieval", type="retrieval_subsystem")
        g.add_edge("agent", "retrieval", relationship="uses")
        for i, vs in enumerate(vector_stores):
            rid = f"retrieval_{vs.implementation}_{i}"
            g.add_node(rid, type="retrieval", implementation=vs.implementation)
            g.add_edge("retrieval", rid, relationship="contains")

    return g


def _graph_to_dict(g: nx.DiGraph) -> dict:
    """Convert NetworkX graph to serialisable dict."""
    nodes = []
    for nid, data in g.nodes(data=True):
        nodes.append({"id": nid, **data})

    edges = []
    for src, tgt, data in g.edges(data=True):
        edges.append({"source": src, "target": tgt, **data})

    return {"nodes": nodes, "edges": edges}


def _tool_to_dict(tool: ToolDefinition, ai_semantics: dict | None, deps: list[str]) -> dict:
    return {
        "id": tool.id,
        "name": tool.name,
        "description": (ai_semantics or {}).get("purpose", tool.description),
        "parameters": tool.parameters,
        "dependencies": deps,
        "sandbox_safe": tool.sandbox_safe,
        "risk_level": (ai_semantics or {}).get("risk_level", tool.risk_level),
        "read_only": (ai_semantics or {}).get("read_only", True),
        "handles_sensitive_data": (ai_semantics or {}).get("handles_sensitive_data", False),
        "source": tool.source,
        "confidence": tool.confidence,
        "location": tool.location,
    }


def generate_agent_map(
    all_symbols: list[FileSymbols],
    pattern_result: PatternResult,
    ai_result: SemanticAnalysisResult | None,
    risks: list[RiskFlag],
    entry_points: list[str],
    root_path: str,
) -> dict:
    """
    Generate the final Agent Map v1 JSON structure.
    """
    graph = build_architecture_graph(pattern_result, ai_result)

    # Build semantic lookup
    semantic_lookup: dict[str, dict] = {}
    if ai_result and ai_result.tool_semantics:
        for ts in ai_result.tool_semantics:
            semantic_lookup[ts.name] = {
                "purpose": ts.purpose,
                "required_inputs": ts.required_inputs,
                "output": ts.output,
                "read_only": ts.read_only,
                "handles_sensitive_data": ts.handles_sensitive_data,
                "sensitive_data_types": ts.sensitive_data_types,
                "dependencies": ts.dependencies,
                "risk_level": ts.risk_level,
            }

    # Dependency lookup
    dep_lookup: dict[str, list[str]] = {}
    if ai_result and ai_result.dependency_analysis:
        for dep in ai_result.dependency_analysis.dependencies:
            dep_lookup[dep.get("tool", "")] = dep.get("requires", [])

    # Build tools list
    tools_output = []
    for tool in pattern_result.tools:
        sem = semantic_lookup.get(tool.name)
        deps = dep_lookup.get(tool.name, [])
        tools_output.append(_tool_to_dict(tool, sem, deps))

    # Workflow info
    workflow_info = {}
    if ai_result and ai_result.workflow:
        wf = ai_result.workflow
        workflow_info = {
            "type": wf.decision_strategy,
            "error_handling": wf.error_handling,
            "guardrails": wf.guardrails,
            "typical_flow": wf.typical_flow,
            "ambiguity_handling": wf.ambiguity_handling,
        }
    else:
        workflow_info = {
            "type": "unknown",
            "error_handling": {},
            "guardrails": [],
            "typical_flow": [],
            "ambiguity_handling": "unknown",
        }

    # Memory info
    memory_info = {
        "systems": [
            {"type": m.type, "implementation": m.implementation, "location": m.location}
            for m in pattern_result.memory_systems
        ],
        "conversation_history": any(
            m.type == "conversation_buffer" for m in pattern_result.memory_systems
        ),
        "persistent_state": any(
            m.type == "persistent_state" for m in pattern_result.memory_systems
        ),
    }

    # Retrieval info
    vs_systems = [m for m in pattern_result.memory_systems if m.type == "vector_store"]
    retrieval_info = {
        "systems": [
            {"type": m.type, "implementation": m.implementation, "location": m.location}
            for m in vs_systems
        ],
        "exists": len(vs_systems) > 0,
    }

    # Prompts
    prompts_output = [
        {
            "name": p.name,
            "type": p.type,
            "content": p.content[:2000],
            "variables": p.variables,
            "location": p.location,
        }
        for p in pattern_result.prompts
    ]

    # Risks
    pii_risks = [r for r in risks if r.risk_type == "pii"]
    critical_actions = [r.tool for r in risks if r.severity == "critical" and r.tool]
    risk_flags = {
        "pii_handling": len(pii_risks) > 0,
        "critical_actions": list(set(critical_actions)),
        "all_risks": [
            {
                "tool": r.tool,
                "risk_type": r.risk_type,
                "pii_type": r.pii_type,
                "severity": r.severity,
                "description": r.description,
                "mitigation": r.mitigation,
                "location": r.location,
            }
            for r in risks
        ],
    }

    # Goal metadata
    goal = {}
    if ai_result and ai_result.goal:
        goal = {
            "purpose": ai_result.goal.purpose,
            "domain": ai_result.goal.domain,
            "capabilities": ai_result.goal.capabilities,
            "confidence": ai_result.goal.confidence,
        }

    # Files analyzed
    files_analyzed = [s.file_path for s in all_symbols]

    agent_map = {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "agent_id": str(uuid.uuid4()),
        "metadata": {
            "name": "Agent",
            "type": goal.get("domain", "custom"),
            "framework": pattern_result.framework,
            "framework_confidence": pattern_result.framework_confidence,
            "language": "python",
            "purpose": goal.get("purpose", "Unknown – run with AI analysis for details"),
            "capabilities": goal.get("capabilities", []),
            "conversation_language": _detect_conversation_language(pattern_result.prompts),
        },
        "components": {
            "orchestrator": workflow_info,
            "tools": tools_output,
            "memory": memory_info,
            "retrieval": retrieval_info,
            "prompts": prompts_output,
        },
        "success_criteria": {
            "task_completion": (
                ai_result.goal.success_criteria if ai_result and ai_result.goal else []
            ),
            "max_latency_ms": 10000,
            "max_cost_per_conversation": 1.00,
            "max_turns": 20,
        },
        "risk_flags": risk_flags,
        "graph": _graph_to_dict(graph),
        "source_files": {
            "analyzed_files": files_analyzed,
            "entry_points": entry_points,
            "repository": root_path,
        },
    }

    return agent_map
