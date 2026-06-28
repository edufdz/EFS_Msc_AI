"""
Pydantic models for the Test Execution Engine (Phase C).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TestStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    TIMEOUT = "timeout"


class ConversationTurn(BaseModel):
    turn_number: int
    role: str  # "user" | "agent"
    message: str
    tool_calls: List[Dict[str, Any]] = []
    timestamp: datetime
    duration_ms: float = 0.0


class ChaosEvent(BaseModel):
    turn_number: int
    chaos_type: str  # timeout|malformed_response|data_conflict
    description: str


class TestResult(BaseModel):
    test_id: str
    test_number: int
    status: TestStatus

    # Test case info
    scenario_title: str
    persona_name: str
    difficulty: str
    coverage_goal: str = ""

    # Execution info
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_sec: float = 0.0

    # Conversation
    turns: List[ConversationTurn] = []
    total_turns: int = 0

    # Outcome
    success: bool = False
    failure_reason: Optional[str] = None
    outcome: Optional[str] = None  # "appointment_booked", "escalated_to_human", etc.
    tools_called_sequence: List[str] = []  # ordered list of all tools called
    tool_results: List[Dict[str, Any]] = []  # tool name + result data for each call

    # Chaos
    chaos_events: List[ChaosEvent] = []

    # Metrics
    llm_calls: int = 0
    tool_calls_count: int = 0
    tokens_used: int = 0
    cost_usd: float = 0.0

    # Trace
    trace_file: Optional[str] = None


class TestRunReport(BaseModel):
    run_id: str
    test_suite_id: str

    total_tests: int
    passed: int
    failed: int
    errors: int
    timeouts: int
    pass_rate: float

    total_duration_sec: float
    avg_duration_sec: float
    total_cost_usd: float

    tool_coverage: Dict[str, int] = Field(default_factory=dict)
    tools_not_covered: List[str] = Field(default_factory=list)
    coverage_pct: float = 0.0

    by_difficulty: Dict[str, Dict[str, int]] = Field(default_factory=dict)
    by_coverage_goal: Dict[str, Dict[str, int]] = Field(default_factory=dict)

    started_at: datetime
    completed_at: datetime
