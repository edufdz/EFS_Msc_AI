"""Integration test: full Phase A pipeline against TypeScript agent fixture."""

import os

import pytest

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")
TS_AGENT = os.path.join(FIXTURES, "typescript_agent")


def _run_pipeline(repo_path):
    from src.ingestion.ingestor import ingest_directory
    from src.analysis.static_analyzer import analyze_files
    from src.patterns.detector import detect_patterns
    from src.risk.analyzer import analyze_risks
    from src.graph.builder import generate_agent_map

    ingestion = ingest_directory(repo_path)
    file_paths = [f.path for f in ingestion.files]
    all_symbols = analyze_files(file_paths)
    pattern_result = detect_patterns(all_symbols, ingestion.prompt_files)
    risks, taint_flows = analyze_risks(pattern_result.tools, pattern_result.prompts, all_symbols)

    agent_map = generate_agent_map(
        all_symbols=all_symbols,
        pattern_result=pattern_result,
        ai_result=None,
        risks=risks,
        entry_points=ingestion.entry_points,
        root_path=ingestion.root_path,
        taint_flows=taint_flows,
    )
    return agent_map


class TestTypeScriptPipeline:
    @pytest.fixture(scope="class")
    def agent_map(self):
        return _run_pipeline(TS_AGENT)

    def test_tools_extracted(self, agent_map):
        tools = agent_map["components"]["tools"]
        names = [t["name"] for t in tools]
        assert len(tools) >= 2
        assert "book_appointment" in names or "lookup_order" in names

    def test_tree_sitter_extracts_param_types(self, agent_map):
        """Regression: old regex parser couldn't extract TS parameter types.
        Verify the tree-sitter parser is being used by checking that
        functions in the static analysis have typed params.
        """
        from src.analysis.static_analyzer import analyze_files
        from src.ingestion.ingestor import ingest_directory
        ingestion = ingest_directory(TS_AGENT)
        ts_files = [f.path for f in ingestion.files if f.path.endswith((".ts", ".tsx"))]
        symbols = analyze_files(ts_files)
        all_funcs = []
        for sym in symbols:
            all_funcs.extend(sym.functions)
        typed_params = [
            p for f in all_funcs for p in f.params if p.type_annotation
        ]
        assert len(typed_params) > 0, "Tree-sitter should extract typed params from TS"

    def test_guardrails_extracted(self, agent_map):
        guardrails = agent_map.get("guardrails", {})
        assert guardrails.get("total_rules", 0) >= 2

    def test_behavioural_model_present(self, agent_map):
        bm = agent_map.get("behavioural_model", {})
        assert "dependency_graph" in bm

    def test_all_new_fields_present(self, agent_map):
        for tool in agent_map["components"]["tools"]:
            assert "preconditions" in tool
            assert "postconditions" in tool
            assert "side_effects" in tool
            assert "state_modifying" in tool


class TestSpanishPipeline:
    @pytest.fixture(scope="class")
    def agent_map(self):
        spanish_path = os.path.join(FIXTURES, "spanish_agent")
        return _run_pipeline(spanish_path)

    def test_spanish_language_detected(self, agent_map):
        assert agent_map["metadata"]["conversation_language"] == "Spanish"

    def test_guardrails_in_spanish(self, agent_map):
        guardrails = agent_map.get("guardrails", {})
        assert guardrails.get("total_rules", 0) >= 4
        rules = guardrails.get("rules", [])
        spanish_rules = [r for r in rules if r.get("language") == "Spanish"]
        assert len(spanish_rules) >= 2

    def test_guardrail_language_matches(self, agent_map):
        guardrails = agent_map.get("guardrails", {})
        assert guardrails.get("guardrail_language") == "Spanish"
        assert guardrails.get("guardrail_language_matches_conversation") is True

    def test_tools_extracted(self, agent_map):
        tools = agent_map["components"]["tools"]
        assert len(tools) >= 1
