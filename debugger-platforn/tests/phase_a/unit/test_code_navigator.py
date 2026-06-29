"""
Sprint T — Tests for Sprint 5 (Hierarchical Code Summarisation).

Validates:
  - Call graph construction from FileSymbols
  - Relevant subgraph selection via BFS
  - Three-level hierarchical summarisation
  - Budget-aware context assembly (never truncates mid-function)
  - Coverage metadata accuracy
  - context_budget parameter wiring
  - LLM-fact validation
"""

import pytest

from src.ai_analyzer.code_navigator import (
    CodeChunk,
    assemble_context,
    build_call_graph,
    find_relevant_subgraph,
    summarise_repository,
)
from src.analysis.static_analyzer import (
    ClassInfo,
    FileSymbols,
    FunctionInfo,
    ImportInfo,
    Location,
    ParamInfo,
)
from src.patterns.detector import PromptDefinition, ToolDefinition


# ── Helpers ──

def _loc(file: str = "test.py", line: int = 1) -> Location:
    return Location(file=file, line=line)


def _func(
    name: str,
    body: str = "pass",
    calls: list[str] | None = None,
    params: list[str] | None = None,
    docstring: str | None = None,
    file: str = "test.py",
) -> FunctionInfo:
    return FunctionInfo(
        name=name,
        params=[ParamInfo(p, None, None) for p in (params or [])],
        docstring=docstring,
        decorators=[],
        body_text=body,
        location=_loc(file),
        calls=calls or [],
    )


def _sym(
    file_path: str = "test.py",
    functions: list[FunctionInfo] | None = None,
    classes: list[ClassInfo] | None = None,
    imports: list[ImportInfo] | None = None,
) -> FileSymbols:
    return FileSymbols(
        file_path=file_path,
        language="python",
        functions=functions or [],
        classes=classes or [],
        imports=imports or [],
        variables=[],
        parse_errors=[],
    )


def _tool(name: str, risk_level: str = "low") -> ToolDefinition:
    return ToolDefinition(
        id=name,
        name=name,
        description=f"{name} tool",
        parameters=[],
        source="test",
        location={"file": "test.py", "line": 1},
        confidence=0.9,
        risk_level=risk_level,
        sandbox_safe=True,
        code_snippet="",
    )


def _prompt(name: str = "system", content: str = "You are helpful.") -> PromptDefinition:
    return PromptDefinition(
        name=name,
        type="system",
        content=content,
        variables=[],
        location={"file": "prompts.py", "line": 1},
    )


# ── 5.1  Call graph construction ──

class TestBuildCallGraph:
    def test_nodes_created_for_all_functions(self):
        sym = _sym(functions=[_func("a"), _func("b"), _func("c")])
        g = build_call_graph([sym])
        assert g.number_of_nodes() == 3

    def test_edges_from_calls(self):
        sym = _sym(functions=[
            _func("main", calls=["helper"]),
            _func("helper"),
        ])
        g = build_call_graph([sym])
        assert g.number_of_edges() == 1
        edges = list(g.edges())
        assert edges[0][0].endswith("::main")
        assert edges[0][1].endswith("::helper")

    def test_no_self_loops(self):
        sym = _sym(functions=[_func("recurse", calls=["recurse"])])
        g = build_call_graph([sym])
        assert g.number_of_edges() == 0  # self-edge filtered

    def test_cross_file_edges(self):
        sym1 = _sym("a.py", functions=[_func("caller", calls=["callee"], file="a.py")])
        sym2 = _sym("b.py", functions=[_func("callee", file="b.py")])
        g = build_call_graph([sym1, sym2])
        assert g.number_of_edges() == 1

    def test_class_methods_indexed(self):
        method = _func("run", body="pass")
        cls = ClassInfo(
            name="Agent", bases=[], docstring=None,
            methods=[method], decorators=[], location=_loc(),
            class_variables=[],
        )
        sym = _sym(classes=[cls])
        g = build_call_graph([sym])
        method_nodes = [n for n in g.nodes if "Agent.run" in n]
        assert len(method_nodes) == 1

    def test_empty_symbols(self):
        g = build_call_graph([])
        assert g.number_of_nodes() == 0
        assert g.number_of_edges() == 0


class TestFindRelevantSubgraph:
    def test_entry_point_functions_included(self):
        sym = _sym("main.py", functions=[_func("start", file="main.py")])
        g = build_call_graph([sym])
        relevant = find_relevant_subgraph(g, ["main.py"], [], [sym])
        assert len(relevant) == 1

    def test_tool_functions_included(self):
        sym = _sym(functions=[_func("search"), _func("unrelated")])
        g = build_call_graph([sym])
        relevant = find_relevant_subgraph(g, [], ["search"], [sym])
        assert any("search" in k for k in relevant)

    def test_reachable_callees_included(self):
        """BFS follows edges from seeds to callees."""
        sym = _sym(functions=[
            _func("main", calls=["helper"]),
            _func("helper", calls=["deep"]),
            _func("deep"),
        ])
        g = build_call_graph([sym])
        relevant = find_relevant_subgraph(g, ["test.py"], [], [sym])
        assert len(relevant) == 3

    def test_unreachable_functions_excluded(self):
        sym = _sym(functions=[
            _func("main"),
            _func("orphan"),
        ])
        g = build_call_graph([sym])
        relevant = find_relevant_subgraph(g, [], ["main"], [sym])
        assert len(relevant) == 1
        assert any("main" in k for k in relevant)

    def test_max_nodes_limit(self):
        funcs = [_func(f"f{i}", calls=[f"f{i+1}"] if i < 99 else []) for i in range(100)]
        sym = _sym(functions=funcs)
        g = build_call_graph([sym])
        relevant = find_relevant_subgraph(g, ["test.py"], [], [sym], max_nodes=10)
        assert len(relevant) <= 10


