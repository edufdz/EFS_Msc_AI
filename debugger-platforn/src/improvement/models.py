"""
Pydantic models for the Improvement & Validation system (Phase E).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class FixStatus(str, Enum):
    PENDING = "pending"
    APPLIED = "applied"
    FAILED = "failed"
    SKIPPED = "skipped"
    ROLLED_BACK = "rolled_back"


class AppliedFix(BaseModel):
    fix_id: str
    cluster_id: str
    fix_type: str  # prompt_patch|code_change|config_change|validation_rule|tool_fix

    status: FixStatus
    applied_at: datetime
    applied_to: str  # File path or component name

    before: Optional[str] = None
    after: Optional[str] = None
    diff: Optional[str] = None

    smoke_test_passed: bool = False
    full_test_passed: bool = False

    failures_fixed: int = 0
    new_failures_introduced: int = 0

    can_rollback: bool = True
    rollback_instructions: Optional[str] = None


class ABTestRun(BaseModel):
    """A/B test comparing baseline vs fixed agent."""

    test_id: str
    run_at: datetime

    baseline_agent_id: str
    fixed_agent_id: str
    test_suite_used: str  # smoke|full

    baseline_results: Dict[str, Any]
    fixed_results: Dict[str, Any]

    improvement: Dict[str, Any]
    statistical_significance: Dict[str, Any]

    is_improvement: bool
    confidence_level: float  # 0-1
    recommendation: str  # deploy|rollback|need_more_data


class RegressionTest(BaseModel):
    """A test case to prevent future regressions."""

    test_id: str
    test_name: str

    cluster_id: str
    root_cause: str

    scenario: Dict[str, Any]
    persona: Dict[str, Any]
    expected_behavior: str

    catches_original_bug: bool = True
    passes_with_fix: bool = True

    priority: str = "medium"  # critical|high|medium|low
    created_from: str = ""  # Fix or cluster ID


class ImprovementReport(BaseModel):
    """Complete improvement validation report."""

    report_id: str
    created_at: datetime

    total_fixes_applied: int
    successful_fixes: int
    failed_fixes: int

    ab_test_runs: List[ABTestRun] = []

    baseline_pass_rate: float
    fixed_pass_rate: float
    pass_rate_improvement: float  # percentage points

    baseline_avg_cost: float = 0.0
    fixed_avg_cost: float = 0.0
    cost_delta: float = 0.0

    improvement_significant: bool = False
    confidence_interval: Dict[str, Any] = Field(default_factory=dict)

    new_failures: List[str] = []
    regression_count: int = 0

    ready_to_deploy: bool = False
    deployment_risk: str = "medium"  # low|medium|high
    rollback_plan: str = ""


class DeploymentPackage(BaseModel):
    """Complete package ready for deployment."""

    package_id: str
    created_at: datetime
    version: str

    fixed_agent_files: List[str] = []
    applied_fixes: List[Dict[str, Any]] = []
    regression_tests: List[Dict[str, Any]] = []

    all_tests_passed: bool = False
    improvement_validated: bool = False

    changelog: str = ""
    deployment_instructions: str = ""
    rollback_instructions: str = ""

    expected_improvement: float = 0.0
    expected_risk: str = "unknown"
