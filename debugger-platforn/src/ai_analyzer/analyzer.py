"""
AI Semantic Analyzer using the Anthropic Claude API.
Provides deep understanding of agent purpose, tool behavior,
workflow patterns, and inter-tool dependencies.

Sprint 5: Uses call-graph-guided hierarchical summarisation instead
of flat 80K-char truncation.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import anthropic
from dotenv import load_dotenv

# Load .env file from project root (in case this module is imported directly)
project_root = Path(__file__).parent.parent.parent
load_dotenv(project_root / ".env")

from src.ai_analyzer.prompts import (
    GOAL_UNDERSTANDING_PROMPT,
    TOOL_ANALYSIS_PROMPT,
    WORKFLOW_ANALYSIS_PROMPT,
    DEPENDENCY_ANALYSIS_PROMPT,
    GUARDRAIL_EXTRACTION_PROMPT,
)
from src.ai_analyzer.code_navigator import (
    build_call_graph,
    find_relevant_subgraph,
    summarise_repository,
    assemble_context,
)
from src.analysis.static_analyzer import FileSymbols
from src.patterns.detector import ToolDefinition, PromptDefinition
from src.patterns.rule_extractor import PolicyRule, PolicyGraph

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-5-20250929"
DEFAULT_CONTEXT_BUDGET = 80_000


@dataclass
class GoalAnalysis:
    purpose: str
    domain: str
    capabilities: list[str]
    success_criteria: list[str]
    confidence: float


@dataclass
class ToolSemanticInfo:
    name: str
    purpose: str
    required_inputs: list[str]
    output: str
    read_only: bool
    handles_sensitive_data: bool
    sensitive_data_types: list[str]
    dependencies: list[str]
    risk_level: str
    preconditions: list[str] = field(default_factory=list)
    postconditions: list[str] = field(default_factory=list)
    side_effects: list[str] = field(default_factory=list)


@dataclass
class WorkflowAnalysis:
    decision_strategy: str
    typical_flow: list[str]
    error_handling: dict[str, str]
    guardrails: list[str]
    ambiguity_handling: str


@dataclass
class DependencyAnalysis:
    dependencies: list[dict]
    mutually_exclusive: list[list[str]]
    common_sequences: list[list[str]]
    circular_dependency_risks: list[str]


@dataclass
class SemanticAnalysisResult:
    goal: GoalAnalysis | None = None
    tool_semantics: list[ToolSemanticInfo] = field(default_factory=list)
    workflow: WorkflowAnalysis | None = None
    dependency_analysis: DependencyAnalysis | None = None
    guardrail_graph: PolicyGraph | None = None


def _call_llm(prompt: str, max_tokens: int = 4096) -> str:
    """Call Claude API and return the text response."""
    client = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY env var
    message = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def _parse_json_response(text: str) -> dict:
    """Parse JSON from LLM response, handling markdown fences."""
    # Strip markdown code fences if present
    text = text.strip()
    if text.startswith("```"):
        # Remove opening fence (```json or ```)
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        text = text.strip()
    return json.loads(text)


def _build_context_summary(
    all_symbols: list[FileSymbols],
    tools: list[ToolDefinition],
    prompts: list[PromptDefinition],
    entry_points: list[str],
    framework: str,
    context_budget: int = DEFAULT_CONTEXT_BUDGET,
) -> tuple[str, dict]:
    """Build a hierarchical, budget-aware context string for the LLM.

    Uses call-graph analysis to prioritise the most architecturally
    relevant functions instead of flat concatenation + truncation.

    Returns (context_string, coverage_metadata).
    """
    graph = build_call_graph(all_symbols)
    tool_names = [t.name for t in tools]
    relevant = find_relevant_subgraph(graph, entry_points, tool_names, all_symbols)
    chunks = summarise_repository(all_symbols, relevant, tools, prompts, framework)
    context, coverage = assemble_context(
        chunks, prompts, tools, entry_points, budget_chars=context_budget,
    )

    logger.info(
        "Context assembly: %d/%d functions included (%d chars of %d budget)",
        coverage["included_functions"],
        coverage["total_functions"],
        coverage["budget_used_chars"],
        coverage["budget_total_chars"],
    )

    return context, coverage


def _get_entry_point_code(all_symbols: list[FileSymbols], entry_points: list[str]) -> str:
    """Read entry point files for context."""
    for ep in entry_points:
        for sym in all_symbols:
            if sym.file_path == ep:
                # Reconstruct from functions
                parts = []
                for func in sym.functions:
                    parts.append(f"def {func.name}(...):\n  '''{func.docstring or ''}'''\n  {func.body_text[:500]}")
                for cls in sym.classes:
                    parts.append(f"class {cls.name}({', '.join(cls.bases)}):\n  '''{cls.docstring or ''}'''")
                    for m in cls.methods[:10]:
                        parts.append(f"  def {m.name}(...):\n    '''{m.docstring or ''}'''\n    {m.body_text[:300]}")
                if parts:
                    return "\n\n".join(parts)

    # Fallback: use the first file with agent-like functions
    for sym in all_symbols:
        agent_funcs = [f for f in sym.functions if "agent" in f.name.lower() or "run" in f.name.lower()]
        if agent_funcs:
            parts = []
            for func in agent_funcs:
                parts.append(f"def {func.name}(...):\n  '''{func.docstring or ''}'''\n  {func.body_text[:500]}")
            return "\n\n".join(parts)

    return "(no entry point code found)"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_goal(
    all_symbols: list[FileSymbols],
    tools: list[ToolDefinition],
    prompts: list[PromptDefinition],
    entry_points: list[str],
    framework: str,
    context_budget: int = DEFAULT_CONTEXT_BUDGET,
) -> GoalAnalysis:
    """Use LLM to understand what the agent is trying to achieve."""
    context, _cov = _build_context_summary(
        all_symbols, tools, prompts, entry_points, framework, context_budget,
    )
    prompt = GOAL_UNDERSTANDING_PROMPT.format(context=context)

    raw = _call_llm(prompt)
    data = _parse_json_response(raw)

    return GoalAnalysis(
        purpose=data.get("purpose", "Unknown"),
        domain=data.get("domain", "custom"),
        capabilities=data.get("capabilities", []),
        success_criteria=data.get("success_criteria", []),
        confidence=data.get("confidence", 0.5),
    )


def analyze_tools_semantically(
    tools: list[ToolDefinition],
    all_symbols: list[FileSymbols],
    framework: str,
) -> list[ToolSemanticInfo]:
    """Use LLM to deeply understand what each tool does."""
    if not tools:
        return []

    # Process in batches
    batch_size = 10
    results = []

    for i in range(0, len(tools), batch_size):
        batch = tools[i:i + batch_size]

        tools_json = []
        for t in batch:
            tools_json.append({
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
                "source": t.source,
                "code_snippet": (t.code_snippet or "")[:400],
            })

        context = f"Framework: {framework}, {len(all_symbols)} files analyzed."
        prompt = TOOL_ANALYSIS_PROMPT.format(
            tools=json.dumps(tools_json, indent=2),
            codebase_context=context,
        )

        raw = _call_llm(prompt)
        data = _parse_json_response(raw)

        for tool_data in data.get("tools", []):
            results.append(ToolSemanticInfo(
                name=tool_data.get("name", "unknown"),
                purpose=tool_data.get("purpose", ""),
                required_inputs=tool_data.get("required_inputs", []),
                output=tool_data.get("output", ""),
                read_only=tool_data.get("read_only", True),
                handles_sensitive_data=tool_data.get("handles_sensitive_data", False),
                sensitive_data_types=tool_data.get("sensitive_data_types", []),
                dependencies=tool_data.get("dependencies", []),
                risk_level=tool_data.get("risk_level", "low"),
                preconditions=tool_data.get("preconditions", []),
                postconditions=tool_data.get("postconditions", []),
                side_effects=tool_data.get("side_effects", []),
            ))

    return results


def analyze_workflow(
    all_symbols: list[FileSymbols],
    tools: list[ToolDefinition],
    prompts: list[PromptDefinition],
    entry_points: list[str],
    framework: str,
    context_budget: int = DEFAULT_CONTEXT_BUDGET,
) -> WorkflowAnalysis:
    """Understand the agent's decision-making and flow."""
    entry_code = _get_entry_point_code(all_symbols, entry_points)
    tool_names = [t.name for t in tools]
    prompts_json = [{"name": p.name, "content": p.content[:300]} for p in prompts[:5]]

    prompt = WORKFLOW_ANALYSIS_PROMPT.format(
        entry_point_code=entry_code[:3000],
        tool_names=json.dumps(tool_names),
        prompts=json.dumps(prompts_json, indent=2),
        framework=framework,
    )

    raw = _call_llm(prompt)
    data = _parse_json_response(raw)

    return WorkflowAnalysis(
        decision_strategy=data.get("decision_strategy", "custom"),
        typical_flow=data.get("typical_flow", []),
        error_handling=data.get("error_handling", {}),
        guardrails=data.get("guardrails", []),
        ambiguity_handling=data.get("ambiguity_handling", "unknown"),
    )


