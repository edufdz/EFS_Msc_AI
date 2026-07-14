"""
Hierarchical code tree of the analyzed agent (Phase A).

Turns the flat Phase A artefacts (per-file symbols, tools, prompts, risks,
entry points) into one nested structure that mirrors how the agent's
codebase is actually built:

    repository
    └── directories …
        └── files  (language, entry-point flag, tool/prompt/risk badges)
            └── classes
                └── methods  (params, async, line)
            └── functions   (params, async, line, tool implementation link)

Every directory rolls up counts (files, classes, functions, tools, prompts,
risks, max risk severity) so a UI can summarise a collapsed subtree at a
glance.  The tree is pure data — JSON-serialisable, no behaviour — and is
embedded in the agent map as ``code_tree``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from src.analysis.static_analyzer import FileSymbols

_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}

# Attach a tool to a specific symbol when its recorded line falls within
# this distance of the symbol's definition line (tool locations usually
# point at the definition itself; small offsets absorb decorators).
_TOOL_LINE_TOLERANCE = 2


def _relpath(file_path: str, root_path: str) -> str:
    try:
        return str(Path(file_path).resolve().relative_to(Path(root_path).resolve()))
    except (ValueError, OSError):
        return file_path.lstrip("/")


def _max_severity(a: Optional[str], b: Optional[str]) -> Optional[str]:
    if not a:
        return b
    if not b:
        return a
    return a if _SEVERITY_RANK.get(a, 0) >= _SEVERITY_RANK.get(b, 0) else b


def _function_node(fn: Any, kind: str, file_tools: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Node for a function or method, linking the tool it implements."""
    tool_name = None
    for tool in file_tools:
        line = (tool.get("location") or {}).get("line")
        same_name = tool.get("name", "").lower() == fn.name.lower()
        same_line = line is not None and abs(line - fn.location.line) <= _TOOL_LINE_TOLERANCE
        if same_name or same_line:
            tool_name = tool.get("name")
            break
    node: Dict[str, Any] = {
        "name": fn.name,
        "type": kind,
        "line": fn.location.line,
        "params": [p.name for p in fn.params],
    }
    if fn.is_async:
        node["is_async"] = True
    if fn.docstring:
        node["doc"] = fn.docstring.strip().splitlines()[0][:160]
    if tool_name:
        node["implements_tool"] = tool_name
    return node


def _file_node(
    rel: str,
    symbols: Optional[FileSymbols],
    file_tools: List[Dict[str, Any]],
    file_prompts: List[Dict[str, Any]],
    file_risks: List[Dict[str, Any]],
    is_entry_point: bool,
) -> Dict[str, Any]:
    children: List[Dict[str, Any]] = []
    n_functions = 0
    n_classes = 0

    if symbols is not None:
        for cls in symbols.classes:
            n_classes += 1
            methods = [_function_node(m, "method", file_tools) for m in cls.methods]
            n_functions += len(methods)
            children.append({
                "name": cls.name,
                "type": "class",
                "line": cls.location.line,
                "bases": cls.bases,
                **({"doc": cls.docstring.strip().splitlines()[0][:160]} if cls.docstring else {}),
                "children": sorted(methods, key=lambda n: n["line"]),
            })
        for fn in symbols.functions:
            n_functions += 1
            children.append(_function_node(fn, "function", file_tools))

    children.sort(key=lambda n: n.get("line", 0))

    max_sev = None
    for risk in file_risks:
        max_sev = _max_severity(max_sev, risk.get("severity"))

    node: Dict[str, Any] = {
        "name": Path(rel).name,
        "type": "file",
        "path": rel,
        "language": symbols.language if symbols else None,
        "counts": {
            "files": 1,
            "classes": n_classes,
            "functions": n_functions,
            "tools": len(file_tools),
            "prompts": len(file_prompts),
            "risks": len(file_risks),
        },
        "children": children,
    }
    if is_entry_point:
        node["is_entry_point"] = True
    if file_tools:
        node["tools"] = [
            {"name": t.get("name"), "risk_level": t.get("risk_level", "low")}
            for t in file_tools
        ]
    if file_prompts:
        node["prompts"] = [p.get("name") for p in file_prompts]
    if file_risks:
        node["risks"] = [
            {
                "severity": r.get("severity"),
                "risk_type": r.get("risk_type"),
                "description": (r.get("description") or "")[:200],
            }
            for r in file_risks
        ]
        node["max_risk_severity"] = max_sev
    if symbols is not None and symbols.parse_errors:
        node["parse_errors"] = len(symbols.parse_errors)
    return node


