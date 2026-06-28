"""
FixProposalGenerator: generates actionable fix proposals for each cluster.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from .models import FailureCluster, RootCauseType


def _parse_json_response(text: str) -> Dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        text = text.strip()
    return json.loads(text)


# Map root-cause types to which fix strategies apply
_FIX_STRATEGIES: Dict[str, List[str]] = {
    "prompt_issue": ["prompt_patch"],
    "tool_selection_error": ["prompt_patch", "tool_fix"],
    "tool_schema_mismatch": ["tool_fix"],
    "missing_guardrail": ["validation_rule", "prompt_patch"],
    "retry_logic_bug": ["config_change", "code_change"],
    "hallucination": ["prompt_patch", "validation_rule"],
    "timeout_handling": ["config_change"],
    "error_handling": ["code_change", "config_change"],
    "state_management": ["code_change"],
    "validation_missing": ["validation_rule"],
    "edge_case_unhandled": ["prompt_patch", "validation_rule"],
    "service_unavailable": ["config_change", "code_change"],
}


class FixProposalGenerator:
    """Generate fix proposals for failure clusters."""

    def __init__(self, use_ai: bool = True, retry_config=None):
        self.use_ai = use_ai
        self._retry_config = retry_config

    def generate(
        self,
        cluster: FailureCluster,
        agent_map: Dict,
    ) -> List[Dict[str, Any]]:
        """Return a list of fix-proposal dicts for this cluster."""
        strategies = _FIX_STRATEGIES.get(cluster.root_cause_type.value, ["prompt_patch"])
        proposals: List[Dict[str, Any]] = []

        for strategy in strategies:
            if self.use_ai:
                try:
                    fix = self._ai_generate_fix(cluster, agent_map, strategy)
                    if fix:
                        proposals.append(fix)
                        continue
                except Exception:
                    pass
            fix = self._offline_generate_fix(cluster, agent_map, strategy)
            if fix:
                proposals.append(fix)

        return proposals

    # ------------------------------------------------------------------
    # AI-powered fix generation
    # ------------------------------------------------------------------

    def _ai_generate_fix(
        self,
        cluster: FailureCluster,
        agent_map: Dict,
        fix_type: str,
    ) -> Optional[Dict[str, Any]]:
        from anthropic import Anthropic
        from .retry import retry_anthropic

        prompt = self._build_fix_prompt(cluster, agent_map, fix_type)
        client = Anthropic()

        @retry_anthropic(self._retry_config)
        def _call():
            return client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=1500,
                temperature=0.3,
                messages=[{"role": "user", "content": prompt}],
            )

        response = _call()
        return _parse_json_response(response.content[0].text)

    def _build_fix_prompt(
        self,
        cluster: FailureCluster,
        agent_map: Dict,
        fix_type: str,
    ) -> str:
        agent_purpose = agent_map.get("metadata", {}).get("purpose", "")
        tools_summary = ", ".join(
            t["name"] for t in agent_map.get("components", {}).get("tools", [])[:10]
        )

        return f"""You are proposing a fix for an agent failure.

Agent purpose: {agent_purpose}
Available tools (sample): {tools_summary}

Failure cluster ({cluster.failure_count} failures):
  Root cause: {cluster.root_cause_type.value}
  Description: {cluster.root_cause_description}
  Pattern: {cluster.common_pattern}
  Affected scenarios: {cluster.affected_scenarios[:5]}
  Key indicators: {cluster.key_indicators}

Generate a "{fix_type}" fix.