def analyze_dependencies(
    tools: list[ToolDefinition],
) -> DependencyAnalysis:
    """Use LLM to understand logical dependencies between tools."""
    if not tools:
        return DependencyAnalysis(
            dependencies=[], mutually_exclusive=[],
            common_sequences=[], circular_dependency_risks=[],
        )

    tools_json = []
    for t in tools[:15]:
        tools_json.append({
            "name": t.name,
            "description": t.description,
            "parameters": t.parameters,
            "code_snippet": (t.code_snippet or "")[:300],
        })

    prompt = DEPENDENCY_ANALYSIS_PROMPT.format(
        tools_with_code=json.dumps(tools_json, indent=2),
    )

    raw = _call_llm(prompt)
    data = _parse_json_response(raw)

    return DependencyAnalysis(
        dependencies=data.get("dependencies", []),
        mutually_exclusive=data.get("mutually_exclusive", []),
        common_sequences=data.get("common_sequences", []),
        circular_dependency_risks=data.get("circular_dependency_risks", []),
    )


def analyze_guardrails(
    prompts: list[PromptDefinition],
    tool_names: list[str],
    pattern_graph: PolicyGraph | None = None,
) -> PolicyGraph:
    """Use LLM to extract guardrail rules from prompts.

    *pattern_graph* is the offline-extracted graph (from rule_extractor).
    AI rules are merged with pattern-extracted rules, deduplicating by
    textual similarity.
    """
    if not prompts:
        return pattern_graph or PolicyGraph()

    # Truncate prompt content to avoid exceeding LLM output limits
    prompts_json = [
        {"name": p.name, "content": p.content[:2000]} for p in prompts if p.content
    ]
    prompt = GUARDRAIL_EXTRACTION_PROMPT.format(
        prompts=json.dumps(prompts_json, indent=2),
        tool_names=json.dumps(tool_names),
    )

    try:
        raw = _call_llm(prompt, max_tokens=8192)
        data = _parse_json_response(raw)
    except Exception as exc:
        logger.warning("AI guardrail extraction failed: %s — using pattern-based only", exc)
        return pattern_graph or PolicyGraph()

    # Convert AI rules to PolicyRule objects
    ai_rules: list[PolicyRule] = []
    for i, rule_data in enumerate(data.get("rules", []), start=1):
        ai_rules.append(PolicyRule(
            rule_id=f"R{i:03d}",
            text=rule_data.get("text", ""),
            category=rule_data.get("category", "requirement"),
            complexity=rule_data.get("complexity", 1),
            scope=rule_data.get("scope", "always"),
            target_tools=rule_data.get("target_tools", []),
            conditions=rule_data.get("conditions", []),
            source_prompt="ai_extraction",
            language="English",
        ))

    interactions = data.get("interactions", [])

    if not pattern_graph or not pattern_graph.rules:
        # Only AI rules — number them
        total = sum(r.complexity for r in ai_rules)
        return PolicyGraph(rules=ai_rules, edges=interactions, total_complexity=total)

    # Merge: keep pattern-extracted rules, add AI rules that aren't duplicates
    existing_texts = {r.text.lower().strip().rstrip(".") for r in pattern_graph.rules}
    merged = list(pattern_graph.rules)
    next_id = len(merged) + 1

    for ai_rule in ai_rules:
        norm = ai_rule.text.lower().strip().rstrip(".")
        if norm not in existing_texts:
            ai_rule.rule_id = f"R{next_id:03d}"
            merged.append(ai_rule)
            existing_texts.add(norm)
            next_id += 1

    total = sum(r.complexity for r in merged)
    edges = pattern_graph.edges + interactions

    return PolicyGraph(rules=merged, edges=edges, total_complexity=total)


