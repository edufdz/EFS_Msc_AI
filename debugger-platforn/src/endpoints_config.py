"""
Resolve agent API endpoints from agent_endpoints.json.

agent_map.json is produced by analysis and does not contain api_endpoint.
This module loads agent_endpoints.json (same dir as agent_map or cwd) and
resolves the URL by agent_id or "default", then can inject it into agent_map
so connectors work without change.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


def _find_endpoints_file(agent_map_file_path: str) -> Optional[Path]:
    """Look for agent_endpoints.json next to agent_map file, then in cwd."""
    p = Path(agent_map_file_path).resolve()
    # Same directory as agent_map
    candidate = p.parent / "agent_endpoints.json"
    if candidate.is_file():
        return candidate
    # Current working directory
    cwd_file = Path.cwd() / "agent_endpoints.json"
    if cwd_file.is_file():
        return cwd_file
    return None


def load_endpoints(endpoints_path: Path) -> Dict[str, Any]:
    """Load agent_endpoints.json. Returns dict with 'default' and optional 'by_agent_id'."""
    with open(endpoints_path) as f:
        data = json.load(f)
    return data


def resolve_api_endpoint(
    agent_map: Dict[str, Any],
    agent_map_file_path: str,
) -> Optional[str]:
    """
    Get API endpoint for this agent_map.
    - If agent_map already has api_endpoint (top-level or metadata), use it.
    - Else load agent_endpoints.json and look up by agent_id, then "default".
    """
    existing = (
        agent_map.get("api_endpoint")
        or agent_map.get("metadata", {}).get("api_endpoint")
    )
    if existing:
        return existing

    endpoints_path = _find_endpoints_file(agent_map_file_path)
    if not endpoints_path:
        return None

    data = load_endpoints(endpoints_path)
    agent_id = agent_map.get("agent_id")
    by_id = data.get("by_agent_id") or {}
    if agent_id and agent_id in by_id:
        return by_id[agent_id]
    return data.get("default")


def apply_endpoints_to_agent_map(
    agent_map: Dict[str, Any],
    agent_map_file_path: str,
) -> None:
    """
    If agent_map has no api_endpoint, resolve from agent_endpoints.json
    and set agent_map["api_endpoint"] in place.
    """
    if agent_map.get("api_endpoint") or agent_map.get("metadata", {}).get("api_endpoint"):
        return
    endpoint = resolve_api_endpoint(agent_map, agent_map_file_path)
    if endpoint is not None:
        agent_map["api_endpoint"] = endpoint
