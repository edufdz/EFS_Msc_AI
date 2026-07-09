"""
Pydantic models for non-LLM oracles (Sprint E4).

Oracles are deterministic, machine-evaluable success/failure checks
derived from Phase A data (postconditions, guardrails, taint flows,
side effects, tool sequences). MetamorphicRelation captures invariants
between two paired executions (e.g. usted vs tú must not change tool
calls).

Note: the codebase uses pydantic models (not plain dataclasses) for
everything nested inside Scenario/TestCase, so these follow suit —
they serialise transparently through ScenarioCatalog and TestSuite.
"""

from __future__ import annotations

from enum import Enum
from typing import List

from pydantic import BaseModel, Field


class OracleType(str, Enum):
    POSTCONDITION = "postcondition"        # Tool postcondition must hold after execution
    GUARDRAIL_COMPLIANCE = "guardrail"     # Numbered guardrail rule must be followed
    GUARDRAIL_VIOLATION = "guardrail_neg"  # Provocation: test input invites violation, agent must resist
    TAINT_FLOW = "taint_flow"              # PII must not flow from source to sink
    TOOL_SEQUENCE = "tool_sequence"        # Expected tool call ordering
    STATE_CHECK = "state_check"            # Database/environment state after execution
    METAMORPHIC = "metamorphic"            # Relation between two executions must hold
    SIDE_EFFECT = "side_effect"            # Expected side-effects must/must-not occur


class Oracle(BaseModel):
    oracle_id: str
    oracle_type: OracleType
    description: str        # Human-readable: "After refund, order status must be 'refunded'"
    check_expression: str   # Machine-evaluable: "tool_result.status == 'refunded'"
    source: str             # "postcondition:process_refund", "guardrail:R003", "taint:email→http"
    severity: str = "medium"  # Weight for scoring: critical|high|medium|low
    applies_to_tools: List[str] = Field(default_factory=list)  # Tools this oracle covers
    applies_to_rules: List[str] = Field(default_factory=list)  # Guardrail rule IDs this oracle covers

    def to_test_case_dict(self) -> dict:
        """Compact serialisation carried onto TestCase.oracles (Sprint E4.5)."""
        return {
            "oracle_id": self.oracle_id,
            "type": self.oracle_type.value,
            "description": self.description,
            "check_expression": self.check_expression,
            "severity": self.severity,
        }


class MetamorphicRelation(BaseModel):
    relation_id: str
    description: str          # "Language invariance: usted vs tú must produce same tool calls"
    base_scenario_id: str
    mutant_scenario_id: str
    invariant: str            # "tool_calls_equal" | "policy_outcome_equal" | "response_language_equal"
    source: str               # "language_invariance" | "formality_invariance" | "synonym_invariance" | "ordering_invariance"
