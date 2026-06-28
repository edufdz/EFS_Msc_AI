"""
MinimalReproducer: generates the shortest conversation that triggers a bug.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

from .models import FailureCluster


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


class MinimalReproducer:
    """Generate minimal reproductions for failure clusters."""

    def __init__(self, use_ai: bool = True, retry_config=None):
        self.use_ai = use_ai
        self._retry_config = retry_config

    def generate(self, cluster: FailureCluster) -> Dict[str, Any]:
        """Generate minimal reproduction for a cluster."""
        # Pick the shortest failure
        shortest = min(cluster.failure_examples, key=lambda f: f.turn_count or 999)
        trace = _load_trace(shortest.trace_file)

        if self.use_ai and trace:
            try:
                return self._ai_generate(shortest, trace, cluster)
            except Exception:
                pass

        return self._offline_generate(shortest, trace, cluster)

    # ------------------------------------------------------------------
    # AI-powered
    # ------------------------------------------------------------------

    def _ai_generate(
        self,
        failure,
        trace: Dict,
        cluster: FailureCluster,
    ) -> Dict[str, Any]:
        from anthropic import Anthropic
        from .retry import retry_anthropic

        conversation = self._extract_conversation(trace)

        prompt = f"""You are creating a minimal reproduction of an agent bug.

Root cause: {cluster.root_cause_description}

Full conversation ({len(conversation)} exchanges):
{json.dumps(conversation, indent=2)}

Failure reason: {failure.failure_reason}

Create the SHORTEST possible conversation that triggers this bug.
Remove unnecessary turns, simplify messages, keep only essential tool calls.

Output ONLY valid JSON:
{{
  "minimal_conversation": [
    {{"role": "user", "content": "..."}},
    {{"role": "agent", "content": "...", "tool_calls": []}}
  ],
  "setup": {{
    "scenario": "One-sentence description",
    "persona": "Simple persona description",
    "required_tools": []
  }},
  "expected_behavior": "What should happen",
  "actual_behavior": "What actually happens (the bug)",
  "steps_to_reproduce": ["step1", "step2"]
}}"""

        client = Anthropic()

        @retry_anthropic(self._retry_config)
        def _call():
            return client.messages.create(
                model="claude-haiku-4-5",  # Switched to Haiku for cost savings (~67% cheaper)
                max_tokens=1500,
                temperature=0.2,
                messages=[{"role": "user", "content": prompt}],
            )

        response = _call()
        return _parse_json_response(response.content[0].text)

    # ------------------------------------------------------------------
    # Offline fallback
    # ------------------------------------------------------------------

    def _offline_generate(
        self,
        failure,
        trace: Optional[Dict],
        cluster: FailureCluster,
    ) -> Dict[str, Any]:
        conversation = self._extract_conversation(trace) if trace else []

        # Take at most first 2 exchanges
        minimal = conversation[:2] if conversation else [
            {"role": "user", "content": f"Request related to: {failure.scenario}"}
        ]

        return {
            "minimal_conversation": minimal,
            "setup": {
                "scenario": failure.scenario,
                "persona": failure.persona,
                "required_tools": failure.tools_expected,
            },
            "expected_behavior": "Agent should handle the request successfully or fail gracefully",
            "actual_behavior": failure.failure_reason,
            "steps_to_reproduce": [
                f"Use persona: {failure.persona}",
                f"Run scenario: {failure.scenario}",
                f"Observe: {failure.failure_reason}",
            ],
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_conversation(trace: Dict) -> List[Dict[str, Any]]:
        conv: List[Dict[str, Any]] = []
        for turn in trace.get("turns", []):
            entry: Dict[str, Any] = {
                "role": turn.get("role", "unknown"),
                "content": turn.get("message", ""),
            }
            if turn.get("tool_calls"):
                entry["tool_calls"] = turn["tool_calls"]
            conv.append(entry)
        return conv
