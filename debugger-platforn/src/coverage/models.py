"""
Pydantic models for Coverage Goals & Sandbox Configuration (Phase B3).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field


class ToolCoverageGoals(BaseModel):
    target_percentage: int = Field(default=100, ge=0, le=100)
    min_invocations_per_tool: Dict[str, int] = Field(default_factory=dict)
    tool_combinations: List[List[str]] = Field(default_factory=list)
    # Sprint E3: t-way interaction coverage over tool x parameter factors.
    # Each covering-array row maps factor name -> level and becomes one
    # test configuration (replaces flat per-tool repetition).
    interaction_strength: int = 2
    covering_array: List[Dict[str, str]] = Field(default_factory=list)


class TransitionCoverageGoals(BaseModel):
    """FSM transition coverage targets (Sprint E3)."""

    # (from_state, trigger, to_state) — every transition at least once
    all_transitions: List[Tuple[str, str, str]] = Field(default_factory=list)
    # (state_A, trigger_1, state_B, trigger_2) — 1-switch pairs
    transition_pairs: List[Tuple[str, str, str, str]] = Field(default_factory=list)
    # Alternating state/trigger sequences: initial -> ... -> initial/terminal
    round_trip_paths: List[List[str]] = Field(default_factory=list)


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
    # Sprint E3: FSM transition coverage (None when the agent map has no
    # behavioural_model.fsm section — e.g. no trace data was available)
    transition_coverage: Optional[TransitionCoverageGoals] = None


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
