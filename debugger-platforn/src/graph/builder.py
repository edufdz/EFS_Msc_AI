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
from src.patterns.rule_extractor import PolicyGraph, extract_rules_from_prompts
from src.graph.behavioural_model import build_behavioural_model, BehaviouralModel
from src.risk.analyzer import RiskFlag
from config.framework_signatures import (
    SPANISH_INDICATORS, ENGLISH_INDICATORS, PORTUGUESE_INDICATORS,
    PORTUGUESE_CHARS, SPANISH_FORMALITY_USTED, SPANISH_FORMALITY_TU,
    DOMAIN_INDICATORS, INDUSTRY_INDICATORS, CHANNEL_INDICATORS,
)


def _score_language(text: str, words: list[str], extra_chars: list[str] | None = None) -> int:
    """Count how many indicator words/chars appear in the text."""
    score = 0
    for word in words:
        score += len(re.findall(r'\b' + re.escape(word) + r'\b', text))
    for char in (extra_chars or []):
        score += text.count(char)
    return score


def _detect_language_metadata(
    prompts: list[PromptDefinition],
    guardrail_rules: list[str] | None = None,
) -> dict:
    """Detect rich language metadata from prompts and guardrail rules.

    Returns conversation languages, primary language, guardrail language,
    mismatch flag, code-switching detection, Spanish formality, and confidence.
    """
    all_text = " ".join(p.content for p in prompts if p.content).lower()
    spanish_chars = ["¿", "¡", "ñ", "á", "é", "í", "ó", "ú", "ü"]

    if not all_text.strip():
        return {
            "conversation_languages": ["English"],
            "primary_language": "English",
            "guardrail_language": "English",
            "language_mismatch": False,
            "code_switching_detected": False,
            "spanish_formality": None,
            "confidence": 0.5,
        }

    # Score each language
    spanish_score = _score_language(all_text, SPANISH_INDICATORS, spanish_chars)
    english_score = _score_language(all_text, ENGLISH_INDICATORS)
    portuguese_score = _score_language(all_text, PORTUGUESE_INDICATORS, PORTUGUESE_CHARS)

    scores = {"Spanish": spanish_score, "English": english_score, "Portuguese": portuguese_score}

    # Detected languages (threshold ≥ 3)
    languages = [lang for lang, score in scores.items() if score >= 3] or ["English"]

    # Primary = highest scoring
    primary = max(scores, key=scores.get)  # type: ignore[arg-type]
    if scores[primary] < 3:
        primary = "English"

    # Code-switching: ≥ 2 languages each scoring ≥ 3 (same threshold as detection)
    code_switching = sum(1 for s in scores.values() if s >= 3) >= 2

    # Spanish formality
    spanish_formality = None
    if "Spanish" in languages:
        usted_score = _score_language(all_text, SPANISH_FORMALITY_USTED)
        tu_score = _score_language(all_text, SPANISH_FORMALITY_TU)
        if usted_score > 0 and tu_score > 0:
            spanish_formality = "mixed"
        elif usted_score > 0:
            spanish_formality = "usted"
        elif tu_score > 0:
            spanish_formality = "tú"

    # Guardrail language detection
    guardrail_text = " ".join(guardrail_rules or []).lower()
    if guardrail_text.strip():
        gr_spanish = _score_language(guardrail_text, SPANISH_INDICATORS, spanish_chars)
        gr_english = _score_language(guardrail_text, ENGLISH_INDICATORS)
        guardrail_language = "Spanish" if gr_spanish > gr_english else "English"
    else:
        guardrail_language = primary

    # Confidence based on total signal strength
    total_score = sum(scores.values())
    confidence = round(min(total_score / 20, 1.0), 2)

    return {
        "conversation_languages": languages,
        "primary_language": primary,
        "guardrail_language": guardrail_language,
        "language_mismatch": guardrail_language != primary,
        "code_switching_detected": code_switching,
        "spanish_formality": spanish_formality,
        "confidence": confidence,
    }


