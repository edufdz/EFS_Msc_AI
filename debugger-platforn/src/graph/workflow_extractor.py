"""
LangGraph Workflow Extraction.
Recovers the agent's actual state machine (nodes + edges) from StateGraph
wiring calls — addNode / addEdge / addConditionalEdges — in TypeScript,
JavaScript, or Python sources.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from src.analysis.static_analyzer import FileSymbols

START = "__start__"
END = "__end__"

_NODE_RE = re.compile(r"\.\s*addNode\(\s*[\"']([\w.-]+)[\"']\s*(?:,\s*(\w+))?")
_EDGE_RE = re.compile(
    r"\.\s*addEdge\(\s*(START|[\"'][\w.-]+[\"'])\s*,\s*(END|[\"'][\w.-]+[\"'])"
)
_COND_RE = re.compile(
    r"\.\s*addConditionalEdges\(\s*[\"']([\w.-]+)[\"']\s*,\s*\w+\s*,\s*\[([^\]]*)\]",
    re.DOTALL,
)
_TARGET_RE = re.compile(r"[\"']([\w.-]+)[\"']|\b(END)\b")

# Python spelling: add_node / add_edge / add_conditional_edges
_PY_NODE_RE = re.compile(r"\.\s*add_node\(\s*[\"']([\w.-]+)[\"']\s*(?:,\s*(\w+))?")
_PY_EDGE_RE = re.compile(
    r"\.\s*add_edge\(\s*(START|[\"'][\w.-]+[\"'])\s*,\s*(END|[\"'][\w.-]+[\"'])"
)


@dataclass
class WorkflowGraph:
    """The agent's state machine as declared in its graph builder."""
    nodes: list[dict] = field(default_factory=list)  # {name, handler}
    edges: list[dict] = field(default_factory=list)  # {source, target, conditional}
    source_file: str | None = None


def _endpoint(token: str) -> str:
    token = token.strip()
    if token == "START":
        return START
    if token == "END":
        return END
    return token.strip("\"'")


def _parse_source(content: str) -> tuple[list[dict], list[dict]]:
    nodes, edges, seen_edges = [], [], set()

    for m in list(_NODE_RE.finditer(content)) + list(_PY_NODE_RE.finditer(content)):
        nodes.append({"name": m.group(1), "handler": m.group(2)})

    for m in list(_EDGE_RE.finditer(content)) + list(_PY_EDGE_RE.finditer(content)):
        src, tgt = _endpoint(m.group(1)), _endpoint(m.group(2))
        if (src, tgt) not in seen_edges:
            seen_edges.add((src, tgt))
            edges.append({"source": src, "target": tgt, "conditional": False})

    for m in _COND_RE.finditer(content):
        src = m.group(1)
        for t in _TARGET_RE.finditer(m.group(2)):
            tgt = _endpoint(t.group(1) or t.group(2))
            if (src, tgt) not in seen_edges:
                seen_edges.add((src, tgt))
                edges.append({"source": src, "target": tgt, "conditional": True})

    return nodes, edges


def extract_workflow(all_symbols: list[FileSymbols]) -> WorkflowGraph | None:
    """Scan analyzed files for StateGraph wiring and return the state machine.

    The file with the most addNode calls is taken as the graph definition
    (agents keep the wiring in a single builder module).
    """
    best: WorkflowGraph | None = None

    for symbols in all_symbols:
        path = symbols.file_path.replace("\\", "/")
        low = path.lower()
        if any(t in low for t in ("__tests__", ".test.", ".spec.", "node_modules")):
            continue
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            continue
        if "addNode" not in content and "add_node" not in content:
            continue

        nodes, edges = _parse_source(content)
        if not nodes:
            continue
        if best is None or len(nodes) > len(best.nodes):
            best = WorkflowGraph(nodes=nodes, edges=edges, source_file=path)

    return best


# ── Effect detection ────────────────────────────────────────────────────────
# Agents like this one inline side effects in graph nodes instead of exposing
# LLM-callable tools. These heuristics recover that action surface: database
# reads/writes, calls into external service modules, and delegations to nodes
# defined in other pipelines.

_DB_FROM_RE = re.compile(r"\.from\(\s*[\"']([\w.]+)[\"']\s*\)")
_DB_OPS = ("select", "insert", "update", "upsert", "delete")
_DB_WRITE_OPS = ("insert", "update", "upsert", "delete")

_NAMED_IMPORT_RE = re.compile(
    r"import\s*(?:type\s*)?\{([^}]*)\}\s*from\s*[\"']([^\"']+)[\"']"
)
# Modules that hold prompts/config/types/logging — not action surfaces
_NOISE_MODULE_RE = re.compile(
    r"/(prompts?|models?|state|types?|config|constants?)(/|$)"
    r"|llm-factory|llm-usage|llm-tracker|supabase-logger|style-guide"
)
_NOISE_NAME_RE = re.compile(
    r"^(log[A-Z_]|track[A-Z]|extractUsage$|getSupabaseClient$"
    r"|requireSupabaseClient$|getAppId$)"
)

_TS_EXTS = (".ts", ".tsx", ".js", ".mjs")


def _try_module_file(base: str) -> str | None:
    for ext in _TS_EXTS:
        if os.path.isfile(base + ext):
            return base + ext
    idx = os.path.join(base, "index.ts")
    return idx if os.path.isfile(idx) else None


