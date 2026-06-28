"""
Pydantic models for Coverage Goals & Sandbox Configuration (Phase B3).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ToolCoverageGoals(BaseModel):
    target_percentage: int = Field(default=100, ge=0, le=100)
    min_invocations_per_tool: Dict[str, int] = Field(default_factory=dict)
    tool_combinations: List[List[str]] = Field(default_factory=list)


class EdgeCaseCoverageGoals(BaseModel):
    ambiguous_requests: int = 40
    incomplete_information: int = 35
    user_changes_mind: int = 20
    contradictory_statements: int = 15


class StressorCoverageGoals(BaseModel):
    timeout_scenarios: int = 50
    malformed_response_scenarios: int = 25
    data_conflict_scenarios: int = 30


class CoverageGoals(BaseModel):
    tool_coverage: ToolCoverageGoals
    edge_case_coverage: EdgeCaseCoverageGoals
    stressor_coverage: StressorCoverageGoals


class ToolSandboxConfig(BaseModel):
    mode: str = "mock"  # real|mock|capture
    mock_strategy: Optional[str] = "schema_based"
    rate_limit: Optional[int] = None
    require_confirmation: bool = False
    latency_simulation: Optional[Dict[str, int]] = None


class SandboxConfig(BaseModel):
    mode: str = "full_mock"
    tool_configs: Dict[str, ToolSandboxConfig] = Field(default_factory=dict)
    cost_limits: Dict[str, float] = Field(default_factory=dict)
    safety: Dict[str, Any] = Field(default_factory=dict)


class TestConfiguration(BaseModel):
    config_id: str
    agent_id: str
    coverage_goals: CoverageGoals
    sandbox_config: SandboxConfig
    created_at: datetime
