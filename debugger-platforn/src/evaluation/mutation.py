"""
Mutation Score Calculator (Sprint E12.5).

Seeds faults into the agent map ("mutants") and measures what fraction of
them the test suite can detect (Just et al., FSE 2014: mutant detection
correlates with real fault detection).  Each mutant is a deep copy of the
agent map with exactly one mutation applied.
"""

from __future__ import annotations

import copy
from enum import Enum
from typing import Any, Dict, List, Optional


class MutationOperator(str, Enum):
    REMOVE_GUARDRAIL = "remove_guardrail"         # Delete one guardrail rule from prompt
    SWAP_TOOL = "swap_tool"                       # Replace one tool call with another
    REMOVE_ESCALATION = "remove_escalation"       # Remove escalation trigger
    INJECT_PII = "inject_pii"                     # Add PII to a tool response
    WRONG_LANGUAGE = "wrong_language"             # Force response in wrong language
    REMOVE_CONFIRMATION = "remove_confirmation"   # Skip confirmation gate
    TRUNCATE_CONTEXT = "truncate_context"         # Cut conversation history


_ESCALATION_KEYWORDS = ("escalat", "handoff", "hand_off", "transfer_to_human", "human_agent")
_CONFIRMATION_KEYWORDS = ("confirm", "verify", "approval", "authorize", "authorise")


def _tools_of(agent_map: Dict) -> List[Dict]:
    return agent_map.get("components", {}).get("tools", [])


def _rules_of(agent_map: Dict) -> List[Dict]:
    return (agent_map.get("guardrails") or {}).get("rules", [])


def _remove_guardrail_mutants(agent_map: Dict) -> List[Dict]:
    mutants = []
    for rule in _rules_of(agent_map):
        rule_id = rule.get("rule_id", "?")
        mutated = copy.deepcopy(agent_map)
        mutated["guardrails"]["rules"] = [
            r for r in mutated["guardrails"]["rules"] if r.get("rule_id") != rule_id
        ]
        if "total_rules" in mutated["guardrails"]:
            mutated["guardrails"]["total_rules"] = len(mutated["guardrails"]["rules"])
        mutants.append({
            "operator": MutationOperator.REMOVE_GUARDRAIL,
            "description": f"Removed guardrail rule {rule_id}: {(rule.get('text') or '')[:80]}",
            "modified_agent_map": mutated,
        })
    return mutants


def _swap_tool_mutants(agent_map: Dict) -> List[Dict]:
    mutants = []
    tools = _tools_of(agent_map)
    for i in range(len(tools) - 1):
        name_a = tools[i].get("name", "")
        name_b = tools[i + 1].get("name", "")
        if not name_a or not name_b:
            continue
        mutated = copy.deepcopy(agent_map)
        mutated_tools = _tools_of(mutated)
        mutated_tools[i]["name"] = name_b
        mutated_tools[i + 1]["name"] = name_a
        mutants.append({
            "operator": MutationOperator.SWAP_TOOL,
            "description": f"Swapped tool '{name_a}' with '{name_b}' (calls route to the wrong implementation)",
            "modified_agent_map": mutated,
        })
    return mutants


def _remove_escalation_mutants(agent_map: Dict) -> List[Dict]:
    escalation_tools = [
        t.get("name") or "" for t in _tools_of(agent_map)
        if any(kw in ((t.get("name") or "") + " " + (t.get("description") or "")).lower()
               for kw in _ESCALATION_KEYWORDS)
    ]
    escalation_rules = [
        r.get("rule_id") for r in _rules_of(agent_map)
        if any(kw in (r.get("text") or "").lower() for kw in _ESCALATION_KEYWORDS)
    ]
    if not escalation_tools and not escalation_rules:
        return []

    mutated = copy.deepcopy(agent_map)
    mutated["components"]["tools"] = [
        t for t in _tools_of(mutated) if t.get("name") not in escalation_tools
    ]
    if _rules_of(mutated):
        mutated["guardrails"]["rules"] = [
            r for r in mutated["guardrails"]["rules"] if r.get("rule_id") not in escalation_rules
        ]
        if "total_rules" in mutated["guardrails"]:
            mutated["guardrails"]["total_rules"] = len(mutated["guardrails"]["rules"])
    removed = escalation_tools + [r for r in escalation_rules if r]
    return [{
        "operator": MutationOperator.REMOVE_ESCALATION,
        "description": f"Removed escalation triggers: {', '.join(removed)}",
        "modified_agent_map": mutated,
    }]


def _inject_pii_mutants(agent_map: Dict) -> List[Dict]:
    mutants = []
    for i, tool in enumerate(_tools_of(agent_map)):
        name = tool.get("name", "")
        if not name:
            continue
        mutated = copy.deepcopy(agent_map)
        mutated_tool = _tools_of(mutated)[i]
        side_effects = list(mutated_tool.get("side_effects", []) or [])
        side_effects.append(
            "MUTATION: response includes raw customer PII (full name, email, phone, address)"
        )
        mutated_tool["side_effects"] = side_effects
        mutants.append({
            "operator": MutationOperator.INJECT_PII,
            "description": f"Injected PII into responses of tool '{name}'",
            "modified_agent_map": mutated,
        })
    return mutants