# ── 5.2  Hierarchical summarisation ──

class TestSummariseRepository:
    def test_three_levels_present(self):
        sym = _sym(functions=[_func("main")])
        g = build_call_graph([sym])
        relevant = find_relevant_subgraph(g, ["test.py"], [], [sym])
        chunks = summarise_repository([sym], relevant, [], [], "langchain")
        levels = {c.level for c in chunks}
        assert "project" in levels
        assert "module" in levels
        assert "function" in levels

    def test_project_chunk_contains_framework(self):
        chunks = summarise_repository([_sym()], set(), [], [], "crewai")
        proj = [c for c in chunks if c.level == "project"]
        assert len(proj) == 1
        assert "crewai" in proj[0].summary

    def test_only_relevant_functions_get_code_chunks(self):
        sym = _sym(functions=[_func("included"), _func("excluded")])
        relevant = {"test.py::included"}
        chunks = summarise_repository([sym], relevant, [], [], "test")
        func_chunks = [c for c in chunks if c.level == "function"]
        assert len(func_chunks) == 1
        assert func_chunks[0].name == "included"

    def test_char_count_populated(self):
        sym = _sym(functions=[_func("f", body="x = 1\nreturn x")])
        relevant = {"test.py::f"}
        chunks = summarise_repository([sym], relevant, [], [], "test")
        func_chunks = [c for c in chunks if c.level == "function"]
        assert func_chunks[0].char_count > 0


# ── 5.3  Budget-aware context assembly ──

class TestAssembleContext:
    def _standard_chunks(self):
        sym = _sym(functions=[
            _func("main", calls=["search"], body="search(q)"),
            _func("search", body="return db.query(q)"),
            _func("helper", body="return 42"),
        ])
        g = build_call_graph([sym])
        relevant = find_relevant_subgraph(g, ["test.py"], ["search"], [sym])
        tool = _tool("search")
        prompt = _prompt(content="Be helpful and safe.")
        chunks = summarise_repository([sym], relevant, [tool], [prompt], "langchain")
        return chunks, [prompt], [tool]

    def test_context_within_budget(self):
        chunks, prompts, tools = self._standard_chunks()
        context, cov = assemble_context(chunks, prompts, tools, ["test.py"], budget_chars=80_000)
        assert cov["budget_used_chars"] <= 80_000

    def test_prompts_always_included(self):
        chunks, prompts, tools = self._standard_chunks()
        context, _ = assemble_context(chunks, prompts, tools, ["test.py"])
        assert "Be helpful and safe." in context

    def test_never_truncates_mid_function(self):
        """A function that doesn't fit the budget is skipped entirely."""
        big_body = "x = 1\n" * 500  # ~3000 chars
        sym = _sym(functions=[_func("big_func", body=big_body)])
        relevant = {"test.py::big_func"}
        chunks = summarise_repository([sym], relevant, [], [], "test")
        prompt = _prompt(content="short")
        # Budget too small for the function but big enough for project+prompt+module
        context, cov = assemble_context(chunks, [prompt], [], ["test.py"], budget_chars=200)
        # The function code should NOT appear (name may appear in module summary)
        assert "x = 1" not in context
        assert cov["included_functions"] == 0

    def test_coverage_metadata_accurate(self):
        chunks, prompts, tools = self._standard_chunks()
        _, cov = assemble_context(chunks, prompts, tools, ["test.py"])
        assert cov["total_functions"] >= 2
        assert cov["included_functions"] >= 1
        assert cov["excluded_functions"] == cov["total_functions"] - cov["included_functions"]
        assert cov["budget_used_chars"] > 0
        assert cov["budget_total_chars"] == 80_000

    def test_no_double_counting(self):
        """A function in entry point file AND named as tool should be counted once."""
        sym = _sym("main.py", functions=[_func("search", file="main.py")])
        relevant = {"main.py::search"}
        tool = _tool("search")
        chunks = summarise_repository([sym], relevant, [tool], [], "test")
        _, cov = assemble_context(chunks, [], [tool], ["main.py"])
        assert cov["included_functions"] == 1

    def test_tool_risk_priority_order(self):
        """Critical-risk tools should appear before low-risk tools."""
        sym = _sym(functions=[
            _func("low_tool", body="safe"),
            _func("crit_tool", body="dangerous"),
        ])
        relevant = {"test.py::low_tool", "test.py::crit_tool"}
        tools = [_tool("low_tool", risk_level="low"), _tool("crit_tool", risk_level="critical")]
        chunks = summarise_repository([sym], relevant, tools, [], "test")
        # Use a tight budget that only fits one tool
        context, cov = assemble_context(
            chunks, [], tools, [],  # no entry points so tools compete
            budget_chars=200,
        )
        if cov["included_functions"] == 1:
            # If only one fits, it should be the critical one
            assert "crit_tool" in context

    def test_tiny_budget_no_crash(self):
        chunks, prompts, tools = self._standard_chunks()
        context, cov = assemble_context(chunks, prompts, tools, ["test.py"], budget_chars=10)
        assert cov["budget_used_chars"] <= 10

    def test_zero_functions_no_crash(self):
        sym = _sym(functions=[])
        chunks = summarise_repository([sym], set(), [], [], "test")
        context, cov = assemble_context(chunks, [], [], [])
        assert cov["total_functions"] == 0
        assert cov["included_functions"] == 0


