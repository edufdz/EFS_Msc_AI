"""
Intra-procedural taint/data-flow analysis.

Tracks untrusted input from sources through propagation to sinks
within individual function bodies. Modelled on CodeQL's
source/propagation/sink framework.

Scope: intra-procedural only (single function body, line-by-line).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from config.framework_signatures import PII_PATTERNS
from src.analysis.static_analyzer import FileSymbols, FunctionInfo


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TaintSource:
    variable: str
    source_type: str   # "user_input" | "tool_output" | "retrieved_doc" | "env_var"
    location: dict
    description: str


@dataclass
class TaintSink:
    variable: str
    sink_type: str     # "external_api" | "database_write" | "logging" | "code_execution" | "outbound_message" | "file_write"
    location: dict
    description: str


@dataclass
class TaintFlow:
    source: TaintSource
    sink: TaintSink
    path: list[str]
    data_types: list[str]
    risk_level: str
    taxonomy_ids: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 4.2  Source identification
# ---------------------------------------------------------------------------

_USER_INPUT_PARAMS = {
    "message", "user_input", "query", "request", "input", "text", "prompt",
    "user_message", "user_query", "content", "body", "payload",
}

_EXTERNAL_DATA_PATTERNS = [
    (r"os\.environ\[", "env_var"),
    (r"os\.getenv\(", "env_var"),
    (r"request\.json", "user_input"),
    (r"request\.body", "user_input"),
    (r"request\.form", "user_input"),
]

_RETRIEVED_DOC_PATTERNS = [
    "retrieve", "search", "fetch", "get_context", "vector_store.query",
    "similarity_search", "get_relevant",
]


def identify_sources(func: FunctionInfo) -> list[TaintSource]:
    """Identify taint sources within a function."""
    sources: list[TaintSource] = []
    loc = {"file": func.location.file, "line": func.location.line}

    # User input parameters
    for param in func.params:
        if param.name.lower() in _USER_INPUT_PARAMS:
            sources.append(TaintSource(
                variable=param.name,
                source_type="user_input",
                location=loc,
                description=f"user input parameter '{param.name}'",
            ))

    # Scan body for external data / retrieved doc sources
    for i, line in enumerate(func.body_text.splitlines(), start=1):
        stripped = line.strip()

        # Assignment from external data
        for pattern, src_type in _EXTERNAL_DATA_PATTERNS:
            if re.search(pattern, stripped):
                # Try to find assigned variable
                m = re.match(r"(\w+)\s*=", stripped)
                if m:
                    sources.append(TaintSource(
                        variable=m.group(1),
                        source_type=src_type,
                        location={**loc, "line": loc["line"] + i},
                        description=f"{src_type} assigned to '{m.group(1)}'",
                    ))

        # Retrieved document patterns
        for pat in _RETRIEVED_DOC_PATTERNS:
            if pat in stripped:
                m = re.match(r"(\w+)\s*=", stripped)
                if m:
                    sources.append(TaintSource(
                        variable=m.group(1),
                        source_type="retrieved_doc",
                        location={**loc, "line": loc["line"] + i},
                        description=f"retrieved document assigned to '{m.group(1)}'",
                    ))

    return sources


# ---------------------------------------------------------------------------
# 4.3  Sink identification
# ---------------------------------------------------------------------------

_SINK_PATTERNS: list[tuple[str, str, str]] = [
    # (regex, sink_type, description_template)
    # External API
    (r"requests\.(post|put|patch|delete)\(", "external_api", "requests.{0}() call"),
    (r"httpx\.(post|put|patch|delete)\(", "external_api", "httpx.{0}() call"),
    (r"aiohttp", "external_api", "aiohttp call"),
    (r"urllib\.request", "external_api", "urllib.request call"),
    (r"fetch\(", "external_api", "fetch() call"),
    # Database writes
    (r"\.execute\(.*(?:INSERT|UPDATE|DELETE)", "database_write", "SQL write via .execute()"),
    (r"\.save\(\)", "database_write", ".save() call"),
    (r"\.commit\(\)", "database_write", ".commit() call"),
    # Logging
    (r"\bprint\(", "logging", "print() call"),
    (r"\blogger\.", "logging", "logger call"),
    (r"\blogging\.", "logging", "logging call"),
    # Code execution
    (r"\beval\(", "code_execution", "eval() call"),
    (r"\bexec\(", "code_execution", "exec() call"),
    (r"subprocess\.", "code_execution", "subprocess call"),
    (r"os\.system\(", "code_execution", "os.system() call"),
    # Outbound messages
    (r"send_email\(", "outbound_message", "send_email() call"),
    (r"send_sms\(", "outbound_message", "send_sms() call"),
    (r"send_message\(", "outbound_message", "send_message() call"),
    (r"\bnotify\(", "outbound_message", "notify() call"),
    # File writes
    (r"open\(.+['\"]w['\"]", "file_write", "file write via open()"),
    (r"\.write\(", "file_write", ".write() call"),
    (r"json\.dump\(", "file_write", "json.dump() call"),
]

_SINK_SEVERITY = {
    "code_execution": "critical",
    "external_api": "high",
    "outbound_message": "high",
    "database_write": "medium",
    "file_write": "medium",
    "logging": "low",
}


def identify_sinks(func: FunctionInfo) -> list[TaintSink]:
    """Identify taint sinks within a function."""
    sinks: list[TaintSink] = []
    loc = {"file": func.location.file, "line": func.location.line}

    for i, line in enumerate(func.body_text.splitlines(), start=1):
        for pattern, sink_type, desc_template in _SINK_PATTERNS:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                # Extract the variable being consumed (look for arguments)
                arg_match = re.search(r"\(([^)]*)", line[match.start():])
                var_name = ""
                if arg_match:
                    # Take first argument token
                    first_arg = arg_match.group(1).split(",")[0].strip().strip("'\"")
                    if first_arg and re.match(r"^[a-zA-Z_]\w*", first_arg):
                        var_name = re.match(r"^[a-zA-Z_]\w*", first_arg).group(0)

                desc = desc_template.format(match.group(1) if match.lastindex else "")
                sinks.append(TaintSink(
                    variable=var_name,
                    sink_type=sink_type,
                    location={**loc, "line": loc["line"] + i},
                    description=desc,
                ))
                break  # one sink per line

    return sinks


# ---------------------------------------------------------------------------
# 4.4  Intra-procedural flow tracing
# ---------------------------------------------------------------------------

def trace_flows(
    func: FunctionInfo,
    sources: list[TaintSource],
    sinks: list[TaintSink],
) -> list[TaintFlow]:
    """Trace tainted data from sources to sinks through assignments.

    Walks the function body line-by-line, propagating taint through:
      - Direct assignment:  x = tainted_var
      - Function calls:     result = foo(tainted_var)
      - String formatting:  msg = f"... {tainted_var} ..."
      - Dict assignment:    data["key"] = tainted_var
    """
    if not sources or not sinks:
        return []

    # Initialise tainted set with source variables
    # Maps variable → (original source, path so far)
    tainted: dict[str, tuple[TaintSource, list[str]]] = {}
    for src in sources:
        tainted[src.variable] = (src, [src.variable])

    # Walk body lines and propagate
    for line in func.body_text.splitlines():
        stripped = line.strip()

        # Assignment: target = expr
        assign_match = re.match(r"(\w+)\s*=\s*(.+)", stripped)
        if assign_match:
            target = assign_match.group(1)
            expr = assign_match.group(2)

            # Check if any tainted variable appears in the RHS
            for tvar, (src, path) in list(tainted.items()):
                if re.search(r'\b' + re.escape(tvar) + r'\b', expr):
                    tainted[target] = (src, path + [target])
                    break

        # Dict/subscript assignment: data["key"] = expr  or  data[key] = expr
        dict_match = re.match(r"(\w+)\[.+\]\s*=\s*(.+)", stripped)
        if dict_match:
            target = dict_match.group(1)
            expr = dict_match.group(2)
            for tvar, (src, path) in list(tainted.items()):
                if re.search(r'\b' + re.escape(tvar) + r'\b', expr):
                    if target not in tainted:
                        tainted[target] = (src, path + [target])
                    break

    # Check which sinks consume tainted variables
    flows: list[TaintFlow] = []
    sink_severity = _SINK_SEVERITY

    for sink in sinks:
        # Check if the sink variable is tainted
        if sink.variable and sink.variable in tainted:
            src, path = tainted[sink.variable]
            flows.append(TaintFlow(
                source=src,
                sink=sink,
                path=path + [sink.description],
                data_types=[],
                risk_level=sink_severity.get(sink.sink_type, "medium"),
            ))
            continue

        # Also check if any tainted variable appears on the sink's line
        for i, line in enumerate(func.body_text.splitlines(), start=1):
            line_num = func.location.line + i
            if sink.location.get("line") == line_num:
                for tvar, (src, path) in tainted.items():
                    if re.search(r'\b' + re.escape(tvar) + r'\b', line):
                        flows.append(TaintFlow(
                            source=src,
                            sink=sink,
                            path=path + [sink.description],
                            data_types=[],
                            risk_level=sink_severity.get(sink.sink_type, "medium"),
                        ))
                        break
                break

    return flows


# ---------------------------------------------------------------------------
# 4.5  PII type detection in flows
# ---------------------------------------------------------------------------

_PII_KEYWORDS = {"email", "phone", "ssn", "credit_card", "address", "name", "password"}


def detect_pii_in_flow(flow: TaintFlow) -> None:
    """Check if a flow carries PII based on variable names in the path."""
    types: set[str] = set()
    for var in flow.path:
        var_lower = var.lower()
        for kw in _PII_KEYWORDS:
            if kw in var_lower:
                types.add(kw)
    flow.data_types = sorted(types)


# ---------------------------------------------------------------------------
# 4.6  Taxonomy assignment for flows
# ---------------------------------------------------------------------------

def assign_flow_taxonomy(flow: TaintFlow) -> None:
    """Assign OWASP/MITRE taxonomy IDs based on sink type and data types."""
    ids: list[str] = []
    if flow.data_types:
        ids.append("LLM02")  # Sensitive Information Disclosure
    if flow.sink.sink_type == "code_execution":
        ids.extend(["ASI05", "LLM01"])
    if flow.sink.sink_type == "external_api":
        ids.append("ASI02")
    if flow.sink.sink_type == "outbound_message":
        ids.append("ASI02")
    if flow.data_types:
        ids.append("ASI03")
    flow.taxonomy_ids = sorted(set(ids))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_function_taint(func: FunctionInfo) -> list[TaintFlow]:
    """Run full taint analysis on a single function."""
    sources = identify_sources(func)
    sinks = identify_sinks(func)
    flows = trace_flows(func, sources, sinks)
    for flow in flows:
        detect_pii_in_flow(flow)
        assign_flow_taxonomy(flow)
    return flows


def analyze_taint(all_symbols: list[FileSymbols]) -> list[TaintFlow]:
    """Run taint analysis across all files and functions."""
    all_flows: list[TaintFlow] = []
    for sym in all_symbols:
        for func in sym.functions:
            all_flows.extend(analyze_function_taint(func))
        for cls in sym.classes:
            for method in cls.methods:
                all_flows.extend(analyze_function_taint(method))
    return all_flows
