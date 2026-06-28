"""
Pydantic models for the Diagnosis & Analysis system (Phase D).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class RootCauseType(str, Enum):
    PROMPT_ISSUE = "prompt_issue"
    TOOL_SELECTION_ERROR = "tool_selection_error"
    TOOL_SCHEMA_MISMATCH = "tool_schema_mismatch"
    MISSING_GUARDRAIL = "missing_guardrail"
    RETRY_LOGIC_BUG = "retry_logic_bug"
    HALLUCINATION = "hallucination"
    TIMEOUT_HANDLING = "timeout_handling"
    ERROR_HANDLING = "error_handling"
    STATE_MANAGEMENT = "state_management"
    VALIDATION_MISSING = "validation_missing"
    EDGE_CASE_UNHANDLED = "edge_case_unhandled"
    SERVICE_UNAVAILABLE = "service_unavailable"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FailureExample(BaseModel):
    test_id: str
    test_number: int
    scenario: str
    persona: str
    failure_reason: str
    trace_file: str = ""
    difficulty: str = "medium"
    coverage_goal: str = ""
    tools_called: List[str] = []
    tools_expected: List[str] = []
    turn_count: int = 0
    duration_sec: float = 0.0
    chaos_events: List[Dict[str, Any]] = []


class FailureCluster(BaseModel):
    cluster_id: str
    cluster_name: str
    failure_count: int
    failure_examples: List[FailureExample]

    root_cause_type: RootCauseType
    root_cause_description: str
    common_pattern: str
    key_indicators: List[str] = []

    severity: Severity
    affected_scenarios: List[str] = []
    affected_tools: List[str] = []

    minimal_reproduction: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=datetime.now)


class FixProposal(BaseModel):
    fix_id: str
    cluster_id: str
    fix_type: str  # prompt_patch|code_change|validation_rule|config_change
    description: str
    changes: Dict[str, Any] = Field(default_factory=dict)
    estimated_fix_rate: float = 0.0
    estimated_effort: str = "medium"  # low|medium|high
    risk_level: str = "low"  # low|medium|high
    created_at: datetime = Field(default_factory=datetime.now)


class DiagnosisReport(BaseModel):
    report_id: str
    run_id: str
    total_failures: int
    clusters_found: int
    clusters: List[FailureCluster]
    fix_proposals: List[FixProposal]
    priority_ranking: List[str]  # cluster IDs ranked by impact
    summary: Dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=datetime.now)
