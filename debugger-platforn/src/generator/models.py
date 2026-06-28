"""
Pydantic models for the Test Suite Generator (Phase B4).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.personas.models import Persona
from src.scenarios.models import Scenario


class TestCase(BaseModel):
    test_id: str
    test_number: int
    scenario: Scenario
    persona: Persona
    execution_config: Dict[str, Any]
    coverage_goal: str  # tool_coverage|edge_case_coverage|stressor_coverage|scenario_coverage
    target_tool: Optional[str] = None
    difficulty: str  # easy|medium|hard
    estimated_duration_sec: int = 30


class TestSuiteSummary(BaseModel):
    total_tests: int
    by_difficulty: Dict[str, int] = Field(default_factory=dict)
    by_coverage_goal: Dict[str, int] = Field(default_factory=dict)
    by_scenario_type: Dict[str, int] = Field(default_factory=dict)
    by_persona: Dict[str, int] = Field(default_factory=dict)
    tool_invocation_counts: Dict[str, int] = Field(default_factory=dict)
    estimated_duration_min: float = 0.0
    estimated_cost_usd: float = 0.0


class TestSuite(BaseModel):
    test_suite_id: str
    agent_id: str
    test_cases: List[TestCase]
    summary: TestSuiteSummary
    created_at: datetime
