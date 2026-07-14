"""
Mock tool layer for the Sandbox Bridge.

Research purpose: production agents call live tools (databases, CRMs,
escalation queues). To exercise the agent safely, the sandbox routes every
tool call through this registry, which returns canned responses and applies
*deterministic* failure injection (seeded ``random.Random``), so a failing
test can always be replayed bit-for-bit and injected faults are cleanly
separable from genuine agent faults.
"""

from __future__ import annotations

import random
import time
from typing import Any, Dict, List, Optional, Tuple

from src.sandbox.models import MockToolConfig


class _ArgumentEcho:
    """Sentinel canned response that echoes call arguments.

    Used by ``MockToolRegistry.from_agent_map`` defaults: the concrete
    payload depends on the arguments of each individual call, so it is
    materialised inside ``call()`` as
    ``{"status": "ok", "tool": <name>, "data": {...arguments...}}``.
    """

    def __init__(self, tool_name: str):
        self.tool_name = tool_name

    def materialise(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "ok", "tool": self.tool_name, "data": dict(arguments or {})}


class MockToolRegistry:
    """Registry of mocked tools with seeded failure injection.

    All stochastic decisions (error / empty injection) come from a single
    ``random.Random(seed)`` instance, so two registries built with the same
    seed and driven with the same call sequence inject the exact same
    failures — the determinism guarantee the research pipeline relies on.
    """

    def __init__(self, tools: Optional[List[MockToolConfig]] = None, seed: int = 42):
        self._tools: Dict[str, MockToolConfig] = {}
        self._call_counts: Dict[str, int] = {}
        self.seed = seed
        self._rng = random.Random(seed)
        for cfg in tools or []:
            self.register(cfg)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, config: MockToolConfig) -> None:
        """Register (or replace) a mock tool config."""
        self._tools[config.name] = config
        self._call_counts.setdefault(config.name, 0)

    @property
    def tool_names(self) -> List[str]:
        """Registered tool names, in registration order."""
        return list(self._tools.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def get(self, name: str) -> Optional[MockToolConfig]:
        return self._tools.get(name)

    # ------------------------------------------------------------------
    # Invocation with failure injection
    # ------------------------------------------------------------------

    def call(self, name: str, arguments: Dict[str, Any]) -> Tuple[Any, Optional[str]]:
        """Invoke a mock tool.

        Returns ``(result, injected_failure)`` where ``injected_failure`` is
        ``None`` on a clean call, ``"error"`` when the error payload was
        injected, or ``"empty_response"`` when an empty result was injected.

        Unknown tools return a permissive stub (the sandbox must never crash
        the agent under test just because a tool was not pre-registered);
        the result is flagged with ``"unregistered": True``.
        """
        arguments = arguments or {}
        cfg = self._tools.get(name)
        if cfg is None:
            return (
                {"status": "ok", "tool": name, "unregistered": True, "data": arguments},
                None,
            )

        if cfg.latency_ms > 0:
            time.sleep(cfg.latency_ms / 1000.0)

        # Error injection first (an erroring backend never returns data).
        if cfg.error_rate > 0 and self._rng.random() < cfg.error_rate:
            return cfg.error_payload, "error"

        if cfg.empty_rate > 0 and self._rng.random() < cfg.empty_rate:
            return {}, "empty_response"

        n = self._call_counts.get(name, 0)
        self._call_counts[name] = n + 1

        if cfg.response_variants:
            # Deterministic round-robin over variants (no RNG consumed, so
            # variants never perturb the failure-injection stream).
            result = cfg.response_variants[n % len(cfg.response_variants)]
        else:
            result = cfg.response

        if isinstance(result, _ArgumentEcho):
            result = result.materialise(arguments)
        return result, None

    # ------------------------------------------------------------------
    # Construction from an Agent Map (Phase A output)
    # ------------------------------------------------------------------

    @classmethod
    def from_agent_map(
        cls,
        agent_map: Dict[str, Any],
        seed: int = 42,
        error_rate: float = 0.0,
        empty_rate: float = 0.0,
        latency_ms: int = 0,
    ) -> "MockToolRegistry":
        """Build a registry with a default mock for every tool in the map.

        Reads ``agent_map["components"]["tools"]`` (the Phase A schema) and
        registers one mock per uniquely named tool. The canned response
        echoes the call arguments so downstream oracles can verify argument
        propagation. Optional ``error_rate`` / ``empty_rate`` / ``latency_ms``
        are applied uniformly to every generated mock (the CLI's
        ``--error-rate`` flag lands here).

        Tools with a null/missing name are skipped — real agent maps contain
        such entries (see the mutation-generator null-field fix in history).
        """
        registry = cls(seed=seed)
        tools = (agent_map.get("components") or {}).get("tools") or []
        seen: set[str] = set()
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            name = tool.get("name")
            if not name or not isinstance(name, str) or name in seen:
                continue
            seen.add(name)
            registry.register(
                MockToolConfig(
                    name=name,
                    response=_ArgumentEcho(name),
                    error_rate=error_rate,
                    empty_rate=empty_rate,
                    latency_ms=latency_ms,
                )
            )
        return registry
