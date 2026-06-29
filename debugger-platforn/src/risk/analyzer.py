"""
Risk Analysis Module.
Detects PII handling, critical operations, and compliance concerns.
Maps all risks to OWASP LLM 2025, OWASP Agentic 2026, and MITRE ATLAS taxonomies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from config.framework_signatures import (
    PII_PATTERNS, CRITICAL_ACTION_KEYWORDS,
    OWASP_LLM_2025, OWASP_AGENTIC_2026, RISK_TO_TAXONOMY,
)
from src.analysis.static_analyzer import FileSymbols
from src.analysis.taint_analyzer import TaintFlow, analyze_taint
from src.patterns.detector import ToolDefinition, PromptDefinition


@dataclass
class RiskFlag:
    location: dict
    tool: str | None
    risk_type: str  # "pii", "critical_action", "unsafe_operation", "excessive_agency"
    pii_type: str | None
    severity: str  # "low", "medium", "high", "critical"
    description: str
    mitigation: str | None = None
    taxonomy_ids: list[str] = field(default_factory=list)
    taxonomy_names: list[str] = field(default_factory=list)


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
                    pii_type=category,
                    severity=severity,
                    description=f"Tool '{tool.name}' performs {category} operations (matched: {', '.join(matched_keywords)}).",
                    mitigation=f"Require confirmation before executing {tool.name}.",
                ))
                break  # one risk per tool

    return risks


UNSAFE_OPERATION_PATTERNS = [
    "eval(", "exec(", "subprocess.", "os.system(", "os.popen(", "__import__(",
]


def detect_unsafe_operations(tools: list[ToolDefinition]) -> list[RiskFlag]:
    """Detect tools that invoke eval, exec, subprocess, or similar unsafe calls."""
    risks = []
    for tool in tools:
        code = (tool.code_snippet or "").lower()
        body = ""
        # ToolDefinition may not have body_text; fall back to code_snippet
        if hasattr(tool, "body_text") and tool.body_text:
            body = tool.body_text.lower()
        search_text = f"{code} {body}"

        for pattern in UNSAFE_OPERATION_PATTERNS:
            if pattern.lower() in search_text:
                op_type = pattern.rstrip(".(").split(".")[-1]  # "eval", "exec", etc.
                risks.append(RiskFlag(
                    location=tool.location,
                    tool=tool.name,
                    risk_type="unsafe_operation",
                    pii_type=op_type,
                    severity="critical",
                    description=f"Tool '{tool.name}' uses unsafe operation '{pattern.rstrip('(')}' — risk of arbitrary code execution.",
                    mitigation=f"Remove or sandbox '{pattern.rstrip('(')}' usage in {tool.name}.",
                ))
                break  # one risk per tool
    return risks


def detect_excessive_agency(
    tools: list[ToolDefinition],
    prompts: list[PromptDefinition],
) -> list[RiskFlag]:
    """Flag tools with excessive agency: missing input validation, no confirmation gates, or too many tools without permission scoping."""
    risks = []
    confirmation_keywords = ["confirm", "approve", "verify", "authorization", "permission"]

    for tool in tools:
        code = (tool.code_snippet or "").lower()
        # Flag state-modifying tools without confirmation gates
        if tool.risk_level in ("high", "critical"):
            has_confirmation = any(kw in code for kw in confirmation_keywords)
            if not has_confirmation:
                risks.append(RiskFlag(
                    location=tool.location,
                    tool=tool.name,
                    risk_type="excessive_agency",
                    pii_type=None,
                    severity="high",
                    description=f"High-risk tool '{tool.name}' has no confirmation gate before execution.",
                    mitigation=f"Add user confirmation step before executing {tool.name}.",
                ))

    # Flag if too many tools with no permission scoping
    if len(tools) > 10:
        all_prompts_text = " ".join(p.content for p in prompts if p.content).lower()
        scoping_keywords = ["permission", "allowed", "restricted", "scope", "authorized"]
        has_scoping = any(kw in all_prompts_text for kw in scoping_keywords)
        if not has_scoping:
            risks.append(RiskFlag(
                location={},
                tool=None,
                risk_type="excessive_agency",
                pii_type=None,
                severity="high",
                description=f"Agent has {len(tools)} tools with no permission scoping detected in prompts.",
                mitigation="Add explicit permission boundaries or tool-access policies in system prompts.",
            ))

    return risks


def detect_taint_risks(all_symbols: list[FileSymbols]) -> tuple[list[RiskFlag], list[TaintFlow]]:
    """Run taint analysis and convert flows to RiskFlags.

    Returns (risk_flags, raw_flows) — raw_flows are kept for the Agent Map.
    """
    flows = analyze_taint(all_symbols)
    risks: list[RiskFlag] = []

    for flow in flows:
        pii_str = ", ".join(flow.data_types) if flow.data_types else None
        risks.append(RiskFlag(
            location=flow.source.location,
            tool=None,
            risk_type="taint_flow",
            pii_type=pii_str,
            severity=flow.risk_level,
            description=(
                f"Data flows from {flow.source.description} "
                f"to {flow.sink.description} via {' → '.join(flow.path)}"
            ),
            mitigation=f"Validate or sanitise data before it reaches {flow.sink.description}.",
            taxonomy_ids=list(flow.taxonomy_ids),
            taxonomy_names=[
                OWASP_LLM_2025.get(tid) or OWASP_AGENTIC_2026.get(tid, tid)
                for tid in flow.taxonomy_ids
            ],
        ))

    return risks, flows


def _apply_taxonomy_labels(risks: list[RiskFlag]) -> None:
    """Enrich each RiskFlag with OWASP/MITRE taxonomy identifiers."""
    for risk in risks:
        sub_type = risk.pii_type or risk.risk_type
        key = (risk.risk_type, sub_type)
        tax_ids = RISK_TO_TAXONOMY.get(key, [])
        if tax_ids:
            risk.taxonomy_ids = list(tax_ids)
            risk.taxonomy_names = [
                OWASP_LLM_2025.get(tid) or OWASP_AGENTIC_2026.get(tid, tid)
                for tid in tax_ids
            ]


def analyze_risks(
    tools: list[ToolDefinition],
    prompts: list[PromptDefinition],
    all_symbols: list[FileSymbols] | None = None,
) -> tuple[list[RiskFlag], list[TaintFlow]]:
    """Run all risk detectors, apply taxonomy labels, and return combined risks.

    Returns (risks, taint_flows).  The taint_flows list is provided
    separately so the Agent Map can include the full flow objects.
    """
    risks: list[RiskFlag] = []
    risks.extend(detect_pii_in_tools(tools))
    risks.extend(detect_pii_in_prompts(prompts))
    risks.extend(detect_critical_actions(tools))
    risks.extend(detect_unsafe_operations(tools))
    risks.extend(detect_excessive_agency(tools, prompts))

    # Taint analysis (Sprint 4)
    taint_flows: list[TaintFlow] = []
    if all_symbols:
        taint_risks, taint_flows = detect_taint_risks(all_symbols)
        risks.extend(taint_risks)

    # Deduplicate by (tool, risk_type, pii_type)
    seen = set()
    unique_risks = []
    for r in risks:
        key = (r.tool, r.risk_type, r.pii_type)
        if key not in seen:
            seen.add(key)
            unique_risks.append(r)

    # Apply OWASP/MITRE taxonomy labels to all risks
    # (taint_flow risks already have taxonomy from detect_taint_risks)
    _apply_taxonomy_labels(unique_risks)

    return unique_risks, taint_flows
