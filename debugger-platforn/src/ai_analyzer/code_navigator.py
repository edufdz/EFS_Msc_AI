"""
Call-graph-guided hierarchical code summarisation.

Replaces the flat 80K-char truncation with a three-level hierarchy:
  1. Project level  — framework, file count, entry points
  2. Module level   — per-file summary (classes, functions, imports)
  3. Function level — full source of relevant functions only

Functions are selected by BFS from entry points and tool definitions
through the call graph, ensuring the most architecturally-important
code is included first.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import networkx as nx

from src.analysis.static_analyzer import FileSymbols, FunctionInfo
from src.patterns.detector import ToolDefinition, PromptDefinition

logger = logging.getLogger(__name__)


@dataclass
class CodeChunk:
    level: str       # "project" | "module" | "function"
    path: str        # file path
    name: str        # function/class name or module name
    summary: str     # human-readable summary (project/module level)
    code: str        # actual source code (function level)
    relevance: float # 0.0–1.0
    char_count: int = 0

    def __post_init__(self):
        self.char_count = len(self.code) + len(self.summary)


# ---------------------------------------------------------------------------
# 5.1  Build call graph from FileSymbols
# ---------------------------------------------------------------------------

def _function_key(file_path: str, func_name: str) -> str:
    """Canonical node ID for a function."""
    return f"{file_path}::{func_name}"


def build_call_graph(all_symbols: list[FileSymbols]) -> nx.DiGraph:
    """Build a directed call graph.

    Nodes  = every function across all files.
    Edges  = from caller → callee (via FunctionInfo.calls).
    """
    g = nx.DiGraph()

    # Index: function name → list of keys (handles name collisions across files)
    name_index: dict[str, list[str]] = {}

    # Pass 1: add nodes
    for sym in all_symbols:
        for func in sym.functions:
            key = _function_key(sym.file_path, func.name)
            g.add_node(key, file=sym.file_path, name=func.name,
                       body_text=func.body_text, docstring=func.docstring or "",
                       params=[p.name for p in func.params],
                       is_async=func.is_async, decorators=func.decorators)
            name_index.setdefault(func.name, []).append(key)

        # Also index class methods
        for cls in sym.classes:
            for method in cls.methods:
                key = _function_key(sym.file_path, f"{cls.name}.{method.name}")
                g.add_node(key, file=sym.file_path, name=f"{cls.name}.{method.name}",
                           body_text=method.body_text, docstring=method.docstring or "",
                           params=[p.name for p in method.params],
                           is_async=method.is_async, decorators=method.decorators)
                name_index.setdefault(method.name, []).append(key)
                name_index.setdefault(f"{cls.name}.{method.name}", []).append(key)

    # Pass 2: add edges from calls
    for sym in all_symbols:
        for func in sym.functions:
            caller_key = _function_key(sym.file_path, func.name)
            for callee_name in func.calls:
                targets = name_index.get(callee_name, [])
                for target in targets:
                    if target != caller_key:
                        g.add_edge(caller_key, target)

        for cls in sym.classes:
            for method in cls.methods:
                caller_key = _function_key(sym.file_path, f"{cls.name}.{method.name}")
                for callee_name in method.calls:
                    targets = name_index.get(callee_name, [])
                    for target in targets:
                        if target != caller_key:
                            g.add_edge(caller_key, target)

    return g


def find_relevant_subgraph(
    graph: nx.DiGraph,
    entry_points: list[str],
    tool_functions: list[str],
    all_symbols: list[FileSymbols],
    max_nodes: int = 50,
) -> set[str]:
    """Find the set of function keys that form the 'relevant spine'.

    Starts from entry points and tool definitions, then BFS to find
    all reachable functions.  Returns at most *max_nodes* keys.
    """
    # Build seed set from entry point files and tool names
    seeds: set[str] = set()

    # Match entry point file paths → all functions in those files
    ep_set = set(entry_points)
    for node, data in graph.nodes(data=True):
        if data.get("file") in ep_set:
            seeds.add(node)

    # Match tool function names
    tool_name_set = set(tool_functions)
    for node, data in graph.nodes(data=True):
        if data.get("name") in tool_name_set:
            seeds.add(node)

    # BFS from seeds (follow both forward and backward edges)
    visited: set[str] = set()
    frontier = list(seeds)
    while frontier and len(visited) < max_nodes:
        current = frontier.pop(0)
        if current in visited:
            continue
        if current not in graph:
            continue
        visited.add(current)
        # Forward edges (callees)
        for succ in graph.successors(current):
            if succ not in visited:
                frontier.append(succ)
        # Backward edges (callers) — only from seeds
        if current in seeds:
            for pred in graph.predecessors(current):
                if pred not in visited:
                    frontier.append(pred)

    return visited


# ---------------------------------------------------------------------------
# 5.2  Hierarchical summarisation
# ---------------------------------------------------------------------------

def summarise_repository(
    all_symbols: list[FileSymbols],
    relevant_functions: set[str],
    tools: list[ToolDefinition],
    prompts: list[PromptDefinition],
    framework: str,
) -> list[CodeChunk]:
    """Produce a three-level hierarchy of CodeChunks."""
    chunks: list[CodeChunk] = []

    # --- Level 1: project ---
    tool_names = [t.name for t in tools]
    project_summary = (
        f"Framework: {framework}\n"
        f"Files analyzed: {len(all_symbols)}\n"
        f"Tools: {', '.join(tool_names) if tool_names else 'none'}\n"
        f"Prompts: {len(prompts)}\n"
    )
    chunks.append(CodeChunk(
        level="project", path="", name="project",
        summary=project_summary, code="", relevance=1.0,
    ))

    # --- Level 2: module summaries ---
    for sym in all_symbols:
        func_names = [f.name for f in sym.functions]
        class_names = [c.name for c in sym.classes]
        import_modules = [imp.module for imp in sym.imports]
        mod_summary = (
            f"File: {sym.file_path}\n"
            f"  Functions: {', '.join(func_names) if func_names else 'none'}\n"
            f"  Classes: {', '.join(class_names) if class_names else 'none'}\n"
            f"  Imports: {', '.join(import_modules[:15]) if import_modules else 'none'}\n"
        )
        chunks.append(CodeChunk(
            level="module", path=sym.file_path, name=sym.file_path,
            summary=mod_summary, code="", relevance=0.3,
        ))

    # --- Level 3: function code (only relevant functions) ---
    for sym in all_symbols:
        for func in sym.functions:
            key = _function_key(sym.file_path, func.name)
            if key in relevant_functions:
                code_text = f"def {func.name}({', '.join(p.name for p in func.params)}):\n"
                if func.docstring:
                    code_text += f'    """{func.docstring}"""\n'
                code_text += func.body_text
                chunks.append(CodeChunk(
                    level="function", path=sym.file_path, name=func.name,
                    summary="", code=code_text, relevance=0.8,
                ))

        for cls in sym.classes:
            for method in cls.methods:
                key = _function_key(sym.file_path, f"{cls.name}.{method.name}")
                if key in relevant_functions:
                    code_text = f"def {cls.name}.{method.name}({', '.join(p.name for p in method.params)}):\n"
                    if method.docstring:
                        code_text += f'    """{method.docstring}"""\n'
                    code_text += method.body_text
                    chunks.append(CodeChunk(
                        level="function", path=sym.file_path, name=f"{cls.name}.{method.name}",
                        summary="", code=code_text, relevance=0.7,
                    ))

    return chunks


# ---------------------------------------------------------------------------
# 5.3  Budget-aware context assembly
# ---------------------------------------------------------------------------

def assemble_context(
    chunks: list[CodeChunk],
    prompts: list[PromptDefinition],
    tools: list[ToolDefinition],
    entry_points: list[str],
    budget_chars: int = 80_000,
) -> tuple[str, dict]:
    """Assemble context string within *budget_chars*, never truncating mid-function.

    Priority order:
      1. Project-level summary
      2. All prompt contents
      3. Entry point function code
      4. Tool function code (sorted by risk: critical > high > medium > low)
      5. Functions called by tools (sorted by relevance)
      6. Module-level summaries for remaining files
    """
    risk_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    ep_set = set(entry_points)
    tool_name_set = {t.name for t in tools}
    tool_risk: dict[str, int] = {t.name: risk_order.get(t.risk_level, 3) for t in tools}

    # Categorise chunks
    project_chunks = [c for c in chunks if c.level == "project"]
    module_chunks = [c for c in chunks if c.level == "module"]
    func_chunks = [c for c in chunks if c.level == "function"]

    entry_func_chunks = [c for c in func_chunks if c.path in ep_set]
    tool_func_chunks = sorted(
        [c for c in func_chunks if c.name in tool_name_set],
        key=lambda c: tool_risk.get(c.name, 3),
    )
    other_func_chunks = sorted(
        [c for c in func_chunks if c.path not in ep_set and c.name not in tool_name_set],
        key=lambda c: -c.relevance,
    )

    parts: list[str] = []
    used = 0
    added_funcs: set[str] = set()  # track (path, name) to avoid double-counting
    included_counts = {"entry_point": 0, "tool_definition": 0, "tool_dependency": 0, "other": 0}
    total_functions = len(func_chunks)

    def _try_add(text: str, category: str | None = None, chunk_key: str | None = None) -> bool:
        nonlocal used
        if chunk_key and chunk_key in added_funcs:
            return False  # already included
        cost = len(text) + 1  # +1 for newline separator
        if used + cost > budget_chars:
            return False
        parts.append(text)
        used += cost
        if category:
            included_counts[category] = included_counts.get(category, 0) + 1
        if chunk_key:
            added_funcs.add(chunk_key)
        return True

    # 1. Project summary (always)
    for c in project_chunks:
        _try_add(c.summary)

    # 2. Prompts (always)
    for p in prompts:
        _try_add(f"Prompt [{p.name}] ({p.type}):\n{p.content}")

    # 3. Entry point functions
    for c in entry_func_chunks:
        _try_add(c.code, "entry_point", f"{c.path}::{c.name}")

    # 4. Tool functions by risk (skip if already added as entry point)
    for c in tool_func_chunks:
        _try_add(c.code, "tool_definition", f"{c.path}::{c.name}")

    # 5. Other relevant functions
    for c in other_func_chunks:
        _try_add(c.code, "tool_dependency", f"{c.path}::{c.name}")

    # 6. Module summaries (fill remaining budget — not counted as functions)
    for c in module_chunks:
        _try_add(c.summary)

    context = "\n".join(parts)
    included_total = sum(included_counts.values())

    coverage = {
        "total_functions": total_functions,
        "included_functions": included_total,
        "included_by_level": included_counts,
        "excluded_functions": total_functions - included_total,
        "budget_used_chars": used,
        "budget_total_chars": budget_chars,
    }

    return context, coverage
