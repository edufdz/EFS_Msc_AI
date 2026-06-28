"""Pydantic request models for each phase."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class PhaseARequest(BaseModel):
    session_id: str
    repo_path: str
    skip_ai: bool = False
    language: Optional[str] = None
    prompt_encoding: str = "utf-8"


class PhaseBRequest(BaseModel):
    session_id: str
    skip_ai: bool = False
    count: int = Field(default=150, ge=10, le=5000)
    persona_count: int = Field(default=8, ge=0, le=20)
    scenario_count: int = Field(default=10, ge=0, le=50)
    variants: int = Field(default=3, ge=0, le=10)
    seed: Optional[int] = None
    language: Optional[str] = None
    use_tlahuac: bool = False
    tlahuac_dir: Optional[str] = None
    include_templates: bool = False
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    llm_base_url: Optional[str] = None


class PhaseCRequest(BaseModel):
    session_id: str
    mock: bool = False
    workers: int = Field(default=10, ge=1, le=50)
    count: int = Field(default=10, ge=0)
    ai_personas: bool = True
    traces: bool = True
    fail_rate: float = Field(default=0.05, ge=0.0, le=1.0)
    seed: Optional[int] = None
    language: Optional[str] = None
    persona_context: Optional[str] = None
    validate: bool = True  # Run AI-powered failure triage before Phase D
    agent_endpoint: Optional[str] = None  # e.g. http://localhost:3099
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    llm_base_url: Optional[str] = None


class PhaseDRequest(BaseModel):
    session_id: str
    skip_ai: bool = False
    use_embeddings: bool = False
    max_retries: int = Field(default=3, ge=1, le=10)
    backoff_base: float = Field(default=2.0, ge=1.0, le=10.0)
    backoff_max: float = Field(default=60.0, ge=10.0, le=300.0)


class CertificationRequest(BaseModel):
    session_id: str


class FileBrowseRequest(BaseModel):
    path: str = "~"
    show_hidden: bool = False