def _resolve_import_file(name: str, source_file: str) -> str | None:
    """Best-effort: find the file that exports `name`, following the import in
    source_file. Handles relative paths and the common `@/` root alias by
    walking ancestor directories until the module path exists."""
    try:
        with open(source_file, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return None
    m = re.search(
        rf"import\s*(?:type\s*)?\{{[^}}]*\b{re.escape(name)}\b[^}}]*\}}\s*from\s*[\"']([^\"']+)[\"']",
        content,
    )
    if not m:
        return None
    module = m.group(1)
    base_dir = os.path.dirname(source_file)
    if module.startswith("."):
        return _try_module_file(os.path.normpath(os.path.join(base_dir, module)))
    mod = module[2:] if module.startswith("@/") else module
    d = base_dir
    while True:
        found = _try_module_file(os.path.join(d, mod))
        if found:
            return found
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def _is_internal_module(module: str, root_path: str) -> bool:
    """True if an import stays inside the analyzed agent directory."""
    if module.startswith("."):
        return True
    mod = module[2:] if module.startswith("@/") else module
    segs = [s for s in root_path.replace("\\", "/").split("/") if s]
    for k in range(1, min(5, len(segs)) + 1):
        prefix = "/".join(segs[-k:])
        if mod == prefix or mod.startswith(prefix + "/"):
            return True
    return False


def _db_effects(content: str) -> list[dict]:
    effects, seen = [], set()
    for m in _DB_FROM_RE.finditer(content):
        table = m.group(1)
        window = content[m.end():m.end() + 300]
        ops = [op for op in _DB_OPS if f".{op}(" in window] or ["select"]
        for op in ops:
            etype = "db_write" if op in _DB_WRITE_OPS else "db_read"
            key = (etype, table, op)
            if key not in seen:
                seen.add(key)
                effects.append({"type": etype, "target": table, "operation": op})
    return effects


def _external_call_effects(content: str, root_path: str) -> list[dict]:
    effects, seen = [], set()
    for m in _NAMED_IMPORT_RE.finditer(content):
        names_blob, module = m.group(1), m.group(2)
        if _is_internal_module(module, root_path) or _NOISE_MODULE_RE.search(module):
            continue
        for raw in names_blob.split(","):
            name = raw.replace("type ", "").strip()
            if not name or not name[0].islower() or _NOISE_NAME_RE.search(name):
                continue
            if not re.search(rf"\b{re.escape(name)}\s*\(", content[m.end():]):
                continue
            etype = "delegation" if name.endswith("Node") else "external_call"
            key = (etype, name)
            if key not in seen:
                seen.add(key)
                effects.append({"type": etype, "target": name, "module": module})
    return effects


def map_node_effects(
    workflow: WorkflowGraph,
    all_symbols: list[FileSymbols],
    root_path: str,
) -> tuple[dict[str, list[dict]], list[dict]]:
    """Identify each workflow node's side effects, plus DB effects in the rest
    of the analyzed files (context assembly, event handlers, metrics...).

    Returns (node_effects, runtime_effects):
      node_effects   — {node_name: [{type, target, ...}]}
      runtime_effects — [{type, target, operation, file}] outside node handlers
    """
    handler_files: dict[str, str] = {}
    for symbols in all_symbols:
        for func in symbols.functions:
            handler_files.setdefault(func.name, symbols.file_path)

    node_effects: dict[str, list[dict]] = {}
    handler_paths: set[str] = set()
    for node in workflow.nodes:
        handler = node.get("handler")
        if not handler:
            continue
        path = handler_files.get(handler)
        if not path and workflow.source_file:
            # Handler imported from outside the analyzed directory (e.g. a
            # node reused from another pipeline) — resolve it via the import.
            path = _resolve_import_file(handler, workflow.source_file)
        if not path:
            continue
        handler_paths.add(path)
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            continue
        effects = _db_effects(content) + _external_call_effects(content, root_path)
        if effects:
            node_effects[node["name"]] = effects

    runtime_effects: list[dict] = []
    seen_runtime = set()
    for symbols in all_symbols:
        path = symbols.file_path
        low = path.lower().replace("\\", "/")
        if path in handler_paths:
            continue
        if any(t in low for t in ("__tests__", ".test.", ".spec.", "node_modules")):
            continue
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            continue
        for eff in _db_effects(content):
            key = (eff["type"], eff["target"], eff["operation"])
            if key not in seen_runtime:
                seen_runtime.add(key)
                runtime_effects.append({**eff, "file": path})

    return node_effects, runtime_effects


def map_node_tools(
    workflow: WorkflowGraph,
    all_symbols: list[FileSymbols],
    tool_names: list[str],
) -> dict[str, list[str]]:
    """For each workflow node, find which detected tools its handler file references.

    Returns {node_name: [tool_name, ...]}. A node's handler function is located
    among the parsed symbols; the handler's whole source file is searched for
    tool-name references (tools are called deterministically inside nodes).
    """
    handler_files: dict[str, str] = {}
    for symbols in all_symbols:
        for func in symbols.functions:
            handler_files.setdefault(func.name, symbols.file_path)

    node_tools: dict[str, list[str]] = {}
    for node in workflow.nodes:
        handler = node.get("handler")
        if not handler or handler not in handler_files:
            continue
        try:
            with open(handler_files[handler], encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            continue
        used = [t for t in tool_names if t and re.search(rf"\b{re.escape(t)}\b", content)]
        if used:
            node_tools[node["name"]] = used

    return node_tools