def build_code_tree(
    all_symbols: List[FileSymbols],
    tools: List[Any],
    prompts: List[Any],
    risks: List[Any],
    entry_points: List[str],
    root_path: str,
) -> Dict[str, Any]:
    """Build the nested code tree embedded in the agent map.

    ``tools``/``prompts``/``risks`` accept the Phase A dataclasses or plain
    dicts (both carry a ``location`` with a ``file`` key).  Files referenced
    only by a tool, prompt, or risk (e.g. prompt template files that produce
    no symbols) still get a node, so nothing the analysis found is invisible
    in the tree.
    """
    def _as_dict(obj: Any) -> Dict[str, Any]:
        if isinstance(obj, dict):
            return obj
        out = dict(getattr(obj, "__dict__", {}) or {})
        return out

    tools_d = [_as_dict(t) for t in tools or []]
    prompts_d = [_as_dict(p) for p in prompts or []]
    risks_d = [_as_dict(r) for r in risks or []]

    symbols_by_rel: Dict[str, FileSymbols] = {
        _relpath(s.file_path, root_path): s for s in all_symbols
    }

    def _bucket(items: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        by_file: Dict[str, List[Dict[str, Any]]] = {}
        for item in items:
            file = (item.get("location") or {}).get("file")
            if file:
                by_file.setdefault(_relpath(file, root_path), []).append(item)
        return by_file

    tools_by_file = _bucket(tools_d)
    prompts_by_file = _bucket(prompts_d)
    risks_by_file = _bucket(risks_d)
    entry_rels = {_relpath(e, root_path) for e in entry_points or []}

    all_rels = sorted(
        set(symbols_by_rel) | set(tools_by_file) | set(prompts_by_file) | set(risks_by_file)
    )

    root_name = Path(root_path).resolve().name or "repository"
    root: Dict[str, Any] = {
        "name": root_name,
        "type": "directory",
        "path": "",
        "children": [],
        "counts": {"files": 0, "classes": 0, "functions": 0,
                   "tools": 0, "prompts": 0, "risks": 0},
    }
    dir_nodes: Dict[str, Dict[str, Any]] = {"": root}

    def _dir_node(rel_dir: str) -> Dict[str, Any]:
        if rel_dir in dir_nodes:
            return dir_nodes[rel_dir]
        parent = _dir_node(str(Path(rel_dir).parent) if str(Path(rel_dir).parent) != "." else "")
        node = {
            "name": Path(rel_dir).name,
            "type": "directory",
            "path": rel_dir,
            "children": [],
            "counts": {"files": 0, "classes": 0, "functions": 0,
                       "tools": 0, "prompts": 0, "risks": 0},
        }
        parent["children"].append(node)
        dir_nodes[rel_dir] = node
        return node

    for rel in all_rels:
        parent_dir = str(Path(rel).parent)
        parent = _dir_node("" if parent_dir == "." else parent_dir)
        file_node = _file_node(
            rel,
            symbols_by_rel.get(rel),
            tools_by_file.get(rel, []),
            prompts_by_file.get(rel, []),
            risks_by_file.get(rel, []),
            is_entry_point=rel in entry_rels,
        )
        parent["children"].append(file_node)

    # Roll counts and max risk severity up the directory chain, then sort
    # children (directories first, then files, both alphabetical).
    def _finalise(node: Dict[str, Any]) -> Dict[str, Any]:
        if node["type"] != "directory":
            return node["counts"], node.get("max_risk_severity")
        totals = node["counts"]
        max_sev = None
        for child in node["children"]:
            child_counts, child_sev = _finalise(child)
            for key in totals:
                totals[key] += child_counts.get(key, 0)
            max_sev = _max_severity(max_sev, child_sev)
        if max_sev:
            node["max_risk_severity"] = max_sev
        node["children"].sort(
            key=lambda n: (0 if n["type"] == "directory" else 1, n["name"].lower())
        )
        return totals, max_sev

    _finalise(root)

    return {
        "root": root_name,
        "total_files": root["counts"]["files"],
        "total_classes": root["counts"]["classes"],
        "total_functions": root["counts"]["functions"],
        "tree": root,
    }
