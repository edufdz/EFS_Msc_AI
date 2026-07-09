"""
Metamorphic relation generator (Sprint E4.3).

Builds partial oracles from necessary properties (Segura et al., IEEE
TSE 2016): two executions related by a meaning-preserving transformation
of the input must agree on tool calls / policy outcome, without needing
a full specification of correct behaviour.

Relations reference the base scenario by ID and a deterministic mutant
scenario ID (``<base_id>::<source>``). Phase C materialises the mutant
by applying the described transformation to the base scenario's user
goal, then checks the invariant across the paired executions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List

from src.oracles.models import MetamorphicRelation

if TYPE_CHECKING:  # avoid circular import: scenarios.models imports oracles.models
    from src.scenarios.models import Scenario


def _language_signals(agent_map: dict) -> dict:
    """Extract the language metadata Phase A emits (Sprint 9 shape)."""
    metadata = agent_map.get("metadata") or {}
    lang_meta = metadata.get("language") or {}
    if not isinstance(lang_meta, dict):
        # Older maps carry a plain string here (e.g. programming language)
        lang_meta = {}
    guardrails = agent_map.get("guardrails") or {}
    return {
        "primary_language": (
            lang_meta.get("primary_language")
            or metadata.get("conversation_language")
            or "English"
        ),
        "code_switching_detected": bool(lang_meta.get("code_switching_detected", False)),
        "spanish_formality": lang_meta.get("spanish_formality"),
        "guardrail_language_matches_conversation": guardrails.get(
            "guardrail_language_matches_conversation", True
        ),
    }


def generate_metamorphic_relations(
    scenarios: List[Scenario],
    agent_map: dict,
) -> List[MetamorphicRelation]:
    """Generate metamorphic relations for a scenario catalog.

    - Language invariance: gated on guardrail/conversation language
      mismatch or detected code switching.
    - Formality invariance (usted vs tú): gated on detected Spanish
      formality.
    - Synonym invariance: always applicable (base scenarios only, to
      avoid combinatorial blow-up across variants).
    - Ordering invariance: base scenarios whose task involves more than
      one required tool (information can arrive in different orders).
    """
    signals = _language_signals(agent_map)
    relations: List[MetamorphicRelation] = []

    language_applicable = (
        not signals["guardrail_language_matches_conversation"]
        or signals["code_switching_detected"]
    )
    formality_applicable = signals["spanish_formality"] is not None
    primary = signals["primary_language"]
    other = "Spanish" if primary == "English" else "English"

    for scenario in scenarios:
        sid = scenario.scenario_id
        is_base = scenario.base_scenario_id is None

        if language_applicable:
            relations.append(MetamorphicRelation(
                relation_id=f"mr-lang-{sid}",
                description=(
                    f"Language invariance: '{scenario.title}' expressed in "
                    f"{primary} vs {other} must invoke the same tools and "
                    f"produce the same policy outcome"
                ),
                base_scenario_id=sid,
                mutant_scenario_id=f"{sid}::language_invariance",
                invariant="tool_calls_equal",
                source="language_invariance",
            ))

        if formality_applicable:
            relations.append(MetamorphicRelation(
                relation_id=f"mr-form-{sid}",
                description=(
                    f"Formality invariance: '{scenario.title}' phrased with "
                    f"usted vs tú must invoke the same tools and produce the "
                    f"same policy outcome"
                ),
                base_scenario_id=sid,
                mutant_scenario_id=f"{sid}::formality_invariance",
                invariant="tool_calls_equal",
                source="formality_invariance",
            ))

        if is_base:
            relations.append(MetamorphicRelation(
                relation_id=f"mr-syn-{sid}",
                description=(
                    f"Synonym invariance: replacing key terms of "
                    f"'{scenario.user_goal}' with synonyms must yield the "
                    f"same intent classification and tool calls"
                ),
                base_scenario_id=sid,
                mutant_scenario_id=f"{sid}::synonym_invariance",
                invariant="tool_calls_equal",
                source="synonym_invariance",
            ))

            if len(scenario.required_tools) > 1:
                relations.append(MetamorphicRelation(
                    relation_id=f"mr-ord-{sid}",
                    description=(
                        f"Ordering invariance: providing the information for "
                        f"'{scenario.title}' in a different order must reach "
                        f"the same final outcome"
                    ),
                    base_scenario_id=sid,
                    mutant_scenario_id=f"{sid}::ordering_invariance",
                    invariant="policy_outcome_equal",
                    source="ordering_invariance",
                ))

    return relations
