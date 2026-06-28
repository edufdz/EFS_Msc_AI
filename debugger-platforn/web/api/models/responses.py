"""Pydantic response models."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class SessionResponse(BaseModel):
    session_id: str
    output_dir: str
    created_at: str
    phases_completed: list[str] = []
    phase_status: Optional[dict[str, str]] = None
    phase_results: Optional[dict[str, Any]] = None


class SessionListResponse(BaseModel):
    sessions: list[SessionResponse]


class PhaseStatusResponse(BaseModel):
    session_id: str
    phase: str
    status: str  # "idle" | "running" | "completed" | "error"
    progress_pct: int = 0
    message: str = ""
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class FileEntry(BaseModel):
    name: str
    type: str  # "file" | "directory"
    path: str
    size: Optional[int] = None


class FileBrowseResponse(BaseModel):
    current_path: str
    parent_path: Optional[str] = None
    entries: list[FileEntry]


class ArtifactResponse(BaseModel):
    artifact_type: str
    session_id: str
    data: Any = None
    file_path: Optional[str] = None
    error: Optional[str] = None
