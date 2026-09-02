"""Health of the sibling services the demo depends on.

The browser cannot poll the live agent (:3098) or the anonymisation backend
(:8100) directly -- both are different origins, so the checks would be blocked
by CORS. Probing them server-side keeps the UI free of cross-origin plumbing
and gives one place to describe how each service is started.
"""

from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter

router = APIRouter(prefix="/api/services", tags=["services"])

# Overridable so a demo on non-default ports still reports correctly.
AGENT_URL = os.environ.get("AGENT_URL", "http://localhost:3098")
ANONYMISER_API = os.environ.get("ANONYMISER_API_URL", "http://localhost:8100")
ANONYMISER_UI = os.environ.get("ANONYMISER_UI_URL", "http://localhost:5174")

_TIMEOUT = 2.0


async def _probe(url: str) -> bool:
    """True if *url* answers with any HTTP status inside the timeout.

    Reachability is the question, not correctness: a 404 still proves the
    process is listening.
    """
    try:
        import aiohttp

        timeout = aiohttp.ClientTimeout(total=_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                return resp.status < 500
    except Exception:
        return False


@router.get("/status")
async def services_status() -> dict:
    """Report which sibling services are reachable."""
    agent_ok, anon_ok = await asyncio.gather(
        _probe(f"{AGENT_URL}/db"),
        _probe(f"{ANONYMISER_API}/api/health"),
    )

    return {
        "agent": {
            "name": "Live agent (sandbox)",
            "url": AGENT_URL,
            "online": agent_ok,
            "start_hint": "cd tech_repair-live-agent && bun server.ts",
        },
        "anonymiser": {
            "name": "Anonymisation system",
            "url": ANONYMISER_UI,
            "api_url": ANONYMISER_API,
            "online": anon_ok,
            "start_hint": "cd anonymization/backend && ./venv/bin/python -m uvicorn app:app --port 8100",
        },
    }
