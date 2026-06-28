"""
Risk Analysis Module.
Detects PII handling, critical operations, and compliance concerns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from config.framework_signatures import PII_PATTERNS, CRITICAL_ACTION_KEYWORDS
from src.patterns.detector import ToolDefinition, PromptDefinition


@dataclass
class RiskFlag:
    location: dict
    tool: str | None
    risk_type: str  # "pii", "critical_action", "data_modification", etc.
    pii_type: str | None
    severity: str  # "low", "medium", "high", "critical"
    description: str
    mitigation: str | None = None


def detect_pii_in_tools(tools: list[ToolDefinition]) -> list[RiskFlag]:
    """Check tool parameters and descriptions for PII patterns."""
    risks = []

    for tool in tools:
        for param in tool.parameters:
            param_name = param.get("name", "").lower()

            # Check keyword-based PII
            for kw in PII_PATTERNS.get("address_keywords", []):
                if kw in param_name:
                    risks.append(RiskFlag(
                        location=tool.location,
                        tool=tool.name,
                        risk_type="pii",
                        pii_type="address",
                        severity="high",
                        description=f"Parameter '{param.get('name')}' in tool '{tool.name}' may handle address data.",
                    ))

            # Check regex-based PII in parameter names
            for pii_type, pattern in PII_PATTERNS.items():
                if pii_type == "address_keywords":
                    continue
                if isinstance(pattern, str):
                    if any(kw in param_name for kw in pii_type.split("_")):
                        risks.append(RiskFlag(
                            location=tool.location,
                            tool=tool.name,
                            risk_type="pii",
                            pii_type=pii_type,
                            severity="high",
                            description=f"Parameter '{param.get('name')}' in tool '{tool.name}' may handle {pii_type} data.",
                        ))

        # Check tool description/code for PII patterns
        text_to_check = (tool.description or "") + " " + (tool.code_snippet or "")
        for pii_type, pattern in PII_PATTERNS.items():
            if pii_type == "address_keywords":
                continue
            if isinstance(pattern, str) and re.search(pattern, text_to_check):
                risks.append(RiskFlag(
                    location=tool.location,
                    tool=tool.name,
                    risk_type="pii",
                    pii_type=pii_type,
                    severity="medium",
                    description=f"Tool '{tool.name}' code/description contains {pii_type} pattern.",
                ))

    return risks


def detect_pii_in_prompts(prompts: list[PromptDefinition]) -> list[RiskFlag]:
    """Check prompts for PII patterns."""
    risks = []
    for prompt in prompts:
        for pii_type, pattern in PII_PATTERNS.items():
            if pii_type == "address_keywords":
                continue
            if isinstance(pattern, str) and re.search(pattern, prompt.content):
                risks.append(RiskFlag(
                    location=prompt.location,
                    tool=None,
                    risk_type="pii",
                    pii_type=pii_type,
                    severity="high",
                    description=f"Prompt '{prompt.name}' contains {pii_type} pattern.",
                ))
    return risks


def detect_critical_actions(tools: list[ToolDefinition]) -> list[RiskFlag]:
    """Identify tools that perform irreversible or sensitive operations."""
    risks = []

    for tool in tools:
        name_lower = tool.name.lower()
        desc_lower = (tool.description or "").lower()
        code_lower = (tool.code_snippet or "").lower()
        search_text = f"{name_lower} {desc_lower} {code_lower}"

        for category, keywords in CRITICAL_ACTION_KEYWORDS.items():
            matched_keywords = [kw for kw in keywords if kw in search_text]
            if matched_keywords:
                severity = "critical" if category == "financial" else "high"
                risks.append(RiskFlag(
                    location=tool.location,
                    tool=tool.name,
                    risk_type="critical_action",
                    pii_type=None,
                    severity=severity,
                    description=f"Tool '{tool.name}' performs {category} operations (matched: {', '.join(matched_keywords)}).",
                    mitigation=f"Require confirmation before executing {tool.name}.",
                ))
                break  # one risk per tool

    return risks


def analyze_risks(
    tools: list[ToolDefinition],
    prompts: list[PromptDefinition],
) -> list[RiskFlag]:
    """Run all risk detectors and return combined risks."""
    risks = []
    risks.extend(detect_pii_in_tools(tools))
    risks.extend(detect_pii_in_prompts(prompts))
    risks.extend(detect_critical_actions(tools))

    # Deduplicate by (tool, risk_type, pii_type)
    seen = set()
    unique_risks = []
    for r in risks:
        key = (r.tool, r.risk_type, r.pii_type)
        if key not in seen:
            seen.add(key)
            unique_risks.append(r)

    return unique_risks