def _detect_domain_metadata(
    tools: list[ToolDefinition],
    prompts: list[PromptDefinition],
) -> dict:
    """Detect domain, industry, and channel from tool names and prompt content."""
    all_text = " ".join(
        [t.name or "" for t in tools]
        + [t.description or "" for t in tools]
        + [p.content or "" for p in prompts]
    ).lower()

    def _best_match(indicators: dict[str, list[str]]) -> str | None:
        best_key, best_score = None, 0
        for key, keywords in indicators.items():
            score = sum(all_text.count(kw) for kw in keywords)
            if score > best_score:
                best_key, best_score = key, score
        return best_key if best_score > 0 else None

    return {
        "type": _best_match(DOMAIN_INDICATORS),
        "industry": _best_match(INDUSTRY_INDICATORS),
        "channel": _best_match(CHANNEL_INDICATORS),
        "detected_from": "tool_names_and_prompts",
    }


def _extract_langgraph_topology(
    all_symbols: list[FileSymbols],
) -> list[tuple[str, str, str]]:
    """Extract LangGraph edges from addNode/addEdge/addConditionalEdges calls.

    Returns a list of (source, target, relationship) tuples using
    the LangGraph node names (not function names).
    """
    edges: list[tuple[str, str, str]] = []

    for symbols in all_symbols:
        path_lower = symbols.file_path.lower()
        if "builder" not in path_lower and "graph" not in path_lower:
            continue

        try:
            with open(symbols.file_path, encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            continue

        # .addEdge(START, "event_detector") or .addEdge("status", "response")
        for m in re.finditer(
            r'\.addEdge\s*\(\s*(?:START|["\'](\w+)["\'])\s*,\s*(?:END|["\'](\w+)["\'])\s*\)',
            content,
        ):
            src = m.group(1) or "__start__"
            tgt = m.group(2) or "__end__"
            edges.append((src, tgt, "flows_to"))

        # .addConditionalEdges("router", routeByIntent, ["status", "support", ...])
        for m in re.finditer(
            r'\.addConditionalEdges\s*\(\s*["\'](\w+)["\']\s*,\s*\w+\s*,\s*\[(.*?)\]',
            content,
            re.DOTALL,
        ):
            src = m.group(1)
            targets_str = m.group(2)
            targets = re.findall(r'["\'](\w+)["\']', targets_str)
            for tgt in targets:
                edges.append((src, tgt, "routes_to"))

    return edges


def build_architecture_graph(
    pattern_result: PatternResult,
    ai_result: SemanticAnalysisResult | None,
    all_symbols: list[FileSymbols] | None = None,
) -> nx.DiGraph:
    """
    Construct a directed graph representing the agent architecture.
    Nodes = components (agent, orchestrator, tools, memory, retrieval).
    Edges = relationships (uses, requires, feeds, flows_to, routes_to).
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

    # --- Try LangGraph topology extraction first ---
    lg_edges = _extract_langgraph_topology(all_symbols or [])

    # Build LangGraph node name → addNode mapping by parsing
    # .addNode("name", functionRef) patterns
    lg_name_to_func: dict[str, str] = {}
    for symbols in (all_symbols or []):
        path_lower = symbols.file_path.lower()
        if "builder" not in path_lower and "graph" not in path_lower:
            continue
        try:
            with open(symbols.file_path, encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            continue
        for m in re.finditer(r'\.addNode\s*\(\s*["\'](\w+)["\']\s*,\s*(\w+)', content):
            lg_name_to_func[m.group(1)] = m.group(2)

    # Map tool function names → tool IDs
    tool_name_to_id: dict[str, str] = {}
    for tool in pattern_result.tools:
        tid = f"tool_{tool.id}"
        tool_name_to_id[tool.name] = tid
        tool_name_to_id[tool.name.lower()] = tid

    # Map LangGraph node names → tool IDs via the function reference
    lg_node_to_tool: dict[str, str] = {}
    for lg_name, func_name in lg_name_to_func.items():
        if func_name in tool_name_to_id:
            lg_node_to_tool[lg_name] = tool_name_to_id[func_name]
        elif func_name.lower() in tool_name_to_id:
            lg_node_to_tool[lg_name] = tool_name_to_id[func_name.lower()]

    # Track which tools are part of the LangGraph state machine
    lg_tool_ids: set[str] = set(lg_node_to_tool.values())

    if lg_edges:
        # Add all tool nodes
        for tool in pattern_result.tools:
            tid = f"tool_{tool.id}"
            g.add_node(tid, type="tool", name=tool.name,
                       description=tool.description or "",
                       source=tool.source, risk_level=tool.risk_level)

        def _resolve_lg_node(name: str) -> str:
            """Resolve a LangGraph node name to a graph node ID."""
            if name == "__start__":
                return "orchestrator"
            if name == "__end__":
                return "agent"
            # First: check if this LG node maps to a known tool
            if name in lg_node_to_tool:
                return lg_node_to_tool[name]
            # Direct tool match
            if name in tool_name_to_id:
                return tool_name_to_id[name]
            if name.lower() in tool_name_to_id:
                return tool_name_to_id[name.lower()]
            # Create a standalone graph node
            nid = f"node_{name}"
            if nid not in g:
                g.add_node(nid, type="graph_node", name=name)
            return nid

        # Add LangGraph edges
        for src, tgt, rel in lg_edges:
            src_id = _resolve_lg_node(src)
            tgt_id = _resolve_lg_node(tgt)
            g.add_edge(src_id, tgt_id, relationship=rel)

        # Tools NOT in the LangGraph flow are helpers — connect to orchestrator
        for tool in pattern_result.tools:
            tid = f"tool_{tool.id}"
            if tid not in lg_tool_ids and not any(True for _ in g.predecessors(tid)):
                g.add_edge("orchestrator", tid, relationship="invokes")

    else:
        # Fallback: flat orchestrator → tool layout
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
    ai = ai_semantics or {}

    # Merge preconditions: union of static (code) and AI-extracted, deduplicated
    preconditions = list(dict.fromkeys(
        tool.preconditions + ai.get("preconditions", [])
    ))
    # Postconditions: primarily from AI (not reliably extractable from code)
    postconditions = list(dict.fromkeys(ai.get("postconditions", [])))
    # Side-effects: union of code-detected and AI-extracted
    side_effects = list(dict.fromkeys(
        tool.side_effects + ai.get("side_effects", [])
    ))
    # state_modifying: code-detected flag is ground truth when side-effects found
    ai_read_only = ai.get("read_only", True)
    if tool.side_effects:
        # Code found write indicators — trust static analysis
        state_modifying = True
    elif ai:
        state_modifying = not ai_read_only
    else:
        state_modifying = tool.state_modifying

    return {
        "id": tool.id,
        "name": tool.name,
        "description": ai.get("purpose", tool.description),
        "parameters": tool.parameters,
        "dependencies": deps,
        "sandbox_safe": tool.sandbox_safe,
        "risk_level": ai.get("risk_level", tool.risk_level),
        "read_only": not state_modifying,
        "handles_sensitive_data": ai.get("handles_sensitive_data", False),
        "source": tool.source,
        "confidence": tool.confidence,
        "location": tool.location,
        "preconditions": preconditions,
        "postconditions": postconditions,
        "side_effects": side_effects,
        "state_modifying": state_modifying,
    }


def generate_agent_map(
    all_symbols: list[FileSymbols],
    pattern_result: PatternResult,
    ai_result: SemanticAnalysisResult | None,
    risks: list[RiskFlag],
    entry_points: list[str],
    root_path: str,
    taint_flows: list | None = None,
    trace_result: object | None = None,
) -> dict:
    """
    Generate the final Agent Map v1 JSON structure.
    """
    graph = build_architecture_graph(pattern_result, ai_result, all_symbols)

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
                "preconditions": ts.preconditions,
                "postconditions": ts.postconditions,
                "side_effects": ts.side_effects,
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
    # Taint flows (Sprint 4)
    taint_flows_output = []
    for tf in (taint_flows or []):
        taint_flows_output.append({
            "source": tf.source.description,
            "sink": tf.sink.description,
            "path": tf.path,
            "data_types": tf.data_types,
            "risk_level": tf.risk_level,
            "taxonomy_ids": tf.taxonomy_ids,
        })

    risk_flags = {
        "pii_handling": len(pii_risks) > 0,
        "critical_actions": list(set(critical_actions)),
        "taint_flows": taint_flows_output,
        "all_risks": [
            {
                "tool": r.tool,
                "risk_type": r.risk_type,
                "pii_type": r.pii_type,
                "severity": r.severity,
                "description": r.description,
                "mitigation": r.mitigation,
                "location": r.location,
                "taxonomy_ids": r.taxonomy_ids,
                "taxonomy_names": r.taxonomy_names,
            }
            for r in risks
        ],
    }

    # Risk summary grouped by taxonomy ID
    taxonomy_counts: dict[str, dict] = {}
    for r in risks:
        for tid, tname in zip(r.taxonomy_ids, r.taxonomy_names):
            if tid not in taxonomy_counts:
                taxonomy_counts[tid] = {"count": 0, "name": tname}
            taxonomy_counts[tid]["count"] += 1

    severity_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    highest_severity = max(
        (r.severity for r in risks),
        key=lambda s: severity_order.get(s, 0),
        default="none",
    )
    risk_summary = {
        "by_taxonomy": taxonomy_counts,
        "highest_severity": highest_severity,
        "total_risks": len(risks),
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

    # Guardrail extraction (Sprint 6)
    tool_names = [t.name for t in pattern_result.tools]
    pattern_guardrails = extract_rules_from_prompts(pattern_result.prompts, tool_names)

    # Merge with AI-extracted guardrails if available
    if ai_result and ai_result.guardrail_graph and ai_result.guardrail_graph.rules:
        ai_gr = ai_result.guardrail_graph
        # Merge AI rules into pattern-extracted graph (deduplicate)
        existing = {r.text.lower().strip().rstrip(".") for r in pattern_guardrails.rules}
        merged_rules = list(pattern_guardrails.rules)
        next_id = len(merged_rules) + 1
        for r in ai_gr.rules:
            norm = r.text.lower().strip().rstrip(".")
            if norm not in existing:
                r.rule_id = f"R{next_id:03d}"
                merged_rules.append(r)
                existing.add(norm)
                next_id += 1
        guardrail_graph = PolicyGraph(
            rules=merged_rules,
            edges=pattern_guardrails.edges + ai_gr.edges,
            total_complexity=sum(r.complexity for r in merged_rules),
        )
    else:
        guardrail_graph = pattern_guardrails

    # Build guardrails output
    by_category: dict[str, int] = {}
    for r in guardrail_graph.rules:
        by_category[r.category] = by_category.get(r.category, 0) + 1

    # Detect guardrail language
    all_rule_text = " ".join(r.text for r in guardrail_graph.rules)
    rule_languages = [r.language for r in guardrail_graph.rules]
    guardrail_lang = max(set(rule_languages), key=rule_languages.count) if rule_languages else "English"

    guardrails_output = {
        "rules": [
            {
                "rule_id": r.rule_id,
                "text": r.text,
                "category": r.category,
                "complexity": r.complexity,
                "scope": r.scope,
                "target_tools": r.target_tools,
                "conditions": r.conditions,
                "source_prompt": r.source_prompt,
                "language": r.language,
            }
            for r in guardrail_graph.rules
        ],
        "interactions": guardrail_graph.edges,
        "total_rules": len(guardrail_graph.rules),
        "total_complexity": guardrail_graph.total_complexity,
        "by_category": by_category,
    }

    # Language & domain metadata (Sprint 9)
    guardrail_rule_texts = [r.text for r in guardrail_graph.rules]
    language_metadata = _detect_language_metadata(pattern_result.prompts, guardrail_rule_texts)
    domain_metadata = _detect_domain_metadata(pattern_result.tools, pattern_result.prompts)

    # Add guardrail language mismatch detection (Sprint 6.6)
    guardrails_output["guardrail_language"] = guardrail_lang
    guardrails_output["guardrail_language_matches_conversation"] = (
        guardrail_lang == language_metadata.get("primary_language", "English")
    )

    agent_map = {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "agent_id": str(uuid.uuid4()),
        "metadata": {
            "name": "Agent",
            "type": goal.get("domain", "custom"),
            "framework": pattern_result.framework,
            "framework_confidence": pattern_result.framework_confidence,
            "language": language_metadata,
            "programming_language": "python",
            "purpose": goal.get("purpose", "Unknown – run with AI analysis for details"),
            "capabilities": goal.get("capabilities", []),
            "conversation_language": language_metadata["primary_language"],
            "domain": domain_metadata,
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
        "guardrails": guardrails_output,
        "risk_flags": risk_flags,
        "risk_summary": risk_summary,
        "graph": _graph_to_dict(graph),
        "source_files": {
            "analyzed_files": files_analyzed,
            "entry_points": entry_points,
            "repository": root_path,
        },
    }

    # Trace analysis (Sprint 7) — optional
    if trace_result is not None:
        from src.traces.comparator import compare_static_dynamic
        comparison = compare_static_dynamic(agent_map, trace_result)
        agent_map["trace_analysis"] = {
            "traces_ingested": len(trace_result.conversations),
            "tool_frequency": trace_result.tool_frequency,
            "common_sequences": [
                {"sequence": seq, "count": count}
                for seq, count in trace_result.tool_sequences[:20]
            ],
            "mutually_exclusive_tools": [
                seq for seq, count in trace_result.tool_sequences
                # This is handled by TraceAnalysisResult itself; use
                # the comparison data instead for mutual exclusion
            ] if False else [],
            "tools_not_in_static": trace_result.tools_not_in_static,
            "tools_not_in_traces": trace_result.tools_not_in_traces,
            "failure_patterns": trace_result.failure_patterns[:10],
            "avg_tools_per_conversation": trace_result.avg_tools_per_conversation,
            "comparison": comparison,
        }

        # Enrich graph with trace-observed edges (Sprint 7.7)
        for seq, count in trace_result.tool_sequences:
            if len(seq) == 2:
                src_id = f"tool_{seq[0].lower().replace(' ', '_')}"
                tgt_id = f"tool_{seq[1].lower().replace(' ', '_')}"
                # Add to graph output if both nodes exist
                existing_nodes = {n["id"] for n in agent_map["graph"]["nodes"]}
                if src_id in existing_nodes and tgt_id in existing_nodes:
                    agent_map["graph"]["edges"].append({
                        "source": src_id,
                        "target": tgt_id,
                        "relationship": "commonly_precedes",
                        "weight": count,
                        "observed_in_traces": True,
                    })

    # Behavioural model (Sprint 8)
    # Pass raw dependency analysis for edge extraction
    if ai_result and ai_result.dependency_analysis:
        agent_map["_raw_dependency_analysis"] = {
            "dependencies": [
                {"tool": d.get("tool", ""), "requires": d.get("requires", []), "reason": d.get("reason", "")}
                for d in (ai_result.dependency_analysis.dependencies or [])
            ] if hasattr(ai_result.dependency_analysis, "dependencies") else [],
            "mutually_exclusive": ai_result.dependency_analysis.mutually_exclusive or [],
            "common_sequences": ai_result.dependency_analysis.common_sequences or [],
        }

    trace_conversations = None
    if trace_result is not None and hasattr(trace_result, "conversations"):
        trace_conversations = trace_result.conversations

    bm = build_behavioural_model(agent_map, trace_result, trace_conversations)

    # Remove temporary key
    agent_map.pop("_raw_dependency_analysis", None)

    # Serialise behavioural model
    bm_output: dict = {
        "dependency_graph": {
            "edges": [
                {
                    "source_tool": e.source_tool,
                    "target_tool": e.target_tool,
                    "edge_type": e.edge_type,
                    "weight": e.weight,
                    "evidence": e.evidence,
                    "description": e.description,
                }
                for e in bm.dependency_graph
            ],
            "properties": bm.graph_properties,
        },
        "coverage_targets": bm.coverage_targets,
    }

    if bm.states is not None:
        bm_output["fsm"] = {
            "states": [
                {
                    "state_id": s.state_id,
                    "name": s.name,
                    "description": s.description,
                    "tools_available": s.tools_available,
                    "is_initial": s.is_initial,
                    "is_terminal": s.is_terminal,
                }
                for s in bm.states
            ],
            "transitions": [
                {
                    "from_state": t.from_state,
                    "to_state": t.to_state,
                    "trigger": t.trigger,
                    "guard": t.guard,
                    "frequency": t.frequency,
                }
                for t in (bm.transitions or [])
            ],
        }

    agent_map["behavioural_model"] = bm_output

    return agent_map
