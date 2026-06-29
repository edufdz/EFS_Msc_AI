"""Integration test: full Phase A pipeline against Python agent fixture."""

import json
import os
import time

import pytest

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")
PYTHON_AGENT = os.path.join(FIXTURES, "python_agent")


def _run_pipeline(repo_path, skip_ai=True):
    """Run the Phase A pipeline programmatically."""
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


class TestPythonPipeline:
    @pytest.fixture(scope="class")
    def agent_map(self):
        return _run_pipeline(PYTHON_AGENT)

    def test_valid_json_structure(self, agent_map):
        assert agent_map["version"] == "1.0"
        assert "components" in agent_map
        assert "tools" in agent_map["components"]

    def test_framework_detected(self, agent_map):
        assert agent_map["metadata"]["framework"] == "langchain"
        assert agent_map["metadata"]["framework_confidence"] > 0.0

    def test_tools_extracted(self, agent_map):
        tools = agent_map["components"]["tools"]
        names = [t["name"] for t in tools]
        assert len(tools) >= 3
        assert "process_refund" in names or "search_knowledge_base" in names

    def test_risks_have_taxonomy(self, agent_map):
        risks = agent_map["risk_flags"]["all_risks"]
        assert len(risks) >= 1
        has_taxonomy = any(r.get("taxonomy_ids") for r in risks)
        assert has_taxonomy

    def test_tools_have_preconditions(self, agent_map):
        tools = agent_map["components"]["tools"]
        has_pre = any(t.get("preconditions") for t in tools)
        assert has_pre, "At least one tool should have preconditions"

    def test_tools_have_state_modifying(self, agent_map):
        tools = agent_map["components"]["tools"]
        has_mod = any(t.get("state_modifying") is True for t in tools)
        assert has_mod, "At least one tool should be state_modifying"

    def test_guardrails_extracted(self, agent_map):
        guardrails = agent_map.get("guardrails", {})
        assert guardrails.get("total_rules", 0) >= 3

    def test_guardrail_categories(self, agent_map):
        guardrails = agent_map.get("guardrails", {})
        by_cat = guardrails.get("by_category", {})
        assert "prohibition" in by_cat or "requirement" in by_cat

    def test_behavioural_model_present(self, agent_map):
        bm = agent_map.get("behavioural_model", {})
        assert "dependency_graph" in bm
        assert "coverage_targets" in bm

    def test_language_english(self, agent_map):
        assert agent_map["metadata"]["conversation_language"] == "English"

    def test_performance(self):
        start = time.time()
        _run_pipeline(PYTHON_AGENT)
        elapsed = time.time() - start
        assert elapsed < 30, f"Pipeline took {elapsed:.1f}s, should be < 30s"


class TestAgentMapSchema:
    """Validate that all expected fields exist in the Agent Map."""

    @pytest.fixture(scope="class")
    def agent_map(self):
        return _run_pipeline(PYTHON_AGENT)

    def test_top_level_keys(self, agent_map):
        required = ["version", "generated_at", "agent_id", "metadata",
                     "components", "risk_flags", "graph", "source_files"]
        for key in required:
            assert key in agent_map, f"Missing top-level key: {key}"

    def test_tool_new_fields(self, agent_map):
        for tool in agent_map["components"]["tools"]:
            assert "preconditions" in tool
            assert "postconditions" in tool
            assert "side_effects" in tool
            assert "state_modifying" in tool
            assert isinstance(tool["preconditions"], list)
            assert isinstance(tool["state_modifying"], bool)

    def test_risk_taxonomy_fields(self, agent_map):
        for risk in agent_map["risk_flags"]["all_risks"]:
            assert "taxonomy_ids" in risk
            assert "taxonomy_names" in risk
            assert isinstance(risk["taxonomy_ids"], list)

    def test_guardrails_section(self, agent_map):
        g = agent_map.get("guardrails", {})
        assert "rules" in g
        assert "total_rules" in g
        assert "total_complexity" in g
        assert "by_category" in g
        assert "guardrail_language" in g

    def test_guardrail_rule_fields(self, agent_map):
        rules = agent_map.get("guardrails", {}).get("rules", [])
        if rules:
            r = rules[0]
            assert "rule_id" in r
            assert "text" in r
            assert "category" in r
            assert "complexity" in r
            assert "scope" in r

    def test_behavioural_model_section(self, agent_map):
        bm = agent_map.get("behavioural_model", {})
        assert "dependency_graph" in bm
        assert "edges" in bm["dependency_graph"]
        assert "properties" in bm["dependency_graph"]
        assert "coverage_targets" in bm

    def test_language_metadata(self, agent_map):
        lang = agent_map["metadata"]["language"]
        assert "primary_language" in lang
        assert "conversation_languages" in lang
        assert "code_switching_detected" in lang

    def test_backward_compatibility(self, agent_map):
        """Old fields must still be present."""
        assert "framework" in agent_map["metadata"]
        assert "framework_confidence" in agent_map["metadata"]
        assert "pii_handling" in agent_map["risk_flags"]
        assert "critical_actions" in agent_map["risk_flags"]