# ── 5.4  _build_context_summary integration ──

class TestBuildContextSummary:
    def test_returns_tuple(self):
        """_build_context_summary now returns (context, coverage) tuple."""
        from src.ai_analyzer.analyzer import _build_context_summary
        sym = _sym(functions=[_func("main")])
        tool = _tool("search")
        prompt = _prompt()
        result = _build_context_summary([sym], [tool], [prompt], ["test.py"], "langchain")
        assert isinstance(result, tuple)
        assert len(result) == 2
        context, coverage = result
        assert isinstance(context, str)
        assert isinstance(coverage, dict)

    def test_custom_budget(self):
        from src.ai_analyzer.analyzer import _build_context_summary
        sym = _sym(functions=[_func("f", body="x" * 1000)])
        _, cov = _build_context_summary([sym], [], [], ["test.py"], "test", context_budget=500)
        assert cov["budget_total_chars"] == 500


# ── 5.5  LLM-fact validation ──

class TestValidateAIFacts:
    def test_validates_without_crash(self):
        from src.ai_analyzer.analyzer import _validate_ai_facts
        from src.ai_analyzer.analyzer import ToolSemanticInfo, DependencyAnalysis
        ts = ToolSemanticInfo(
            name="search", purpose="search", required_inputs=["q"],
            output="results", read_only=True, handles_sensitive_data=False,
            sensitive_data_types=[], dependencies=[], risk_level="low",
        )
        dep = DependencyAnalysis(
            dependencies=[{"tool": "search", "requires": ["db_connect"]}],
            mutually_exclusive=[], common_sequences=[], circular_dependency_risks=[],
        )
        sym = _sym(functions=[_func("search", body="return results")])
        g = build_call_graph([sym])
        result = _validate_ai_facts([ts], dep, g, [sym])
        assert len(result) == 1

    def test_dependency_marked_unverified_when_no_path(self):
        from src.ai_analyzer.analyzer import _validate_ai_facts, ToolSemanticInfo, DependencyAnalysis
        dep = DependencyAnalysis(
            dependencies=[{"tool": "a", "requires": ["nonexistent"]}],
            mutually_exclusive=[], common_sequences=[], circular_dependency_risks=[],
        )
        sym = _sym(functions=[_func("a")])
        g = build_call_graph([sym])
        _validate_ai_facts([], dep, g, [sym])
        assert dep.dependencies[0]["_confidence"]["nonexistent"] == "unverified"

    def test_dependency_marked_verified_when_path_exists(self):
        from src.ai_analyzer.analyzer import _validate_ai_facts, ToolSemanticInfo, DependencyAnalysis
        dep = DependencyAnalysis(
            dependencies=[{"tool": "caller", "requires": ["callee"]}],
            mutually_exclusive=[], common_sequences=[], circular_dependency_risks=[],
        )
        sym = _sym(functions=[
            _func("caller", calls=["callee"]),
            _func("callee"),
        ])
        g = build_call_graph([sym])
        _validate_ai_facts([], dep, g, [sym])
        assert dep.dependencies[0]["_confidence"]["callee"] == "verified"


# ── 5.6  Budget configurable via CLI / API ──

class TestContextBudgetConfig:
    def test_cli_option_exists(self):
        """analyze.py main() accepts --context-budget."""
        import click.testing
        from analyze import main
        runner = click.testing.CliRunner()
        result = runner.invoke(main, ["--help"])
        assert "--context-budget" in result.output

    def test_api_request_model_has_field(self):
        from web.api.models.requests import PhaseARequest
        req = PhaseARequest(session_id="test", repo_path="/tmp")
        assert req.context_budget == 80_000

    def test_api_request_model_custom_budget(self):
        from web.api.models.requests import PhaseARequest
        req = PhaseARequest(session_id="test", repo_path="/tmp", context_budget=200_000)
        assert req.context_budget == 200_000

    def test_api_request_model_rejects_too_small(self):
        from web.api.models.requests import PhaseARequest
        with pytest.raises(Exception):
            PhaseARequest(session_id="test", repo_path="/tmp", context_budget=100)
