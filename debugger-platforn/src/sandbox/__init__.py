"""
Sandbox Bridge subsystem.

Research purpose (MSc Phases A-D pipeline): expose a *test* endpoint that
wraps a real production agent behind a mock tool layer with deterministic
failure injection, so that synthetic tests (Phase C) can exercise the real
agent logic without touching live customers or production tools. Every
conversation through the bridge is captured as a `SandboxTrace` in a shared
schema, and a replay harness (`src.sandbox.replay`) measures the behavioural
fidelity of the sandbox against recorded production conversations.

Public API:
    - models:      MockToolConfig, SandboxBridgeConfig, SandboxTrace
    - mock_tools:  MockToolRegistry
    - bridge:      create_bridge_app
    - replay:      replay_conversation, fidelity_score, replay_batch
"""

from __future__ import annotations

from src.sandbox.models import MockToolConfig, SandboxBridgeConfig, SandboxTrace
from src.sandbox.mock_tools import MockToolRegistry
from src.sandbox.bridge import create_bridge_app
from src.sandbox.replay import (
    ReplayResult,
    fidelity_score,
    replay_batch,
    replay_conversation,
)

__all__ = [
    "MockToolConfig",
    "SandboxBridgeConfig",
    "SandboxTrace",
    "MockToolRegistry",
    "create_bridge_app",
    "ReplayResult",
    "replay_conversation",
    "fidelity_score",
    "replay_batch",
]
