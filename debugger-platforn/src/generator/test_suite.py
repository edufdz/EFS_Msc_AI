"""
TestSuiteGenerator: combines personas, scenarios, and coverage goals
into an executable test suite.
"""

from __future__ import annotations

import random
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.coverage.models import CoverageGoals, SandboxConfig
from src.personas.affinity import select_persona_weighted
from src.personas.models import Persona
from src.scenarios.models import Scenario

from .models import TestCase, TestSuite, TestSuiteSummary

# Average seconds per turn, used for time estimation
_SECS_PER_TURN = 6
# Average LLM cost per turn (input + output tokens)
_COST_PER_TURN = 0.002


class TestSuiteGenerator:
    """
    Coverage-driven test suite generator.

    Allocation strategy:
      1. Tool coverage   – guarantee every tool hits its min-invocation target
      2. Edge-case coverage – allocate tests for ambiguity, missing info, etc.
      3. Stressor coverage – allocate chaos-injection tests
      4. Scenario fill    – pad remaining slots with random persona x scenario pairs
    """

    def __init__(
        self,
        agent_map: Dict,
        personas: List[Persona],
        scenarios: List[Scenario],
        coverage_goals: CoverageGoals,
        sandbox_config: SandboxConfig,
    ):
        self.agent_map = agent_map
        self.personas = personas
        self.scenarios = scenarios
        self.coverage_goals = coverage_goals
        self.sandbox_config = sandbox_config

        # Pre-index scenarios by required tool for fast lookup
        self._scenarios_by_tool: Dict[str, List[Scenario]] = defaultdict(list)
        for s in scenarios:
            for t in s.required_tools:
                self._scenarios_by_tool[t].append(s)

        # Pre-index personas by target_tool for tool-attack pairing
        self._personas_by_target_tool: Dict[str, List[Persona]] = defaultdict(list)
        for p in personas:
            if p.target_tool:
                self._personas_by_target_tool[p.target_tool].append(p)

        # Pre-index personas by target_flow for flow-attack pairing
        self._personas_by_target_flow: Dict[str, List[Persona]] = defaultdict(list)
        for p in personas:
            if p.target_flow:
                self._personas_by_target_flow[p.target_flow].append(p)

        # Pre-index scenarios by variant type
        self._scenarios_by_variant: Dict[str, List[Scenario]] = defaultdict(list)
        for s in scenarios:
            if s.variant_type:
                self._scenarios_by_variant[s.variant_type].append(s)

        # Pre-index scenarios by type
        self._scenarios_by_type: Dict[str, List[Scenario]] = defaultdict(list)
        for s in scenarios:
            self._scenarios_by_type[s.type].append(s)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, target_count: int = 250) -> TestSuite:
        """Generate a coverage-driven test suite."""
        if not self.scenarios:
            raise ValueError(
                "No scenarios available for test generation. "
                "Set ANTHROPIC_API_KEY for AI-generated scenarios, "
                "or pass --include-templates / include_templates=True to use built-in template scenarios."
            )

        test_cases: List[TestCase] = []

        # Phase 1: Tool coverage
        test_cases.extend(self._generate_tool_coverage_tests())

        # Phase 2: Edge-case coverage
        test_cases.extend(self._generate_edge_case_tests())

        # Phase 3: Stressor coverage
        test_cases.extend(self._generate_stressor_tests())

        # Phase 4: Fill remaining with scenario coverage
        remaining = max(0, target_count - len(test_cases))
        test_cases.extend(self._generate_scenario_fill(remaining))

        # If we overshot, trim to target
        if len(test_cases) > target_count:
            random.shuffle(test_cases)
            test_cases = test_cases[:target_count]

        # Shuffle and renumber
        random.shuffle(test_cases)
        for i, tc in enumerate(test_cases, 1):
            tc.test_number = i

        summary = self._build_summary(test_cases)

        return TestSuite(
            test_suite_id=str(uuid.uuid4()),
            agent_id=self.agent_map.get("agent_id", "unknown"),
            test_cases=test_cases,
            summary=summary,
            created_at=datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------------
    # Phase 1: Tool coverage
    # ------------------------------------------------------------------

    def _generate_tool_coverage_tests(self) -> List[TestCase]:
        tests: List[TestCase] = []
        min_invocations = self.coverage_goals.tool_coverage.min_invocations_per_tool

        for tool_name, min_calls in min_invocations.items():
            pool = self._scenarios_by_tool.get(tool_name, [])
            # Prefer tool-attack personas when available
            attack_personas = self._personas_by_target_tool.get(tool_name, [])
            for _ in range(min_calls):
                scenario = random.choice(pool) if pool else random.choice(self.scenarios)
                persona = random.choice(attack_personas) if attack_personas else select_persona_weighted(self.personas, scenario)
                tests.append(self._make_test_case(
                    scenario=scenario,
                    persona=persona,
                    coverage_goal="tool_coverage",
                    target_tool=tool_name,
                ))

        # Tool-combination tests
        for combo in self.coverage_goals.tool_coverage.tool_combinations:
            # Find a scenario that requires all tools in the combo, or pick any
            matching = [
                s for s in self.scenarios
                if all(t in s.required_tools for t in combo)
            ]
            scenario = random.choice(matching) if matching else random.choice(self.scenarios)
            persona = select_persona_weighted(self.personas, scenario)
            tests.append(self._make_test_case(
                scenario=scenario,
                persona=persona,
                coverage_goal="tool_combination",
                target_tool="+".join(combo),
            ))

        return tests

    # ------------------------------------------------------------------
    # Phase 2: Edge-case coverage
    # ------------------------------------------------------------------

    def _generate_edge_case_tests(self) -> List[TestCase]:
        tests: List[TestCase] = []
        ec = self.coverage_goals.edge_case_coverage

        mapping = {
            "ambiguity": ec.ambiguous_requests,
            "missing_info": ec.incomplete_information,
            "interruption": ec.user_changes_mind,
            "adversarial": ec.contradictory_statements,
        }

        for variant_type, count in mapping.items():
            pool = self._scenarios_by_variant.get(variant_type, [])
            # Fall back to edge_case type scenarios
            if not pool:
                pool = self._scenarios_by_type.get("edge_case", self.scenarios)
            for _ in range(count):
                scenario = random.choice(pool)
                persona = select_persona_weighted(self.personas, scenario)
                tests.append(self._make_test_case(
                    scenario=scenario,
                    persona=persona,
                    coverage_goal=f"edge_case:{variant_type}",
                ))

        return tests

    # ------------------------------------------------------------------
    # Phase 3: Stressor coverage
    # ------------------------------------------------------------------

    def _generate_stressor_tests(self) -> List[TestCase]:
        tests: List[TestCase] = []
        sc = self.coverage_goals.stressor_coverage

        stressor_configs = {
            "timeout": (sc.timeout_scenarios, {"timeout": True, "malformed_response": False, "data_conflict": False}),
            "malformed_response": (sc.malformed_response_scenarios, {"timeout": False, "malformed_response": True, "data_conflict": False}),
            "data_conflict": (sc.data_conflict_scenarios, {"timeout": False, "malformed_response": False, "data_conflict": True}),
        }

        # Prefer error_path scenarios for stressor tests
        error_pool = self._scenarios_by_type.get("error_path", [])

        for stressor_name, (count, chaos_override) in stressor_configs.items():
            pool = error_pool if error_pool else self.scenarios
            for _ in range(count):
                scenario = random.choice(pool)
                persona = select_persona_weighted(self.personas, scenario)
                tests.append(self._make_test_case(
                    scenario=scenario,
                    persona=persona,
                    coverage_goal=f"stressor:{stressor_name}",
                    chaos_override=chaos_override,
                ))

        return tests

    # ------------------------------------------------------------------
    # Phase 4: Scenario fill
    # ------------------------------------------------------------------

    def _generate_scenario_fill(self, count: int) -> List[TestCase]:
        tests: List[TestCase] = []
        for _ in range(count):
            scenario = random.choice(self.scenarios)
            persona = select_persona_weighted(self.personas, scenario)
            tests.append(self._make_test_case(
                scenario=scenario,
                persona=persona,
                coverage_goal="scenario_coverage",
            ))
        return tests

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_test_case(
        self,
        scenario: Scenario,
        persona: Persona,
        coverage_goal: str,
        target_tool: Optional[str] = None,
        chaos_override: Optional[Dict[str, bool]] = None,
    ) -> TestCase:
        exec_config = self._build_exec_config(scenario, chaos_override)
        return TestCase(
            test_id=str(uuid.uuid4()),
            test_number=0,  # renumbered later
            scenario=scenario,
            persona=persona,
            execution_config=exec_config,
            coverage_goal=coverage_goal,
            target_tool=target_tool,
            difficulty=scenario.difficulty,
            estimated_duration_sec=scenario.estimated_turns * _SECS_PER_TURN,
        )

    def _build_exec_config(
        self,
        scenario: Scenario,
        chaos_override: Optional[Dict[str, bool]] = None,
    ) -> Dict[str, Any]:
        chaos = scenario.chaos_config
        safety = self.sandbox_config.safety

        if chaos_override:
            injection = chaos_override
        else:
            injection = {
                "timeout": random.random() < chaos.inject_timeout,
                "malformed_response": random.random() < chaos.inject_malformed_response,
                "data_conflict": random.random() < chaos.inject_data_conflict,
            }

        return {
            "max_turns": safety.get("max_turns_per_episode", 20),
            "timeout_per_tool_call_sec": safety.get("timeout_per_tool_call_sec", 10),
            "sandbox_mode": self.sandbox_config.mode,
            "chaos_injection": injection,
            "pii_detection": safety.get("pii_detection", True),
        }

    def _build_summary(self, test_cases: List[TestCase]) -> TestSuiteSummary:
        by_difficulty: Dict[str, int] = defaultdict(int)
        by_coverage: Dict[str, int] = defaultdict(int)
        by_type: Dict[str, int] = defaultdict(int)
        by_persona: Dict[str, int] = defaultdict(int)
        tool_counts: Dict[str, int] = defaultdict(int)

        total_duration_sec = 0

        for tc in test_cases:
            by_difficulty[tc.difficulty] += 1
            by_coverage[tc.coverage_goal] += 1
            by_type[tc.scenario.type] += 1
            by_persona[tc.persona.name] += 1
            total_duration_sec += tc.estimated_duration_sec

            if tc.target_tool:
                for t in tc.target_tool.split("+"):
                    tool_counts[t] += 1
            for t in tc.scenario.required_tools:
                tool_counts[t] += 1

        total_turns = sum(tc.scenario.estimated_turns for tc in test_cases)

        return TestSuiteSummary(
            total_tests=len(test_cases),
            by_difficulty=dict(by_difficulty),
            by_coverage_goal=dict(by_coverage),
            by_scenario_type=dict(by_type),
            by_persona=dict(by_persona),
            tool_invocation_counts=dict(tool_counts),
            estimated_duration_min=round(total_duration_sec / 60, 1),
            estimated_cost_usd=round(total_turns * _COST_PER_TURN, 2),
        )
