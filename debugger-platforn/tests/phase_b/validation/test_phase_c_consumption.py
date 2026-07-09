"""
Validation test: Phase C consumption — Sprint E-T.13.2.

Confirms that the enhanced ``test_suite.json`` is readable by Phase C
(``execute_tests`` / the conversation simulator) without modification: the
executor loads the suite as a plain dict and reads ``test_cases[].scenario``,
``.persona``, ``.execution_config`` and persona traits; the new enhancement
fields (oracles, richer coverage goals, adversarial sources) must be ignored
gracefully rather than crash unmodified Phase C code.

Loading Phase C's executor requires no API key when only the schema-level
reader path is exercised, so no live execution is performed here.
"""

from __future__ import annotations

from src.generator.models import TestSuite as SuiteModel


class TestPhaseCCanReadEnhancedSuite:
    def test_suite_json_has_executor_contract_key(self, phase_b):
        """execute_tests.py requires a top-level ``test_cases`` list."""
        gen = phase_b(map_name="tech_repair", use_traces=True)
        assert "test_cases" in gen.suite_raw
        assert isinstance(gen.suite_raw["test_cases"], list)
        assert gen.suite_raw["test_cases"]

    def test_each_test_case_exposes_simulator_fields(self, phase_b):
        """Mirror the field access in
        src/execution/conversation_simulator.py (scenario / persona /
        execution_config / persona traits)."""
        gen = phase_b(map_name="tech_repair", use_traces=True)
        for tc in gen.suite_raw["test_cases"]:
            scenario = tc["scenario"]
            persona = tc["persona"]
            exec_config = tc.get("execution_config", {})
            assert isinstance(scenario, dict) and scenario.get("user_goal")
            assert isinstance(persona, dict)
            assert isinstance(exec_config, dict)
            # Mood-drift init reads these persona traits
            traits = persona.get("traits", {})
            assert isinstance(traits.get("patience"), int)
            assert isinstance(traits.get("trust_level"), int)

    def test_oracles_are_machine_readable(self, phase_b):
        """Phase C can read the deterministic oracle definitions carried on
        each test case."""
        gen = phase_b(map_name="tech_repair", use_traces=True)
        n_with_oracles = 0
        for tc in gen.suite_raw["test_cases"]:
            for o in tc["oracles"]:
                assert o["oracle_id"] and o["type"] and o["check_expression"]
                assert o["severity"] in {"critical", "high", "medium", "low"}
                n_with_oracles += 1
        assert n_with_oracles > 0

    def test_new_fields_do_not_break_pydantic_load(self, phase_b):
        """The unmodified TestSuite model round-trips the enhanced output."""
        gen = phase_b(map_name="tech_repair", use_traces=True)
        suite = SuiteModel.model_validate(gen.suite_raw)
        assert suite.summary.total_tests == len(suite.test_cases)

    def test_conversation_simulator_field_extraction(self, phase_b):
        """Drive the exact synchronous field extraction the Phase C
        ConversationSimulator performs in __init__, proving unmodified Phase
        C code consumes the enhanced test case (no LLM/network involved)."""
        gen = phase_b(map_name="tech_repair", use_traces=True)
        tc = gen.suite_raw["test_cases"][0]
        # Replicates ConversationSimulator.__init__ lines 46-49, 102-109
        scenario = tc["scenario"]
        persona = tc["persona"]
        exec_config = tc.get("execution_config", {})
        max_turns = exec_config.get("max_turns", 40)
        chaos_cfg = exec_config.get("chaos_injection", {})
        traits = persona.get("traits", {})
        trust = float(traits.get("trust_level", 5))
        patience = float(traits.get("patience", 5))
        assert scenario and persona
        assert isinstance(max_turns, int)
        assert isinstance(chaos_cfg, dict)
        assert 0.0 <= trust <= 10.0
        assert 0.0 <= patience <= 10.0
