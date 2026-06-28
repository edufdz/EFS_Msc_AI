"""Filesystem routes — native directory picker + path resolution."""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from web.api.models.requests import FileBrowseRequest
from web.api.models.responses import FileBrowseResponse, FileEntry

router = APIRouter(prefix="/api/fs", tags=["filesystem"])


# ── Resolve directory (used with browser showDirectoryPicker) ──────────────


class ResolveDirectoryRequest(BaseModel):
    name: str
    files: list[str] = []


@router.post("/resolve-directory")
async def resolve_directory(req: ResolveDirectoryRequest):
    """Given a directory name + sample filenames, find its absolute path on disk.

    This is used when the browser's showDirectoryPicker() API returns a handle
    (which has the name but not the absolute path). We use Spotlight (mdfind)
    on macOS, or search common locations as fallback.
    """
    path = _resolve_dir(req.name, req.files)
    return {"path": path}


def _resolve_dir(name: str, sample_files: list[str]) -> str | None:
    """Find the absolute path of a directory by name + known contents."""
    # 1. Quick check: common locations
    home = Path.home()
    common_roots = [
        home / "Desktop",
        home / "Documents",
        home / "Downloads",
        home / "Projects",
        home / "Developer",
        home / "repos",
        home / "code",
        home / "src",
        home,
        Path("/tmp"),
    ]
    for root in common_roots:
        candidate = root / name
        if candidate.is_dir() and _verify_dir(candidate, sample_files):
            return str(candidate)

    # 2. Walk one level deeper in common roots
    for root in common_roots[:4]:  # Desktop, Documents, Downloads, Projects
        if not root.exists():
            continue
        try:
            for child in root.iterdir():
                if child.is_dir():
                    candidate = child / name
                    if candidate.is_dir() and _verify_dir(candidate, sample_files):
                        return str(candidate)
        except PermissionError:
            continue

    # 3. macOS: use Spotlight (mdfind) — instant indexed search
    if platform.system() == "Darwin":
        found = _mdfind_directory(name, sample_files)
        if found:
            return found

    return None


def _verify_dir(path: Path, sample_files: list[str]) -> bool:
    """Verify a candidate directory contains the expected sample files."""
    if not sample_files:
        return True
    # Check at least half the sample files exist
    matches = sum(1 for f in sample_files[:6] if (path / f).exists())
    return matches >= min(len(sample_files[:6]) // 2 + 1, len(sample_files[:6]))


def _mdfind_directory(name: str, sample_files: list[str]) -> str | None:
    """Use macOS Spotlight to find a directory by name."""
    try:
        result = subprocess.run(
            ["mdfind", f"kMDItemFSName = '{name}' && kMDItemContentTypeTree = 'public.folder'"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None
        for line in result.stdout.strip().split("\n"):
            candidate = Path(line.strip())
            if candidate.is_dir() and _verify_dir(candidate, sample_files):
                return str(candidate)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


# ── Browse directory (listing) ─────────────────────────────────────────────


@router.post("/browse", response_model=FileBrowseResponse)
async def browse_directory(req: FileBrowseRequest):
    target = Path(os.path.expanduser(req.path)).resolve()

    if not target.exists():
        return FileBrowseResponse(
            current_path=str(target),
            parent_path=str(target.parent),
            entries=[],
        )

    entries: list[FileEntry] = []
    try:
        for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if not req.show_hidden and item.name.startswith("."):
                continue
            if item.name in ("node_modules", "__pycache__", ".git", ".venv", "venv"):
                entries.append(FileEntry(name=item.name, type="directory", path=str(item)))
                continue
            try:
                entry_type = "directory" if item.is_dir() else "file"
                size = item.stat().st_size if item.is_file() else None
                entries.append(FileEntry(name=item.name, type=entry_type, path=str(item), size=size))
            except PermissionError:
                continue
    except PermissionError:
        pass

    return FileBrowseResponse(
        current_path=str(target),
        parent_path=str(target.parent) if target.parent != target else None,
        entries=entries,
    )
