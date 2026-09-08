"""
Trace parser — converts raw Langfuse trace data into structured objects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TraceToolCall:
    tool_name: str
    arguments: dict
    result: dict | None
    success: bool
    duration_ms: float
    timestamp: datetime


@dataclass
class TraceConversation:
    trace_id: str
    tool_calls: list[TraceToolCall]
    tool_sequence: list[str]
    total_turns: int
    total_duration_ms: float
    outcome: str  # "success" | "failure" | "unknown"
    user_messages: list[str] = field(default_factory=list)
    agent_messages: list[str] = field(default_factory=list)


@dataclass
class TraceAnalysisResult:
    conversations: list[TraceConversation]
    tool_frequency: dict[str, int]
    tool_sequences: list[tuple[list[str], int]]
    tools_not_in_static: list[str]
    tools_not_in_traces: list[str]
    common_first_tools: list[str]
    common_last_tools: list[str]
    avg_tools_per_conversation: float
    failure_patterns: list[dict]


def _parse_timestamp(ts_str: str) -> datetime:
    """Best-effort timestamp parse."""
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(ts_str, fmt)
        except (ValueError, TypeError):
            continue
    return datetime.min


def _extract_tool_calls_from_observations(observations: list[dict]) -> list[TraceToolCall]:
    """Extract tool calls from Langfuse observations (spans/generations)."""
    calls: list[TraceToolCall] = []

    for obs in observations:
        obs_type = obs.get("type", "")
        obs_name = obs.get("name", "") or ""
        obs_input = obs.get("input") or {}
        obs_output = obs.get("output") or {}
        metadata = obs.get("metadata") or {}

        # Detect tool calls by type or naming conventions
        is_tool = (
            obs_type in ("tool", "function")
            or "tool" in obs_name.lower()
            or metadata.get("type") == "tool_call"
        )

        # Also detect from generation inputs that have tool_calls
        tool_calls_in_output = []
        if isinstance(obs_output, dict):
            tool_calls_in_output = obs_output.get("tool_calls", [])
        if isinstance(obs_output, list):
            tool_calls_in_output = [
                tc for tc in obs_output
                if isinstance(tc, dict) and tc.get("type") == "tool_call"
            ]

        if is_tool and obs_name:
            start = _parse_timestamp(obs.get("start_time", ""))
            end = _parse_timestamp(obs.get("end_time", ""))
            duration = (end - start).total_seconds() * 1000 if end > start else 0

            status = obs.get("status_message") or obs.get("level") or ""
            success = "error" not in str(status).lower()

            arguments = obs_input if isinstance(obs_input, dict) else {}
            result = obs_output if isinstance(obs_output, dict) else None

            calls.append(TraceToolCall(
                tool_name=obs_name,
                arguments=arguments,
                result=result,
                success=success,
                duration_ms=duration,
                timestamp=start,
            ))

        # Handle tool calls embedded in generation outputs
        for tc in tool_calls_in_output:
            fn = tc.get("function", {})
            calls.append(TraceToolCall(
                tool_name=fn.get("name", tc.get("name", "unknown")),
                arguments=fn.get("arguments", {}),
                result=None,
                success=True,
                duration_ms=0,
                timestamp=_parse_timestamp(obs.get("start_time", "")),
            ))

    calls.sort(key=lambda c: c.timestamp)
    return calls


def _extract_messages(observations: list[dict]) -> tuple[list[str], list[str]]:
    """Extract user and agent messages from generation observations."""
    user_msgs: list[str] = []
    agent_msgs: list[str] = []

    for obs in observations:
        obs_input = obs.get("input") or {}
        obs_output = obs.get("output") or {}

        # Extract from chat-style input messages
        if isinstance(obs_input, dict):
            messages = obs_input.get("messages", [])
            for msg in messages:
                if isinstance(msg, dict):
                    role = msg.get("role", "")
                    content = msg.get("content", "")
                    if role == "user" and content:
                        user_msgs.append(str(content)[:500])
                    elif role == "assistant" and content:
                        agent_msgs.append(str(content)[:500])

        # Extract from output content
        if isinstance(obs_output, dict):
            content = obs_output.get("content", "")
            if content and isinstance(content, str):
                agent_msgs.append(content[:500])

    return user_msgs, agent_msgs


def _determine_outcome(observations: list[dict]) -> str:
    """Determine conversation outcome from observation statuses."""
    for obs in reversed(observations):
        status = str(obs.get("status_message", "") or obs.get("level", "") or "").lower()
        if "error" in status or "fail" in status:
            return "failure"
        if "success" in status or "ok" in status:
            return "success"
    return "unknown"


def parse_trace_detail(trace_detail: dict) -> TraceConversation | None:
    """Parse a single trace detail dict into a TraceConversation."""
    trace_info = trace_detail.get("trace", {})
    observations = trace_detail.get("observations", [])

    if not trace_info.get("id"):
        return None

    tool_calls = _extract_tool_calls_from_observations(observations)
    user_msgs, agent_msgs = _extract_messages(observations)
    outcome = _determine_outcome(observations)

    # Calculate total duration
    total_duration = sum(tc.duration_ms for tc in tool_calls)

    return TraceConversation(
        trace_id=trace_info["id"],
        tool_calls=tool_calls,
        tool_sequence=[tc.tool_name for tc in tool_calls],
        total_turns=len(user_msgs),
        total_duration_ms=total_duration,
        outcome=outcome,
        user_messages=user_msgs,
        agent_messages=agent_msgs,
    )


def parse_langfuse_traces(trace_details: list[dict]) -> list[TraceConversation]:
    """Parse a list of trace detail dicts into TraceConversations."""
    conversations: list[TraceConversation] = []
    for detail in trace_details:
        conv = parse_trace_detail(detail)
        if conv:
            conversations.append(conv)
    return conversations