Output ONLY valid JSON:
{{
  "fix_type": "{fix_type}",
  "description": "What this fix does (1-2 sentences)",
  "changes": {{
    "type": "specific change details relevant to {fix_type}",
    "rationale": "Why this fixes the issue"
  }},
  "estimated_fix_rate": 0.7,
  "estimated_effort": "low|medium|high",
  "risk_level": "low|medium|high"
}}"""

    # ------------------------------------------------------------------
    # Offline fallback
    # ------------------------------------------------------------------

    def _offline_generate_fix(
        self,
        cluster: FailureCluster,
        agent_map: Dict,
        fix_type: str,
    ) -> Optional[Dict[str, Any]]:
        rc = cluster.root_cause_type.value

        if fix_type == "prompt_patch":
            return {
                "fix_type": "prompt_patch",
                "description": f"Add instructions to handle '{rc}' scenarios in system prompt",
                "changes": {
                    "type": "append",
                    "location": "end_of_system_prompt",
                    "new_text": self._generate_prompt_patch_text(cluster),
                    "rationale": f"Addresses {cluster.failure_count} failures caused by {rc}",
                },
                "estimated_fix_rate": 0.6,
                "estimated_effort": "low",
                "risk_level": "low",
            }

        if fix_type == "config_change":
            return self._generate_config_fix(cluster)

        if fix_type == "validation_rule":
            return {
                "fix_type": "validation_rule",
                "description": f"Add validation to detect and handle '{rc}' conditions",
                "changes": {
                    "validation_type": "output",
                    "condition": f"Check for {rc} indicators before returning response",
                    "error_message": f"Detected potential {rc} — triggering fallback",
                    "action": "fallback",
                },
                "estimated_fix_rate": 0.5,
                "estimated_effort": "medium",
                "risk_level": "low",
            }

        if fix_type == "code_change":
            return {
                "fix_type": "code_change",
                "description": f"Implement {rc} handling logic in agent code",
                "changes": {
                    "component": "error_handler" if "error" in rc else "orchestrator",
                    "modification": f"Add {rc} detection and recovery",
                    "rationale": f"Prevents {cluster.failure_count} failures",
                },
                "estimated_fix_rate": 0.7,
                "estimated_effort": "high",
                "risk_level": "medium",
            }

        if fix_type == "tool_fix":
            return {
                "fix_type": "tool_fix",
                "description": f"Update tool definitions to address {rc}",
                "changes": {
                    "affected_tools": cluster.affected_tools[:3],
                    "modification": "Improve descriptions and parameter validation",
                    "rationale": f"Better tool descriptions reduce {rc}",
                },
                "estimated_fix_rate": 0.5,
                "estimated_effort": "medium",
                "risk_level": "low",
            }

        return None

    # ------------------------------------------------------------------
    # Prompt-patch text helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_prompt_patch_text(cluster: FailureCluster) -> str:
        rc = cluster.root_cause_type.value
        patches = {
            "service_unavailable": (
                "If a tool call fails with a service error, apologize to the user, "
                "explain the issue briefly, and offer to retry or escalate to a human agent."
            ),
            "timeout_handling": (
                "If the conversation is taking many turns without resolution, "
                "summarize what has been accomplished, ask if the user needs anything else, "
                "and offer to escalate to a human if needed."
            ),
            "error_handling": (
                "When a tool returns an error, do NOT simply repeat the error to the user. "
                "Instead, try an alternative approach or ask the user for more information."
            ),
            "edge_case_unhandled": (
                "If a user request is outside your capabilities or seems adversarial, "
                "clearly state your limitations and offer to connect them with a human agent."
            ),
            "hallucination": (
                "Never make up information. If you don't have the data, say so explicitly "
                "and offer to look it up using the available tools."
            ),
            "missing_guardrail": (
                "Before performing any action, verify that all required parameters are present. "
                "If information is missing, ask the user before proceeding."
            ),
        }
        return patches.get(rc, f"Handle {rc} scenarios gracefully with appropriate fallback behavior.")

    @staticmethod
    def _generate_config_fix(cluster: FailureCluster) -> Dict[str, Any]:
        rc = cluster.root_cause_type.value
        if rc == "timeout_handling":
            return {
                "fix_type": "config_change",
                "description": "Increase timeout and add retry with backoff",
                "changes": {
                    "timeout_sec": {"current": 10, "proposed": 30},
                    "max_retries": {"current": 0, "proposed": 2},
                    "backoff_strategy": "exponential",
                },
                "estimated_fix_rate": 0.8,
                "estimated_effort": "low",
                "risk_level": "low",
            }
        if rc == "service_unavailable":
            return {
                "fix_type": "config_change",
                "description": "Add retry logic with circuit breaker for service calls",
                "changes": {
                    "max_retries": {"current": 0, "proposed": 3},
                    "circuit_breaker_threshold": 5,
                    "fallback_response": "Service temporarily unavailable, please try again",
                },
                "estimated_fix_rate": 0.75,
                "estimated_effort": "medium",
                "risk_level": "low",
            }
        return {
            "fix_type": "config_change",
            "description": f"Adjust configuration to mitigate {rc}",
            "changes": {"rationale": f"Configuration tuning for {rc}"},
            "estimated_fix_rate": 0.5,
            "estimated_effort": "low",
            "risk_level": "low",
        }
