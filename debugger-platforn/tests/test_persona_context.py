"""
Verify persona context flows into the simulator (raw and analyzed).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.execution.conversation_simulator import ConversationSimulator


class _MockConnector:
    async def send_message(self, message: str, context=None):
        return {"success": True, "response": "OK", "tool_calls": [], "error": None}

    async def reset(self):
        pass


def _minimal_test_case(
    persona_context: str | None = None,
    persona_context_analyzed: dict | None = None,
) -> dict:
    tc = {
        "test_id": "t1",
        "test_number": 1,
        "scenario": {"title": "Test", "user_goal": "get help", "estimated_turns": 3},
        "persona": {"name": "User", "traits": {"patience": 5}, "style": {"tone": "neutral"}},
        "execution_config": {"max_turns": 5},
    }
    if persona_context is not None:
        tc["persona_context"] = persona_context
    if persona_context_analyzed is not None:
        tc["persona_context_analyzed"] = persona_context_analyzed
    return tc


def test_simulator_gets_raw_context():
    """Simulator receives persona_context from test_case."""
    raw = "VIN: ABC123, Model: Tesla"
    tc = _minimal_test_case(persona_context=raw)

    sim = ConversationSimulator(
        test_case=tc,
        agent_connector=_MockConnector(),
        event_queue=asyncio.Queue(),
        use_ai_personas=False,
        language="English",
    )

    assert sim.persona_context_user == raw
    assert sim.persona_context_analyzed is None


def test_simulator_gets_analyzed_context():
    """Simulator receives persona_context_analyzed from test_case."""
    analyzed = {
        "analysis": "Vehicle identifiers and details.",
        "when_agent_asks": "My VIN is WBA8E9C50JK285901 and license plate TX-BMW-3301.",
    }
    tc = _minimal_test_case(persona_context_analyzed=analyzed)

    sim = ConversationSimulator(
        test_case=tc,
        agent_connector=_MockConnector(),
        event_queue=asyncio.Queue(),
        use_ai_personas=False,
        language="English",
    )

    assert sim.persona_context_analyzed == analyzed
    assert sim.persona_context_analyzed.get("when_agent_asks") == analyzed["when_agent_asks"]


def test_simulator_gets_both_raw_and_analyzed():
    """Simulator can have both raw and analyzed; analyzed is used in prompts."""
    raw = "vin: X1, plate: Y2"
    analyzed = {"analysis": "IDs.", "when_agent_asks": "VIN X1, plate Y2."}
    tc = _minimal_test_case(persona_context=raw, persona_context_analyzed=analyzed)

    sim = ConversationSimulator(
        test_case=tc,
        agent_connector=_MockConnector(),
        event_queue=asyncio.Queue(),
        use_ai_personas=True,
        language="English",
    )

    assert sim.persona_context_user == raw
    assert sim.persona_context_analyzed == analyzed

    # First-message prompt should use analyzed form when present
    prompt = sim._build_first_message_prompt()
    assert "IDs." in prompt
    assert "VIN X1, plate Y2." in prompt
