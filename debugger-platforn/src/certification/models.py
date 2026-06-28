"""Pydantic data models for Certification."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CertificationTier(str, Enum):
    platinum = "platinum"
    gold = "gold"
    silver = "silver"
    not_certified = "not_certified"


class CategoryScore(BaseModel):
    category: str
    score: float = Field(ge=0, le=100)
    weight: float
    breakdown: Dict[str, float] = {}
    notes: List[str] = []


class HardBlocker(BaseModel):
    blocker_type: str
    condition: str
    evidence: str = ""
    tier_blocked: CertificationTier


class TestingConditions(BaseModel):
    total_simulations: int = 0
    by_difficulty: Dict[str, int] = {}
    chaos_tested: bool = False
    persona_count: int = 0
    persona_diversity: float = 0.0


class ConfidenceMetrics(BaseModel):
    total_simulations: int = 0
    confidence_level: float = 0.0
    margin_of_error: float = 0.0
    sample_sufficient: bool = False


class CertificationReport(BaseModel):
    certification_id: str
    agent_name: str = ""
    agent_framework: str = ""
    tier: CertificationTier
    overall_score: float = Field(ge=0, le=100)
    category_scores: List[CategoryScore] = []
    hard_blockers: List[HardBlocker] = []
    strengths: List[str] = []
    improvements: List[str] = []
    testing_conditions: TestingConditions = Field(default_factory=TestingConditions)
    confidence: ConfidenceMetrics = Field(default_factory=ConfidenceMetrics)
    radar_chart_data: Dict[str, float] = {}
    issued_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