def _validate_ai_facts(
    tool_semantics: list[ToolSemanticInfo],
    dependency_analysis: DependencyAnalysis | None,
    call_graph: "nx.DiGraph",
    all_symbols: list[FileSymbols],
) -> list[ToolSemanticInfo]:
    """Cross-check AI-derived claims against static analysis.

    Adds a ``confidence`` annotation where static evidence exists:
      - "verified"   — AI claim matches static facts
      - "unverified" — no static evidence found
      - "conflicted" — AI claim contradicts static evidence
    """
    import networkx as nx

    # Build a set of known function names for call-graph path checks
    all_func_names: set[str] = set()
    for sym in all_symbols:
        for f in sym.functions:
            all_func_names.add(f.name)
        for c in sym.classes:
            for m in c.methods:
                all_func_names.add(f"{c.name}.{m.name}")

    # Build name→keys lookup for the call graph
    name_to_keys: dict[str, list[str]] = {}
    for node, data in call_graph.nodes(data=True):
        name = data.get("name", "")
        name_to_keys.setdefault(name, []).append(node)

    # Check tool dependency claims
    if dependency_analysis:
        for dep in dependency_analysis.dependencies:
            tool_name = dep.get("tool", "")
            requires = dep.get("requires", [])
            for req in requires:
                # Check if there's a path in the call graph
                src_keys = name_to_keys.get(tool_name, [])
                tgt_keys = name_to_keys.get(req, [])
                path_found = False
                for sk in src_keys:
                    for tk in tgt_keys:
                        if sk in call_graph and tk in call_graph:
                            try:
                                if nx.has_path(call_graph, sk, tk) or nx.has_path(call_graph, tk, sk):
                                    path_found = True
                                    break
                            except nx.NetworkXError:
                                pass
                    if path_found:
                        break
                dep.setdefault("_confidence", {})[req] = "verified" if path_found else "unverified"

    # Check read_only claims against code content
    write_indicators = ["write", "save", "insert", "update", "delete", "post(", "put(", "patch("]
    for ts in tool_semantics:
        if ts.read_only:
            # Look for write indicators in the tool's code
            tool_code = ""
            for sym in all_symbols:
                for f in sym.functions:
                    if f.name == ts.name:
                        tool_code = f.body_text.lower()
                        break
            if any(ind in tool_code for ind in write_indicators):
                logger.warning(
                    "AI claims tool '%s' is read_only but code contains write indicators",
                    ts.name,
                )

    return tool_semantics


def run_semantic_analysis(
    all_symbols: list[FileSymbols],
    tools: list[ToolDefinition],
    prompts: list[PromptDefinition],
    entry_points: list[str],
    framework: str,
    context_budget: int = DEFAULT_CONTEXT_BUDGET,
) -> SemanticAnalysisResult:
    """Run all AI-powered analyses and return combined result."""
    result = SemanticAnalysisResult()

    result.goal = analyze_goal(
        all_symbols, tools, prompts, entry_points, framework, context_budget,
    )
    result.tool_semantics = analyze_tools_semantically(tools, all_symbols, framework)
    result.workflow = analyze_workflow(
        all_symbols, tools, prompts, entry_points, framework, context_budget,
    )
    result.dependency_analysis = analyze_dependencies(tools)

    # Guardrail extraction (Sprint 6) — AI pass
    tool_names = [t.name for t in tools]
    result.guardrail_graph = analyze_guardrails(prompts, tool_names)

    # LLM-fact validation (Sprint 5.5)
    call_graph = build_call_graph(all_symbols)
    result.tool_semantics = _validate_ai_facts(
        result.tool_semantics, result.dependency_analysis, call_graph, all_symbols,
    )

    return result
