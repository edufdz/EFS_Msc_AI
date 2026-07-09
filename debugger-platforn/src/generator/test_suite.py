"""
TestSuiteGenerator: combines personas, scenarios, and coverage goals
into an executable test suite.
"""

from __future__ import annotations

import random
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.coverage.models import CoverageGoals, SandboxConfig
from src.personas.affinity import select_persona_weighted
from src.personas.models import Persona
from src.scenarios.models import Scenario

from .models import TestCase, TestSuite, TestSuiteSummary
from .prioritiser import prioritise_suite

# Average seconds per turn, used for time estimation
_SECS_PER_TURN = 6
# Average LLM cost per turn (input + output tokens)
_COST_PER_TURN = 0.002

# OWASP LLM 2025 / OWASP Agentic 2026 taxonomy ID shape (e.g. LLM01, ASI05)
_TAXONOMY_ID_RE = re.compile(r"^(?:LLM|ASI)\d{2}$")


def _looks_like_taxonomy_id(value: str) -> bool:
    """True when a scenario/persona tag is an OWASP/ASI taxonomy ID."""
    return bool(_TAXONOMY_ID_RE.match(value or ""))


class TestSuiteGenerator:
    """
    Coverage-driven test suite generator (candidate-then-prioritise, Sprint E8).

    Rather than emitting tests in a fixed phase priority, every phase below is
    now a candidate *generator*: each contributes tests to a single pool, and
    the APFD-weighted prioritiser (:mod:`src.generator.prioritiser`) orders the
    union so that early tests maximise marginal predicted-fault coverage,
    weighted by fault-proneness (risk, operational profile, failure history,
    oracle density).  The top ``target_count`` tests are kept.

    Candidate generators (all preserved from the prior fixed-phase pipeline):
      - Production seeds (Sprint E1) – seed-preferential production-failure scenarios
      - Tool/interaction coverage (Sprint E3) – covering-array rows + per-tool floor
      - Transition coverage (Sprint E3) – FSM transitions, 1-switch pairs, round trips
      - Edge-case coverage – ambiguity, missing info, interruption, adversarial
      - Risk-guided adversarial coverage (Sprint E5) – taxonomy/taint attacks
      - Stressor coverage – chaos-injection tests
      - Scenario fill – random persona x scenario pairs to reach the budget

    The prioritiser tiers seeds first, then coverage-forced / adversarial tests,
    then the rest, so a budget cut drops fill before coverage before seeds — the
    same preservation contract the old overshoot-trim enforced.
    """

    def __init__(
        self,
        agent_map: Dict,
        personas: List[Persona],
        scenarios: List[Scenario],
        coverage_goals: CoverageGoals,
        sandbox_config: SandboxConfig,
        seed_budget_fraction: float = 0.2,
        trace_result: Any = None,
    ):
        self.agent_map = agent_map
        self.personas = personas
        self.scenarios = scenarios
        self.coverage_goals = coverage_goals
        self.sandbox_config = sandbox_config
        # Fraction of the test budget reserved for production-seed scenarios
        # (Sprint E1, Phase 0 allocation)
        self.seed_budget_fraction = seed_budget_fraction
        # Phase A trace analysis (tool_frequency, failure_patterns) — feeds the
        # operational-profile weighting of the APFD prioritiser (Sprint E8).
        self.trace_result = trace_result

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

        # --- Candidate generation: every former phase is now a generator ---
        # feeding a single pool.  Order of appended lists no longer determines
        # test priority; the prioritiser does (Sprint E8).
        candidates: List[TestCase] = []

        # Production-seed coverage (Sprint E1)
        candidates.extend(self._generate_seed_coverage_tests(target_count))
        # Tool/interaction coverage — covering array + per-tool floor (Sprint E3)
        candidates.extend(self._generate_tool_coverage_tests())
        # FSM transition coverage (Sprint E3)
        candidates.extend(self._generate_transition_coverage_tests())
        # Edge-case coverage
        candidates.extend(self._generate_edge_case_tests())
        # Risk-guided adversarial coverage (Sprint E5)
        candidates.extend(self._generate_adversarial_coverage_tests())
        # Stressor coverage
        candidates.extend(self._generate_stressor_tests())
        # Scenario fill — top the pool up toward the target budget
        remaining = max(0, target_count - len(candidates))
        candidates.extend(self._generate_scenario_fill(remaining))

        # --- Prioritise the whole pool by marginal fault coverage (APFD),
        # weighted by fault-proneness and the operational profile (Sprint E8).
        # Seeds are tiered first, then coverage-forced / adversarial, then the
        # rest — so taking the top target_count drops fill before coverage
        # before seeds, preserving the E1/E3/E5 contract.
        ordered = prioritise_suite(candidates, self.agent_map, self.trace_result)

        # Keep the best target_count and number them in prioritised order so the
        # measurement harness (which reads test_number as execution order)
        # sees the APFD-optimised ordering.
        test_cases = ordered[:target_count]
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
    # Phase 0: Production-seed coverage (Sprint E1)
    # ------------------------------------------------------------------

    def _generate_seed_coverage_tests(self, target_count: int) -> List[TestCase]:
        """Seed-preferential allocation: production-failure seed scenarios
        get first claim on the budget (default 20%, configurable via
        ``seed_budget_fraction``). One test per seed scenario, capped at
        the reserved budget."""
        seed_scenarios = [s for s in self.scenarios if s.source == "production_seed"]
        if not seed_scenarios:
            return []

        budget = max(1, int(target_count * self.seed_budget_fraction))
        seed_personas = [p for p in self.personas if p.source == "production_seed"]

        tests: List[TestCase] = []
        for scenario in seed_scenarios[:budget]:
            if seed_personas:
                persona = random.choice(seed_personas)
            else:
                persona = select_persona_weighted(self.personas, scenario)
            tests.append(self._make_test_case(
                scenario=scenario,
                persona=persona,
                coverage_goal="production_seed",
                target_tool=scenario.required_tools[0] if scenario.required_tools else None,
            ))
        return tests

    # ------------------------------------------------------------------
    # Phase 1: Tool/interaction coverage (Sprint E3)
    # ------------------------------------------------------------------

    def _generate_tool_coverage_tests(self) -> List[TestCase]:
        """Covering-array-driven interaction coverage with a per-tool floor.

        Instead of repeating each tool N times by risk (critical=25x, ...),
        each covering-array row — a t-way combination of tool selection and
        key parameter values — becomes exactly one test case.  The small
        per-tool floor (3x max) is then topped up only for tools the
        covering array did not already exercise enough.
        """
        tests: List[TestCase] = []
        tool_coverage = self.coverage_goals.tool_coverage
        min_invocations = tool_coverage.min_invocations_per_tool

        # How many Phase-1 tests already target each tool
        tests_per_tool: Dict[str, int] = defaultdict(int)

        # --- Covering-array rows: one test per row ---
        for row in getattr(tool_coverage, "covering_array", None) or []:
            tool_name = self._tool_of_row(row)
            pool = self._scenarios_by_tool.get(tool_name, []) if tool_name else []
            scenario = random.choice(pool) if pool else random.choice(self.scenarios)
            attack_personas = self._personas_by_target_tool.get(tool_name, []) if tool_name else []
            persona = (
                random.choice(attack_personas) if attack_personas
                else select_persona_weighted(self.personas, scenario)
            )
            tests.append(self._make_test_case(
                scenario=scenario,
                persona=persona,
                coverage_goal="interaction_coverage",
                target_tool=tool_name,
                interaction_config=dict(row),
            ))
            if tool_name:
                tests_per_tool[tool_name] += 1

        # --- Per-tool floor (minimum guarantee for stochastic variation) ---
        for tool_name, min_calls in min_invocations.items():
            needed = max(0, min_calls - tests_per_tool.get(tool_name, 0))
            pool = self._scenarios_by_tool.get(tool_name, [])
            # Prefer tool-attack personas when available
            attack_personas = self._personas_by_target_tool.get(tool_name, [])
            for _ in range(needed):
                scenario = random.choice(pool) if pool else random.choice(self.scenarios)
                persona = random.choice(attack_personas) if attack_personas else select_persona_weighted(self.personas, scenario)
                tests.append(self._make_test_case(
                    scenario=scenario,
                    persona=persona,
                    coverage_goal="tool_coverage",
                    target_tool=tool_name,
                ))

        # Tool-combination tests (legacy fallback when no covering array)
        for combo in tool_coverage.tool_combinations:
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

    @staticmethod
    def _tool_of_row(row: Dict[str, str]) -> Optional[str]:
        """The tool a covering-array row targets (its 'tool' factor, or the
        tool prefix of the first 'tool.param' factor)."""
        if not row:
            return None
        if "tool" in row:
            return row["tool"]
        for name in row:
            if "." in name:
                return name.split(".", 1)[0]
        return None

    # ------------------------------------------------------------------
    # Phase 1.5: FSM transition coverage (Sprint E3)
    # ------------------------------------------------------------------

    def _generate_transition_coverage_tests(self) -> List[TestCase]:
        """One test per FSM coverage target: every transition (0-switch),
        every transition pair (1-switch), and each round-trip path.

        Each target is matched to a scenario that exercises the
        transition's trigger tool(s); the transition itself is recorded in
        the execution config for Phase C."""
        tcg = self.coverage_goals.transition_coverage
        if tcg is None:
            return []

        tests: List[TestCase] = []

        # --- All transitions: every (from, trigger, to) at least once ---
        for from_state, trigger, to_state in tcg.all_transitions:
            scenario = self._scenario_for_tools([trigger])
            persona = select_persona_weighted(self.personas, scenario)
            tests.append(self._make_test_case(
                scenario=scenario,
                persona=persona,
                coverage_goal="transition_coverage",
                target_tool=trigger if trigger in self._scenarios_by_tool else None,
                transition_target={
                    "type": "transition",
                    "from_state": from_state,
                    "trigger": trigger,
                    "to_state": to_state,
                },
            ))

        # --- Transition pairs (1-switch coverage) ---
        for state_a, trigger_1, state_b, trigger_2 in tcg.transition_pairs:
            scenario = self._scenario_for_tools([trigger_1, trigger_2])
            persona = select_persona_weighted(self.personas, scenario)
            known = [t for t in (trigger_1, trigger_2) if t in self._scenarios_by_tool]
            tests.append(self._make_test_case(
                scenario=scenario,
                persona=persona,
                coverage_goal="transition_pair",
                target_tool="+".join(known) if known else None,
                transition_target={
                    "type": "transition_pair",
                    "from_state": state_a,
                    "trigger_1": trigger_1,
                    "intermediate_state": state_b,
                    "trigger_2": trigger_2,
                },
            ))

        # --- Round-trip paths (initial -> ... -> initial/terminal) ---
        for path in tcg.round_trip_paths:
            triggers = path[1::2]  # alternating state/trigger sequence
            scenario = self._scenario_for_tools(triggers)
            persona = select_persona_weighted(self.personas, scenario)
            known = [t for t in triggers if t in self._scenarios_by_tool]
            tests.append(self._make_test_case(
                scenario=scenario,
                persona=persona,
                coverage_goal="round_trip",
                target_tool="+".join(dict.fromkeys(known)) if known else None,
                transition_target={"type": "round_trip", "path": list(path)},
            ))

        return tests

    def _scenario_for_tools(self, tools: List[str]) -> Scenario:
        """Pick a scenario exercising as many of the given tools as possible:
        all of them, then any of them, then any scenario at all."""
        wanted = [t for t in tools if t]
        if wanted:
            matching = [
                s for s in self.scenarios
                if all(t in s.required_tools for t in wanted)
            ]
            if matching:
                return random.choice(matching)
            partial = [
                s for s in self.scenarios
                if any(t in s.required_tools for t in wanted)
            ]
            if partial:
                return random.choice(partial)
        return random.choice(self.scenarios)

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
    # Phase 2.5: Risk-guided adversarial coverage (Sprint E5)
    # ------------------------------------------------------------------

    def _generate_adversarial_coverage_tests(self) -> List[TestCase]:
        """One adversarial test per taxonomy-mapped / taint-flow attack
        scenario, ensuring every taxonomy ID present in risk_flags is
        exercised at least once. Adversarial personas (source="adversarial")
        matched to the scenario's taxonomy tag are preferred; otherwise any
        adversarial persona, then an affinity-weighted fallback."""
        adversarial_scenarios = [
            s for s in self.scenarios
            if s.source in ("adversarial_taxonomy", "adversarial_taint")
        ]
        if not adversarial_scenarios:
            return []

        adversarial_personas = [p for p in self.personas if p.source == "adversarial"]
        personas_by_tax: Dict[str, List[Persona]] = defaultdict(list)
        for p in adversarial_personas:
            for tag in getattr(p, "tags", []) or []:
                personas_by_tax[tag].append(p)

        tests: List[TestCase] = []
        for scenario in adversarial_scenarios:
            tax_tags = [t for t in scenario.tags if _looks_like_taxonomy_id(t)]
            persona = None
            for tag in tax_tags:
                pool = personas_by_tax.get(tag)
                if pool:
                    persona = random.choice(pool)
                    break
            if persona is None and adversarial_personas:
                persona = random.choice(adversarial_personas)
            if persona is None:
                persona = select_persona_weighted(self.personas, scenario)

            primary_tax = tax_tags[0] if tax_tags else "adversarial"
            tests.append(self._make_test_case(
                scenario=scenario,
                persona=persona,
                coverage_goal=f"adversarial:{primary_tax}",
                target_tool=scenario.required_tools[0] if scenario.required_tools else None,
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
        interaction_config: Optional[Dict[str, str]] = None,
        transition_target: Optional[Dict[str, Any]] = None,
    ) -> TestCase:
        exec_config = self._build_exec_config(scenario, chaos_override)
        # Sprint E3: carry the covering-array row / FSM target so Phase C
        # can steer the conversation toward the intended interaction
        if interaction_config:
            exec_config["interaction_config"] = interaction_config
        if transition_target:
            exec_config["transition_target"] = transition_target
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
            # Carry the scenario's non-LLM oracles onto the test case (Sprint E4)
            oracles=[o.to_test_case_dict() for o in getattr(scenario, "oracles", [])],
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
        oracles_by_type: Dict[str, int] = defaultdict(int)
        total_oracles = 0

        total_duration_sec = 0

        for tc in test_cases:
            by_difficulty[tc.difficulty] += 1
            by_coverage[tc.coverage_goal] += 1
            by_type[tc.scenario.type] += 1
            by_persona[tc.persona.name] += 1
            total_duration_sec += tc.estimated_duration_sec

            # Oracle counts (Sprint E4)
            total_oracles += len(tc.oracles)
            for o in tc.oracles:
                oracles_by_type[o.get("type", "unknown")] += 1

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
            total_oracles=total_oracles,
            oracles_by_type=dict(oracles_by_type),
        )
