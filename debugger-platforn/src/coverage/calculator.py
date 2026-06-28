"""
Coverage calculator: auto-derives coverage goals and sandbox config
from an Agent Map.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from itertools import combinations
from typing import Dict, List

from .models import (
    CoverageGoals,
    EdgeCaseCoverageGoals,
    SandboxConfig,
    StressorCoverageGoals,
    TestConfiguration,
    ToolCoverageGoals,
    ToolSandboxConfig,
)

# Risk → min invocations mapping
_RISK_MIN_CALLS: Dict[str, int] = {
    "critical": 25,
    "high": 15,
    "medium": 10,
    "low": 5,
}

# Risk → edge-case multiplier (higher risk tools get more edge-case coverage)
_RISK_EDGE_MULTIPLIER: Dict[str, float] = {
    "critical": 2.0,
    "high": 1.5,
    "medium": 1.0,
    "low": 0.8,
}


def calculate_coverage_goals(agent_map: Dict) -> CoverageGoals:
    """Auto-calculate coverage goals based on agent map tool inventory and risk levels."""
    tools = agent_map.get("components", {}).get("tools", [])
    risk_flags = agent_map.get("risk_flags", {})

    # --- Tool coverage ---
    min_invocations: Dict[str, int] = {}
    seen_names: set = set()
    risk_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}

    for tool in tools:
        name = tool["name"]
        if name in seen_names:
            continue
        seen_names.add(name)

        risk = tool.get("risk_level", "medium")
        min_invocations[name] = _RISK_MIN_CALLS.get(risk, 10)
        risk_counts[risk] = risk_counts.get(risk, 0) + 1

    # Build interesting tool-combination pairs from tools that share dependencies
    # or are both high/critical risk
    high_risk_tools = [
        t["name"] for t in tools
        if t.get("risk_level") in ("critical", "high") and t["name"] in seen_names
    ]
    tool_combos: List[List[str]] = []
    unique_high = list(dict.fromkeys(high_risk_tools))  # dedupe preserving order
    for pair in combinations(unique_high[:10], 2):  # cap at 10 to avoid explosion
        tool_combos.append(list(pair))

    tool_coverage = ToolCoverageGoals(
        target_percentage=100,
        min_invocations_per_tool=min_invocations,
        tool_combinations=tool_combos,
    )

    # --- Edge-case coverage (scale with risk profile) ---
    max_risk_mult = max(
        (_RISK_EDGE_MULTIPLIER.get(r, 1.0) for r in risk_counts if risk_counts[r] > 0),
        default=1.0,
    )
    edge_case_coverage = EdgeCaseCoverageGoals(
        ambiguous_requests=int(40 * max_risk_mult),
        incomplete_information=int(35 * max_risk_mult),
        user_changes_mind=int(20 * max_risk_mult),
        contradictory_statements=int(15 * max_risk_mult),
    )

    # --- Stressor coverage (scale with tool count) ---
    tool_count = len(seen_names)
    scale = max(1.0, tool_count / 10)
    stressor_coverage = StressorCoverageGoals(
        timeout_scenarios=int(50 * scale),
        malformed_response_scenarios=int(25 * scale),
        data_conflict_scenarios=int(30 * scale),
    )

    return CoverageGoals(
        tool_coverage=tool_coverage,
        edge_case_coverage=edge_case_coverage,
        stressor_coverage=stressor_coverage,
    )


def generate_sandbox_config(agent_map: Dict) -> SandboxConfig:
    """Auto-generate sandbox config based on tool risk levels and properties."""
    tools = agent_map.get("components", {}).get("tools", [])
    success_criteria = agent_map.get("success_criteria", {})

    tool_configs: Dict[str, ToolSandboxConfig] = {}
    seen_names: set = set()

    for tool in tools:
        name = tool["name"]
        if name in seen_names:
            continue
        seen_names.add(name)

        risk = tool.get("risk_level", "medium")
        sandbox_safe = tool.get("sandbox_safe", True)
        read_only = tool.get("read_only", False)
        handles_sensitive = tool.get("handles_sensitive_data", False)

        if risk in ("critical", "high") or not sandbox_safe:
            config = ToolSandboxConfig(
                mode="mock",
                mock_strategy="schema_based",
                require_confirmation=(risk == "critical"),
                latency_simulation={"min_ms": 200, "max_ms": 800},
            )
        elif read_only and sandbox_safe:
            config = ToolSandboxConfig(
                mode="capture",
                mock_strategy=None,
                rate_limit=100,
            )
        else:
            config = ToolSandboxConfig(
                mode="mock" if handles_sensitive else "real",
                mock_strategy="schema_based" if handles_sensitive else None,
                rate_limit=50,
            )

        tool_configs[name] = config

    # Cost limits from agent's own success criteria or sensible defaults
    max_cost_per_convo = success_criteria.get("max_cost_per_conversation", 1.0)
    sandbox_config = SandboxConfig(
        mode="full_mock",
        tool_configs=tool_configs,
        cost_limits={
            "max_llm_cost_per_episode": min(max_cost_per_convo, 0.10),
            "max_total_cost_per_run": 50.00,
        },
        safety={
            "max_turns_per_episode": success_criteria.get("max_turns", 20),
            "timeout_per_tool_call_sec": 10,
            "pii_detection": bool(
                agent_map.get("risk_flags", {}).get("pii_handling", False)
                or any(t.get("handles_sensitive_data") for t in tools)
            ),
            "block_real_external_calls": True,
        },
    )

    return sandbox_config


def build_test_configuration(agent_map: Dict) -> TestConfiguration:
    """Build a complete TestConfiguration from an agent map."""
    return TestConfiguration(
        config_id=str(uuid.uuid4()),
        agent_id=agent_map.get("agent_id", "unknown"),
        coverage_goals=calculate_coverage_goals(agent_map),
        sandbox_config=generate_sandbox_config(agent_map),
        created_at=datetime.now(timezone.utc),
    )
