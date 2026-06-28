"""
Pattern Recognition System.
Detects agent frameworks, extracts tools, prompts, and memory systems
from parsed symbols.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from src.analysis.static_analyzer import (
    FileSymbols, FunctionInfo, ClassInfo, ImportInfo, VariableInfo, Location,
)

# Import framework signatures from config
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from config.framework_signatures import FRAMEWORK_SIGNATURES


@dataclass
class ToolDefinition:
    id: str
    name: str
    description: str | None
    parameters: list[dict]
    source: str  # e.g. "langchain_decorator", "langchain_class", "openai_function_calling", "custom_heuristic"
    location: dict
    confidence: float = 1.0
    risk_level: str = "low"
    sandbox_safe: bool = True
    code_snippet: str | None = None


@dataclass
class PromptDefinition:
    name: str
    type: str  # "system_prompt", "template", "file"
    content: str
    variables: list[str] = field(default_factory=list)
    location: dict = field(default_factory=dict)


@dataclass
class MemorySystem:
    type: str  # "conversation_buffer", "vector_store", "persistent_state", "class_state"
    implementation: str
    location: dict = field(default_factory=dict)


@dataclass
class PatternResult:
    framework: str
    framework_confidence: float
    tools: list[ToolDefinition] = field(default_factory=list)
    prompts: list[PromptDefinition] = field(default_factory=list)
    memory_systems: list[MemorySystem] = field(default_factory=list)


def _generate_id(name: str) -> str:
    return name.lower().replace(" ", "_").replace("-", "_")


# ---------------------------------------------------------------------------
# Framework Detection
# ---------------------------------------------------------------------------

def detect_framework(all_symbols: list[FileSymbols]) -> tuple[str, float]:
    """
    Score each framework by matching imports, decorators, and class bases
    across all parsed files. Returns (framework_name, confidence).
    """
    scores: dict[str, int] = {fw: 0 for fw in FRAMEWORK_SIGNATURES}

    for symbols in all_symbols:
        # Check imports
        for imp in symbols.imports:
            import_text = f"from {imp.module} import" if imp.names else f"import {imp.module}"
            for fw, sig in FRAMEWORK_SIGNATURES.items():
                for pattern in sig.get("imports", []):
                    if pattern in import_text or imp.module.startswith(pattern.split()[-1]):
                        scores[fw] += 2

        # Check decorators on functions
        for func in symbols.functions:
            for dec in func.decorators:
                for fw, sig in FRAMEWORK_SIGNATURES.items():
                    if dec in sig.get("decorators", []):
                        scores[fw] += 3

        # Check class bases
        for cls in symbols.classes:
            for base in cls.bases:
                for fw, sig in FRAMEWORK_SIGNATURES.items():
                    if base in sig.get("classes", []):
                        scores[fw] += 3

    best_fw, best_score = max(scores.items(), key=lambda x: x[1])
    if best_score == 0:
        return "custom", 0.0

    # Normalize confidence (arbitrary cap at 20)
    confidence = min(best_score / 20.0, 1.0)
    return best_fw, confidence


# ---------------------------------------------------------------------------
# Tool Extraction
# ---------------------------------------------------------------------------

def _extract_langchain_tools(all_symbols: list[FileSymbols]) -> list[ToolDefinition]:
    """Extract tools from @tool decorators and BaseTool subclasses."""
    tools = []

    for symbols in all_symbols:
        # Pattern 1: @tool decorator on functions
        for func in symbols.functions:
            if "tool" in func.decorators:
                tools.append(ToolDefinition(
                    id=_generate_id(func.name),
                    name=func.name,
                    description=func.docstring,
                    parameters=[
                        {"name": p.name, "type": p.type_annotation, "default": p.default}
                        for p in func.params
                    ],
                    source="langchain_decorator",
                    location={"file": func.location.file, "line": func.location.line},
                    code_snippet=func.body_text[:500] if func.body_text else None,
                ))

        # Pattern 2: BaseTool subclasses
        for cls in symbols.classes:
            base_names = [b.split(".")[-1] for b in cls.bases]
            if any(b in ("BaseTool", "StructuredTool", "Tool") for b in base_names):
                # Find _run or _arun method
                run_method = None
                for m in cls.methods:
                    if m.name in ("_run", "_arun", "run"):
                        run_method = m
                        break

                desc = cls.docstring
                params = []
                code = None
                if run_method:
                    desc = desc or run_method.docstring
                    params = [
                        {"name": p.name, "type": p.type_annotation, "default": p.default}
                        for p in run_method.params
                    ]
                    code = run_method.body_text[:500] if run_method.body_text else None

                # Check class variables for name/description overrides
                for var_name, var_val in cls.class_variables:
                    if var_name == "name" and var_val:
                        pass  # could override name
                    if var_name == "description" and var_val:
                        desc = var_val.strip("\"'")

                tools.append(ToolDefinition(
                    id=_generate_id(cls.name),
                    name=cls.name,
                    description=desc,
                    parameters=params,
                    source="langchain_class",
                    location={"file": cls.location.file, "line": cls.location.line},
                    code_snippet=code,
                ))

    return tools


def _is_tool_array_variable(name_lower: str, value_text: str | None) -> bool:
    """True if this variable is likely a list of tool definitions (OpenAI, Claude, or Python)."""
    if not value_text or len(value_text) < 50:
        return False
    # Explicit list names (JS/TS and Python: TOOLS, tools, tool_list, etc.)
    if any(kw in name_lower for kw in (
        "tools", "functions", "function_definitions", "tool_definitions",
        "tool_list", "tool_defs", "agent_tools",
    )):
        return True
    # Name ends with 'tools': victoriaTools (TS), agent_tools (Python), etc.
    if name_lower.endswith("tools") and len(name_lower) > 4:
        return True
    # Avoid executor/helper names
    if any(no in name_lower for no in ("execute", "handler", "node", "runner")):
        return False
    return False


def _extract_openai_tools(all_symbols: list[FileSymbols]) -> list[ToolDefinition]:
    """Extract tools from OpenAI- or Claude-style tool arrays.
    Works for TypeScript, JavaScript, and Python. Parses name/description from variable
    value (double or single quotes, unquoted keys). Detects tools, functions, victoriaTools,
    agent_tools, tool_list, etc.
    """
    tools = []

    for symbols in all_symbols:
        # Look for variables that look like tool/function schemas
        for var in symbols.variables:
            name_lower = var.name.lower()
            if not _is_tool_array_variable(name_lower, var.value_text):
                continue
            val = var.value_text or ""
            # Double-quoted (JSON): "name": "tool_name"
            name_double = re.findall(r'"name"\s*:\s*"([^"]+)"', val)
            desc_double = re.findall(r'"description"\s*:\s*"([^"]+)"', val)
            # Single-quoted or unquoted key (TS/JS): name: 'tool_name' or 'name': 'tool_name'
            name_single = re.findall(r"['\"]?name['\"]?\s*:\s*['\"]([^'\"]+)['\"]", val)
            desc_single = re.findall(
                r"['\"]?description['\"]?\s*:\s*['\"]([^'\"]+)['\"]",
                val,
            )

            name_matches = name_double if name_double else name_single
            desc_matches = desc_double if desc_double else desc_single

            for i, tool_name in enumerate(name_matches):
                desc = desc_matches[i] if i < len(desc_matches) else None
                tools.append(ToolDefinition(
                    id=_generate_id(tool_name),
                    name=tool_name,
                    description=desc,
                    parameters=[],
                    source="openai_function_calling",
                    location={"file": var.location.file, "line": var.location.line},
                    confidence=0.8,
                ))

    return tools


def _path_looks_like_tool_definitions(path_lower: str) -> bool:
    """True if path suggests tool definition modules (OpenAI or Claude layout)."""
    if "/tools/" in path_lower or "tools" in path_lower:
        return True
    # Claude/agent layouts: agent/tools, services/agent, skills, definitions
    if "agent" in path_lower and ("tool" in path_lower or "definition" in path_lower or "skill" in path_lower):
        return True
    if "/skills/" in path_lower or "skill" in path_lower:
        return True
    return False


def _extract_openai_tools_from_tool_files(all_symbols: list[FileSymbols]) -> list[ToolDefinition]:
    """Extract tools from one-tool-per-file modules. Supports TypeScript, JavaScript, and Python.
    Scans paths like tools/, agent/tools, skills/. Parses first name/description in file
    (OpenAI function: { name, description } or Python/Claude dict with name/description).
    """
    tools = []
    seen_names: set[str] = set()

    for symbols in all_symbols:
        path_lower = symbols.file_path.lower().replace("\\", "/")
        if "node_modules" in path_lower or "__pycache__" in path_lower:
            continue
        if symbols.language not in ("typescript", "javascript", "python"):
            continue
        # Scan paths that look like tool modules (tools/, agent/tools, skills/, etc.)
        if not _path_looks_like_tool_definitions(path_lower):
            continue
        if not os.path.isfile(symbols.file_path):
            continue

        try:
            with open(symbols.file_path, encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            continue

        # OpenAI: function: { name, description }; Claude: top-level name/description or same shape
        name_matches = re.findall(
            r"\bname\s*:\s*[\"']([^\"']+)[\"']",
            content,
        )
        desc_matches = re.findall(
            r"\bdescription\s*:\s*[\"']([^\"']+)[\"']",
            content,
        )

        # First name in file is the tool name; rest can be param names
        if not name_matches:
            continue
        tool_name = name_matches[0]
        if tool_name in seen_names:
            continue
        if " " in tool_name or len(tool_name) > 60 or len(tool_name) < 2:
            continue
        if tool_name in ("string", "object", "array", "number", "boolean"):
            continue
        desc = desc_matches[0] if desc_matches else None
        tools.append(ToolDefinition(
            id=_generate_id(tool_name),
            name=tool_name,
            description=desc,
            parameters=[],
            source="openai_tool_file",
            location={"file": symbols.file_path, "line": 0},
            confidence=0.85,
        ))
        seen_names.add(tool_name)

    return tools


# Function names that are tool *executors* or graph *nodes*, not tool definitions.
# These should not be reported as tools for the agent.
_EXECUTOR_NODE_PATTERNS = (
    "executetool", "execute_tool", "runtool", "run_tool",
    "createtoolsnode", "create_tools_node", "toolsnode", "tools_node",
    "handletool", "process_tool", "tool_executor", "tool_execution",
    "invoketool", "dispatch_tool",
)


def _extract_custom_tools(
    all_symbols: list[FileSymbols],
    known_tool_names: set[str],
) -> list[ToolDefinition]:
    """Heuristic detection of tools in custom implementations."""
    tools = []

    for symbols in all_symbols:
        # Check if this is a route file (TypeScript/JavaScript API routes)
        file_path_lower = symbols.file_path.lower()
        is_route_file = "route" in file_path_lower or "api" in file_path_lower
        is_ts_js = symbols.language in ("typescript", "javascript")
        
        for func in symbols.functions:
            if func.name in known_tool_names:
                continue
            if func.name.startswith("_") and not is_route_file:
                continue
            name_lower = func.name.lower()
            # Skip executors/nodes: they run tools, they are not tools the agent chooses.
            if any(pat in name_lower for pat in _EXECUTOR_NODE_PATTERNS):
                continue
            doc_lower = (func.docstring or "").lower()
            if is_ts_js:
                if "tool" not in name_lower and "tool" not in doc_lower and "tools" not in file_path_lower:
                    continue
            if symbols.language == "python":
                decorator_text = " ".join(func.decorators).lower()
                if "tool" not in name_lower and "tool" not in doc_lower and "tool" not in decorator_text:
                    continue

            score = 0

            # Functions making HTTP/API calls
            http_indicators = ("requests.", "httpx.", "aiohttp.", "urllib.", "fetch(", "axios", "http", "https")
            body_lower = (func.body_text or "").lower()
            if any(h in body_lower for h in http_indicators):
                score += 3

            # Database calls
            db_indicators = ("execute", "query", "cursor.", "session.", "db.", "database", "sql", "mssql", "postgres")
            if any(d in body_lower for d in db_indicators):
                score += 2

            # API route handlers (TypeScript/JavaScript)
            if is_route_file:
                score += 3
                # Common route handler patterns
                route_patterns = ("get", "post", "put", "delete", "patch", "handler", "route")
                if any(p in func.name.lower() for p in route_patterns):
                    score += 2

            # Naming patterns
            if any(kw in name_lower for kw in ("tool", "action", "execute", "run_", "handler", "endpoint")):
                score += 2

            # Has a descriptive docstring (tools usually do)
            if func.docstring and len(func.docstring) > 20:
                score += 1

            # Has typed parameters (more tool-like)
            if any(p.type_annotation for p in func.params):
                score += 1
            elif symbols.language in ("typescript", "javascript") and func.params:
                # TypeScript functions often have params even without explicit types
                score += 0.5

            # Exported functions are more likely to be tools
            if symbols.language in ("typescript", "javascript"):
                # Check if function is exported (simplified check)
                file_content = func.body_text or ""
                if "export" in file_content[:200] or func.name in [v.name for v in symbols.variables]:
                    score += 1

            if score >= 3:  # Lowered threshold for TypeScript
                tools.append(ToolDefinition(
                    id=_generate_id(func.name),
                    name=func.name,
                    description=func.docstring,
                    parameters=[
                        {"name": p.name, "type": p.type_annotation, "default": p.default}
                        for p in func.params
                    ],
                    source="custom_heuristic",
                    location={"file": func.location.file, "line": func.location.line},
                    confidence=min(score / 8.0, 1.0),
                    code_snippet=func.body_text[:500] if func.body_text else None,
                ))

    return tools


def extract_all_tools(all_symbols: list[FileSymbols], framework: str) -> list[ToolDefinition]:
    """Extract tools using framework-specific and generic patterns."""
    tools = []

    if framework in ("langchain", "langgraph"):
        tools.extend(_extract_langchain_tools(all_symbols))

    tools.extend(_extract_openai_tools(all_symbols))
    # Per-file tool definitions (e.g. tools/lookup-vehicle.ts with function: { name, description })
    tools.extend(_extract_openai_tools_from_tool_files(all_symbols))

    known_names = {t.name for t in tools}
    tools.extend(_extract_custom_tools(all_symbols, known_names))

    # Deduplicate: keep highest confidence per name
    seen: dict[str, ToolDefinition] = {}
    for t in tools:
        key = t.name.lower()
        if key not in seen or t.confidence > seen[key].confidence:
            seen[key] = t
    tools = list(seen.values())

    return tools


# ---------------------------------------------------------------------------
# Prompt Extraction
# ---------------------------------------------------------------------------

def extract_prompts(
    all_symbols: list[FileSymbols],
    prompt_files: list[str],
    prompt_encoding: str = "utf-8",
) -> list[PromptDefinition]:
    """Find system prompts, templates, and instruction strings."""
    prompts = []
    prompt_keywords = ("prompt", "system", "instruction", "template", "persona")

    for symbols in all_symbols:
        # Pattern 1: String variables with prompt-like names
        for var in symbols.variables:
            name_lower = var.name.lower()
            if any(kw in name_lower for kw in prompt_keywords):
                if var.value_text and len(var.value_text) > 50:
                    # Extract template variables like {variable}
                    template_vars = re.findall(r"\{(\w+)\}", var.value_text)
                    prompts.append(PromptDefinition(
                        name=var.name,
                        type="system_prompt",
                        content=var.value_text.strip("\"'"),
                        variables=template_vars,
                        location={"file": var.location.file, "line": var.location.line},
                    ))

        # Pattern 2: PromptTemplate / ChatPromptTemplate objects
        for var in symbols.variables:
            if var.value_text and ("PromptTemplate" in (var.value_text or "") or
                                   "ChatPromptTemplate" in (var.value_text or "")):
                # Extract template string if visible
                template_match = re.search(
                    r'template\s*=\s*["\'](.+?)["\']',
                    var.value_text,
                    re.DOTALL,
                )
                content = template_match.group(1) if template_match else var.value_text
                template_vars = re.findall(r"\{(\w+)\}", content)
                prompts.append(PromptDefinition(
                    name=var.name,
                    type="template",
                    content=content,
                    variables=template_vars,
                    location={"file": var.location.file, "line": var.location.line},
                ))

    # Pattern 3: Prompt files
    for file_path in prompt_files:
        try:
            with open(file_path, encoding=prompt_encoding, errors="replace") as f:
                content = f.read()
            template_vars = re.findall(r"\{(\w+)\}", content)
            prompts.append(PromptDefinition(
                name=os.path.basename(file_path),
                type="file",
                content=content[:2000],
                variables=template_vars,
                location={"file": file_path, "line": 0},
            ))
        except OSError:
            pass

    return prompts


# ---------------------------------------------------------------------------
# Memory / State Detection
# ---------------------------------------------------------------------------

MEMORY_CLASS_PATTERNS = [
    "ConversationBufferMemory", "ConversationSummaryMemory",
    "ConversationBufferWindowMemory", "ConversationTokenBufferMemory",
    "VectorStoreRetrieverMemory",
]

VECTOR_STORE_PATTERNS = [
    "Pinecone", "Chroma", "FAISS", "Weaviate", "Qdrant",
    "Milvus", "PGVector",
]

DB_IMPORT_PATTERNS = [
    "redis", "psycopg", "pymongo", "sqlite3", "sqlalchemy",
    "motor", "aioredis",
]


def detect_memory_systems(all_symbols: list[FileSymbols]) -> list[MemorySystem]:
    """Identify conversation history, vector stores, and state management."""
    memory_systems = []

    for symbols in all_symbols:
        # LangChain memory classes
        for cls in symbols.classes:
            for base in cls.bases:
                base_name = base.split(".")[-1]
                if base_name in MEMORY_CLASS_PATTERNS:
                    memory_systems.append(MemorySystem(
                        type="conversation_buffer",
                        implementation=base_name,
                        location={"file": cls.location.file, "line": cls.location.line},
                    ))

        # Variable assignments that instantiate memory
        for var in symbols.variables:
            if var.value_text:
                for mem_cls in MEMORY_CLASS_PATTERNS:
                    if mem_cls in var.value_text:
                        memory_systems.append(MemorySystem(
                            type="conversation_buffer",
                            implementation=mem_cls,
                            location={"file": var.location.file, "line": var.location.line},
                        ))

                for vs in VECTOR_STORE_PATTERNS:
                    if vs in var.value_text:
                        memory_systems.append(MemorySystem(
                            type="vector_store",
                            implementation=vs,
                            location={"file": var.location.file, "line": var.location.line},
                        ))

        # Database imports
        for imp in symbols.imports:
            for db in DB_IMPORT_PATTERNS:
                if db in imp.module:
                    memory_systems.append(MemorySystem(
                        type="persistent_state",
                        implementation=imp.module,
                        location={"file": imp.location.file, "line": imp.location.line},
                    ))

    return memory_systems


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------

def detect_patterns(
    all_symbols: list[FileSymbols],
    prompt_files: list[str] | None = None,
    prompt_encoding: str = "utf-8",
) -> PatternResult:
    """
    Run all pattern detection on parsed symbols.
    Returns framework, tools, prompts, and memory systems.
    """
    framework, fw_confidence = detect_framework(all_symbols)
    tools = extract_all_tools(all_symbols, framework)
    prompts = extract_prompts(all_symbols, prompt_files or [], prompt_encoding=prompt_encoding)
    memory = detect_memory_systems(all_symbols)

    return PatternResult(
        framework=framework,
        framework_confidence=fw_confidence,
        tools=tools,
        prompts=prompts,
        memory_systems=memory,
    )
