"""
AI Semantic Analyzer using the Anthropic Claude API.
Provides deep understanding of agent purpose, tool behavior,
workflow patterns, and inter-tool dependencies.
"""

from __future__ import annotations

import json
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
)
from src.analysis.static_analyzer import FileSymbols
from src.patterns.detector import ToolDefinition, PromptDefinition


MODEL = "claude-sonnet-4-5-20250929"
MAX_CONTEXT_CHARS = 80_000  # stay well under token limits


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


def _call_llm(prompt: str) -> str:
    """Call Claude API and return the text response."""
    client = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY env var
    message = client.messages.create(
        model=MODEL,
        max_tokens=4096,
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
    entry_point_code: str,
    framework: str,
) -> str:
    """Build a compact context string for the LLM."""
    parts = []
    parts.append(f"Framework: {framework}")
    parts.append(f"Files analyzed: {len(all_symbols)}")

    # Summarise imports
    all_imports = []
    for sym in all_symbols:
        for imp in sym.imports:
            all_imports.append(imp.module)
    if all_imports:
        unique_imports = list(set(all_imports))[:30]
        parts.append(f"Key imports: {', '.join(unique_imports)}")

    # Summarise tools
    if tools:
        parts.append("\nTools found:")
        for t in tools[:20]:
            desc = (t.description or "no description")[:150]
            parts.append(f"  - {t.name}: {desc}")

    # Summarise prompts
    if prompts:
        parts.append("\nPrompts found:")
        for p in prompts[:5]:
            parts.append(f"  - {p.name} ({p.type}): {p.content[:200]}...")

    # Entry point code
    if entry_point_code:
        parts.append(f"\nEntry point code:\n{entry_point_code[:3000]}")

    context = "\n".join(parts)
    return context[:MAX_CONTEXT_CHARS]


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
) -> GoalAnalysis:
    """Use LLM to understand what the agent is trying to achieve."""
    entry_code = _get_entry_point_code(all_symbols, entry_points)
    context = _build_context_summary(all_symbols, tools, prompts, entry_code, framework)
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
            ))

    return results


def analyze_workflow(
    all_symbols: list[FileSymbols],
    tools: list[ToolDefinition],
    prompts: list[PromptDefinition],
    entry_points: list[str],
    framework: str,
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


def run_semantic_analysis(
    all_symbols: list[FileSymbols],
    tools: list[ToolDefinition],
    prompts: list[PromptDefinition],
    entry_points: list[str],
    framework: str,
) -> SemanticAnalysisResult:
    """Run all AI-powered analyses and return combined result."""
    result = SemanticAnalysisResult()

    result.goal = analyze_goal(all_symbols, tools, prompts, entry_points, framework)
    result.tool_semantics = analyze_tools_semantically(tools, all_symbols, framework)
    result.workflow = analyze_workflow(all_symbols, tools, prompts, entry_points, framework)
    result.dependency_analysis = analyze_dependencies(tools)

    return result