def _wrong_language_mutants(agent_map: Dict) -> List[Dict]:
    mutated = copy.deepcopy(agent_map)
    metadata = mutated.setdefault("metadata", {})
    current = metadata.get("conversation_language") or "English"
    wrong = "Spanish" if current.lower() in ("english", "en") else "English"
    metadata["conversation_language"] = wrong
    return [{
        "operator": MutationOperator.WRONG_LANGUAGE,
        "description": f"Forced responses in wrong language: {current} -> {wrong}",
        "modified_agent_map": mutated,
    }]


def _remove_confirmation_mutants(agent_map: Dict) -> List[Dict]:
    mutants = []

    # Confirmation gates expressed as tool preconditions
    for i, tool in enumerate(_tools_of(agent_map)):
        preconditions = tool.get("preconditions", []) or []
        gated = [p for p in preconditions if any(kw in str(p).lower() for kw in _CONFIRMATION_KEYWORDS)]
        if not gated:
            continue
        mutated = copy.deepcopy(agent_map)
        mutated_tool = _tools_of(mutated)[i]
        mutated_tool["preconditions"] = [p for p in preconditions if p not in gated]
        mutants.append({
            "operator": MutationOperator.REMOVE_CONFIRMATION,
            "description": f"Removed confirmation gate from tool '{tool.get('name', '')}': {gated[0]}",
            "modified_agent_map": mutated,
        })

    # Confirmation gates expressed as guardrail rules
    for rule in _rules_of(agent_map):
        text = (rule.get("text") or "").lower()
        category = str(rule.get("category", "")).lower()
        if category != "confirmation" and not any(kw in text for kw in _CONFIRMATION_KEYWORDS):
            continue
        rule_id = rule.get("rule_id", "?")
        mutated = copy.deepcopy(agent_map)
        mutated["guardrails"]["rules"] = [
            r for r in mutated["guardrails"]["rules"] if r.get("rule_id") != rule_id
        ]
        if "total_rules" in mutated["guardrails"]:
            mutated["guardrails"]["total_rules"] = len(mutated["guardrails"]["rules"])
        mutants.append({
            "operator": MutationOperator.REMOVE_CONFIRMATION,
            "description": f"Removed confirmation guardrail {rule_id}: {(rule.get('text') or '')[:80]}",
            "modified_agent_map": mutated,
        })

    return mutants


def _truncate_context_mutants(agent_map: Dict) -> List[Dict]:
    mutated = copy.deepcopy(agent_map)
    criteria = mutated.setdefault("success_criteria", {})
    original_turns = criteria.get("max_turns") or 20
    criteria["max_turns"] = min(3, original_turns)
    criteria["context_truncated"] = True
    return [{
        "operator": MutationOperator.TRUNCATE_CONTEXT,
        "description": f"Truncated conversation context: max_turns {original_turns} -> {criteria['max_turns']}",
        "modified_agent_map": mutated,
    }]


_OPERATOR_GENERATORS = {
    MutationOperator.REMOVE_GUARDRAIL: _remove_guardrail_mutants,
    MutationOperator.SWAP_TOOL: _swap_tool_mutants,
    MutationOperator.REMOVE_ESCALATION: _remove_escalation_mutants,
    MutationOperator.INJECT_PII: _inject_pii_mutants,
    MutationOperator.WRONG_LANGUAGE: _wrong_language_mutants,
    MutationOperator.REMOVE_CONFIRMATION: _remove_confirmation_mutants,
    MutationOperator.TRUNCATE_CONTEXT: _truncate_context_mutants,
}


def generate_mutants(
    agent_map: Dict,
    operators: Optional[List[MutationOperator]] = None,
) -> List[Dict]:
    """Generate mutants of an agent map, one mutation applied per mutant.

    Args:
        agent_map: the original (unmutated) agent map.
        operators: subset of operators to apply; defaults to all.

    Returns:
        list of ``{mutant_id, operator, description, modified_agent_map}``.
        Operators that find nothing to mutate produce no mutants.
    """
    if operators is None:
        operators = list(MutationOperator)

    mutants: List[Dict] = []
    for op in operators:
        mutants.extend(_OPERATOR_GENERATORS[op](agent_map))

    for i, mutant in enumerate(mutants, start=1):
        mutant["mutant_id"] = f"M{i:03d}"
        mutant["operator"] = MutationOperator(mutant["operator"]).value
    return mutants


def compute_mutation_score(
    test_suite: Any,
    mutants: List[Dict],
    execution_results: Dict[str, Any],
) -> float:
    """Compute mutation score = killed_mutants / total_mutants.

    A mutant is "killed" when at least one test case produces a different
    outcome on the mutant than on the original agent.

    Args:
        test_suite: the TestSuite the results were produced with (or None).
        mutants: output of :func:`generate_mutants`.
        execution_results: per-run outcomes keyed by run:
            ``execution_results["original"]`` maps test_id -> outcome for the
            unmutated agent; ``execution_results[mutant_id]`` maps test_id ->
            outcome for that mutant.  A mutant entry may instead be a bool
            (True = killed) for pre-judged results.

    Returns:
        mutation score in [0, 1]; 0.0 when there are no mutants.
    """
    if not mutants:
        return 0.0

    baseline: Dict[str, Any] = execution_results.get("original", {}) or {}

    killed = 0
    for mutant in mutants:
        result = execution_results.get(mutant.get("mutant_id"))
        if result is None:
            continue
        if isinstance(result, bool):
            killed += int(result)
            continue
        # dict of test_id -> outcome: killed when any shared test differs
        if any(
            test_id in baseline and outcome != baseline[test_id]
            for test_id, outcome in result.items()
        ):
            killed += 1

    return killed / len(mutants)
