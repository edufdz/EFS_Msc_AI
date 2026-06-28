"""
RootCauseAnalyzer: identifies the root cause for each failure cluster
using AI analysis (with offline heuristic fallback).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple


def _load_trace(trace_file: str) -> Optional[Dict]:
    if not trace_file or not os.path.exists(trace_file):
        return None
    with open(trace_file) as f:
        return json.load(f)


def _parse_json_response(text: str) -> Dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        text = text.strip()
    return json.loads(text)


class RootCauseAnalyzer:
    """Analyze a cluster of failures to determine root cause."""

    def __init__(self, use_ai: bool = True, retry_config=None):
        self.use_ai = use_ai
        self._retry_config = retry_config

    def analyze_cluster(
        self,
        cluster_failures: List[Dict],
    ) -> Tuple[str, str, str, List[str]]:
        """Analyze a cluster and return (root_cause_type, description, common_pattern, indicators)."""
        if self.use_ai:
            try:
                return self._ai_analyze(cluster_failures)
            except Exception:
                pass
        return self._heuristic_analyze(cluster_failures)

    # ------------------------------------------------------------------
    # AI-powered analysis
    # ------------------------------------------------------------------

    def _ai_analyze(
        self, failures: List[Dict]
    ) -> Tuple[str, str, str, List[str]]:
        from anthropic import Anthropic
        from .retry import retry_anthropic

        samples = failures[:5]
        samples_text = self._format_samples(samples)

        prompt = f"""You are analyzing agent test failures to identify root causes.

You have a cluster of {len(failures)} similar failures. Here are {len(samples)} samples:

{samples_text}

Root cause types (pick ONE):
- service_unavailable: Agent's backend service returned errors
- timeout_handling: Agent couldn't complete within turn limit
- error_handling: Agent doesn't recover from tool/API errors
- edge_case_unhandled: Specific scenario variant not handled
- prompt_issue: System prompt is unclear or missing instructions
- tool_selection_error: Agent uses wrong tool for the task
- validation_missing: No input/output validation
- state_management: Agent loses track of conversation state
- hallucination: Agent fabricates information
- missing_guardrail: No safety check where needed
- retry_logic_bug: Agent doesn't retry on transient errors

Output ONLY valid JSON:
{{
  "root_cause_type": "one_of_the_types_above",
  "description": "2-3 sentence explanation of what is going wrong",
  "common_pattern": "One sentence: what all failures share",
  "key_indicators": ["indicator1", "indicator2", "indicator3"]
}}"""

        client = Anthropic()

        @retry_anthropic(self._retry_config)
        def _call():
            return client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=1000,
                temperature=0.2,
                messages=[{"role": "user", "content": prompt}],
            )

        response = _call()

        data = _parse_json_response(response.content[0].text)
        return (
            data["root_cause_type"],
            data["description"],
            data["common_pattern"],
            data.get("key_indicators", []),
        )

    # ------------------------------------------------------------------
    # Heuristic fallback
    # ------------------------------------------------------------------

    def _heuristic_analyze(
        self, failures: List[Dict]
    ) -> Tuple[str, str, str, List[str]]:
        reasons = [f.get("failure_reason", "").lower() for f in failures]
        scenarios = [f.get("scenario", "").lower() for f in failures]

        # Classify by dominant failure reason
        service_errors = sum(1 for r in reasons if "unavailable" in r or "service" in r)
        max_turns = sum(1 for r in reasons if "max turns" in r)
        agent_errors = sum(1 for r in reasons if "agent error" in r)
        timeouts = sum(1 for r in reasons if "timeout" in r or "timed out" in r)

        total = len(failures)

        if service_errors > total * 0.5:
            return (
                "service_unavailable",
                f"Agent's backend service returned 'service unavailable' errors in {service_errors}/{total} failures. "
                "The agent does not gracefully handle service outages and fails to provide fallback responses or retry.",
                "All failures share a common 'service unavailable' error from the backend",
                ["service unavailable error", "no retry logic", "no fallback response"],
            )

        if max_turns > total * 0.5:
            boundary = sum(1 for s in scenarios if "boundary" in s)
            if boundary > total * 0.3:
                return (
                    "edge_case_unhandled",
                    f"Adversarial/boundary-testing scenarios exhaust the turn limit ({max_turns}/{total}). "
                    "The agent cannot conclude conversations with users who test its boundaries, "
                    "leading to infinite loops.",
                    "Boundary-testing personas cause the agent to loop without resolving",
                    ["max turns exceeded", "boundary testing scenario", "adversarial persona"],
                )
            return (
                "timeout_handling",
                f"Conversations exceed the maximum turn limit ({max_turns}/{total}). "
                "The agent fails to reach a resolution within the allowed number of turns, "
                "indicating poor conversation efficiency or missing exit conditions.",
                "Agent cannot resolve conversations within the turn limit",
                ["max turns exceeded", "long conversations", "no resolution"],
            )

        if agent_errors > total * 0.5:
            return (
                "error_handling",
                f"Agent returns errors without recovery ({agent_errors}/{total}). "
                "When tool calls or API requests fail, the agent does not retry or provide "
                "graceful degradation.",
                "Agent propagates internal errors instead of handling them",
                ["agent error", "no error recovery", "tool call failure"],
            )

        if timeouts > total * 0.3:
            return (
                "timeout_handling",
                f"Tool calls or API requests time out ({timeouts}/{total}). "
                "The agent lacks timeout handling and retry mechanisms.",
                "Operations time out without fallback behavior",
                ["timeout", "slow response", "no retry"],
            )

        # Mixed / unknown
        return (
            "edge_case_unhandled",
            f"A mix of failure modes across {total} failures. "
            "No single dominant root cause; likely multiple edge cases that the agent "
            "does not handle.",
            "Multiple unhandled edge cases across different scenarios",
            ["mixed failures", "edge cases", "varied scenarios"],
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _format_samples(self, samples: List[Dict]) -> str:
        parts = []
        for i, f in enumerate(samples, 1):
            trace = _load_trace(f.get("trace_file", ""))
            tools = []
            conversation_snippet = ""
            if trace:
                for turn in trace.get("turns", []):
                    for tc in turn.get("tool_calls", []):
                        tools.append(tc.get("tool_name", ""))
                # First and last turn
                turns = trace.get("turns", [])
                if turns:
                    first_user = next((t for t in turns if t["role"] == "user"), None)
                    last_agent = next((t for t in reversed(turns) if t["role"] == "agent"), None)
                    if first_user:
                        conversation_snippet += f'  First user msg: "{first_user["message"][:100]}"\n'
                    if last_agent:
                        conversation_snippet += f'  Last agent msg: "{last_agent["message"][:100]}"\n'

            parts.append(
                f"Sample {i}:\n"
                f"  Scenario: {f.get('scenario')}\n"
                f"  Persona: {f.get('persona')}\n"
                f"  Failure: {f.get('failure_reason')}\n"
                f"  Turns: {f.get('total_turns', '?')}\n"
                f"  Tools called: {tools}\n"
                f"  Coverage goal: {f.get('coverage_goal', '?')}\n"
                f"{conversation_snippet}"
            )
        return "\n".join(parts)
