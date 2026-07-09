"""
Non-LLM oracle package (Sprint E4).

Derives executable success/failure conditions for scenarios from Phase A
data — tool postconditions, guardrail rules, taint-flow sinks, side
effects, and dependency-graph tool sequences — plus metamorphic
relations between paired executions. No LLM judge is involved: every
oracle is a deterministic check that Phase C can evaluate against tool
calls, agent output, and environment state.

Literature: tau-bench (Yao et al., 2024) and AgentDojo (Debenedetti et
al., NeurIPS 2024) evaluate with state-based checks; Barr et al. (IEEE
TSE 2015) catalogue specified/derived/metamorphic oracles; Segura et
al. (IEEE TSE 2016) formalise metamorphic testing.
"""

from src.oracles.models import MetamorphicRelation, Oracle, OracleType
from src.oracles.generator import generate_oracles_from_agent_map
from src.oracles.metamorphic import generate_metamorphic_relations

__all__ = [
    "Oracle",
    "OracleType",
    "MetamorphicRelation",
    "generate_oracles_from_agent_map",
    "generate_metamorphic_relations",
]
