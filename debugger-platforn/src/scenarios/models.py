"""
Pydantic models for the Scenario Library system.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class ScenarioSuccessConditions(BaseModel):
    tool_called: Optional[str] = None
    tools_called: Optional[List[str]] = None
    user_satisfied: bool = False  # Must be explicitly opted-in; default False prevents premature passes
    info_provided: Optional[List[str]] = None


class ScenarioFailureConditions(BaseModel):
    hallucinated_response: bool = False
    wrong_tool_called: bool = False
    pii_leaked: bool = False


class ChaosConfig(BaseModel):
    inject_timeout: float = Field(default=0.1, ge=0.0, le=1.0)
    inject_malformed_response: float = Field(default=0.05, ge=0.0, le=1.0)
    inject_data_conflict: float = Field(default=0.08, ge=0.0, le=1.0)


class Scenario(BaseModel):
    scenario_id: str
    title: str
    description: str
    user_goal: str
    category: str  # support|sales|scheduling|etc
    difficulty: str = "medium"  # easy|medium|hard
    type: str = "happy_path"  # happy_path|error_path|edge_case
    required_tools: List[str] = []
    optional_tools: List[str] = []
    forbidden_tools: List[str] = []
    success_conditions: ScenarioSuccessConditions = Field(default_factory=ScenarioSuccessConditions)
    failure_conditions: ScenarioFailureConditions = Field(default_factory=ScenarioFailureConditions)
    chaos_config: ChaosConfig = Field(default_factory=ChaosConfig)
    tags: List[str] = []
    estimated_turns: int = 5
    source: str = "template"  # template|ai_generated|variant|tlahuac
    base_scenario_id: Optional[str] = None
    variant_type: Optional[str] = None  # ambiguity|missing_info|interruption|constraint|error
    starter_openers: List[str] = []  # Pre-written first messages (e.g. from tlahuac scenarios)
    created_at: datetime


class ScenarioCatalog(BaseModel):
    catalog_id: str
    agent_id: str
    base_scenarios_count: int
    total_scenarios_count: int
    scenarios: List[Scenario]
    created_at: datetime
