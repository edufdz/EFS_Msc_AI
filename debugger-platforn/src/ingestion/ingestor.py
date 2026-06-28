"""
Code Ingestion Engine
Handles local directory traversal, language detection, file filtering,
and entry point identification for agent codebases.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path


# Patterns likely to contain agent logic
INCLUDE_PATTERNS = [
    "**/agent*.py", "**/agents/**/*.py",
    "**/tool*.py", "**/tools/**/*.py",
    "**/chain*.py", "**/chains/**/*.py",
    "**/workflow*.py", "**/workflows/**/*.py",
    "**/graph*.py", "**/graphs/**/*.py",
    "**/*llm*.py", "**/*openai*.py", "**/*anthropic*.py",
    "**/prompt*.py", "**/prompts/**/*.py",
    "**/crew*.py",
    "**/main.py", "**/app.py", "**/run.py", "**/cli.py",
]

# Directories / patterns to skip
EXCLUDE_DIRS = {
    "__pycache__", ".git", ".hg", ".svn",
    "node_modules", "venv", ".venv", "env", ".env",
    "dist", "build", ".eggs", "*.egg-info",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
}

EXCLUDE_FILE_PATTERNS = [
    "test_*.py", "*_test.py", "conftest.py",
    "setup.py", "setup.cfg",
]

# Entry-point file names (in priority order)
ENTRY_POINT_NAMES = [
    "main.py", "app.py", "run.py", "cli.py",
    "agent.py", "server.py", "__main__.py",
]


@dataclass
class FileInfo:
    path: str
    relative_path: str
    language: str
    size_bytes: int
    is_entry_point: bool = False
    priority: int = 0  # higher = more likely to be agent-relevant


@dataclass
class IngestionResult:
    root_path: str
    project_type: str  # "python", "javascript", etc.
    files: list[FileInfo] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)
    total_files_scanned: int = 0
    prompt_files: list[str] = field(default_factory=list)


def _should_exclude_dir(dirname: str) -> bool:
    return dirname in EXCLUDE_DIRS or dirname.endswith(".egg-info")


def _should_exclude_file(filename: str) -> bool:
    return any(fnmatch(filename, pat) for pat in EXCLUDE_FILE_PATTERNS)


def _detect_language(filepath: str) -> str | None:
    ext = os.path.splitext(filepath)[1].lower()
    lang_map = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".jsx": "javascript",
        ".tsx": "typescript",
        ".go": "go",
        ".rs": "rust",
    }
    return lang_map.get(ext)


def _matches_include_pattern(rel_path: str) -> bool:
    """Check if file matches any agent-relevant include pattern."""
    for pattern in INCLUDE_PATTERNS:
        # Simple glob matching – normalize separators
        if fnmatch(rel_path, pattern):
            return True
    return False


def _compute_priority(rel_path: str, filename: str) -> int:
    """Assign a priority score – higher means more likely agent-related."""
    score = 0
    name_lower = filename.lower()

    # Files with "agent" in the name are top priority
    if "agent" in name_lower:
        score += 10
    if "tool" in name_lower:
        score += 8
    if "chain" in name_lower or "workflow" in name_lower or "graph" in name_lower:
        score += 7
    if "prompt" in name_lower:
        score += 6
    if "llm" in name_lower or "openai" in name_lower or "anthropic" in name_lower:
        score += 5
    if name_lower in ENTRY_POINT_NAMES:
        score += 4

    # Penalise deeply nested utility files
    depth = rel_path.count(os.sep)
    if depth > 4:
        score -= 2

    return score


def detect_project_type(root_path: str) -> str:
    """Detect dominant language / project type."""
    counts: dict[str, int] = {}
    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if not _should_exclude_dir(d)]
        for f in filenames:
            lang = _detect_language(f)
            if lang:
                counts[lang] = counts.get(lang, 0) + 1

    if not counts:
        return "unknown"
    return max(counts, key=counts.get)


def find_prompt_files(root_path: str) -> list[str]:
    """Find files that likely contain prompt templates."""
    prompt_files = []
    prompt_extensions = {".txt", ".md", ".prompt", ".jinja", ".jinja2"}
    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if not _should_exclude_dir(d)]
        for f in filenames:
            fpath = os.path.join(dirpath, f)
            name_lower = f.lower()
            ext = os.path.splitext(f)[1].lower()
            if ext in prompt_extensions and "prompt" in name_lower:
                prompt_files.append(fpath)
    return prompt_files


def ingest_directory(root_path: str, language_filter: str | None = None) -> IngestionResult:
    """
    Scan a local directory and collect all relevant source files.

    Args:
        root_path: Absolute path to the codebase root.
        language_filter: If set, only include files of this language (e.g. "python").

    Returns:
        IngestionResult with categorised file list.
    """
    root_path = os.path.abspath(root_path)
    if not os.path.isdir(root_path):
        raise FileNotFoundError(f"Directory not found: {root_path}")

    project_type = detect_project_type(root_path)
    if language_filter:
        project_type = language_filter

    files: list[FileInfo] = []
    entry_points: list[str] = []
    total_scanned = 0

    for dirpath, dirnames, filenames in os.walk(root_path):
        # Prune excluded directories in-place
        dirnames[:] = sorted(d for d in dirnames if not _should_exclude_dir(d))

        for filename in sorted(filenames):
            filepath = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(filepath, root_path)
            lang = _detect_language(filename)

            if lang is None:
                continue
            if language_filter and lang != language_filter:
                continue
            if _should_exclude_file(filename):
                continue

            total_scanned += 1
            priority = _compute_priority(rel_path, filename)
            is_entry = filename in ENTRY_POINT_NAMES

            fi = FileInfo(
                path=filepath,
                relative_path=rel_path,
                language=lang,
                size_bytes=os.path.getsize(filepath),
                is_entry_point=is_entry,
                priority=priority,
            )
            files.append(fi)
            if is_entry:
                entry_points.append(filepath)

    # Sort by priority descending
    files.sort(key=lambda f: f.priority, reverse=True)
    prompt_files = find_prompt_files(root_path)

    return IngestionResult(
        root_path=root_path,
        project_type=project_type,
        files=files,
        entry_points=entry_points,
        total_files_scanned=total_scanned,
        prompt_files=prompt_files,
    )
