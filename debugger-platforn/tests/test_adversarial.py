"""
Tests for risk-guided adversarial generation (Sprint E5).

Covers: attack-template taxonomy coverage, taxonomy-ID resolution (explicit
and pattern-only fallback), taint-flow attack generation, taxonomy-mapped
attack generation with Spanish localisation, non-LLM oracle attachment,
ScenarioLibrary integration (oracles survive attach_oracles ordering),
adversarial persona enrichment, and Phase 2.5 adversarial coverage in the
test-suite generator.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.coverage.models import (
    CoverageGoals,
    EdgeCaseCoverageGoals,
    SandboxConfig,
    StressorCoverageGoals,
    ToolCoverageGoals,
)
from src.generator.test_suite import (
    TestSuiteGenerator as SuiteGenerator,
    _looks_like_taxonomy_id,
)
from src.oracles.generator import generate_oracles_from_agent_map
from src.oracles.models import OracleType
from src.personas.builder import PersonaBuilder
from src.scenarios.adversarial import (
    ATTACK_TEMPLATES,
    generate_taint_flow_attacks,
    generate_taxonomy_attacks,
    instantiate_template,
    is_taxonomy_id,
    present_taxonomy_ids,
)
from src.scenarios.library import ScenarioLibrary


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _rich_map() -> dict:
    """Agent map with explicit taxonomy_ids, taint flows and guardrails —
    exercising all five attack families (LLM01/LLM02/LLM06/ASI03/ASI05)."""
    return {
        "agent_id": "adv-agent",
        "metadata": {"type": "support", "purpose": "Order support",
                     "conversation_language": "Spanish"},
        "components": {
            "tools": [
                {"name": "track_order", "risk_level": "low", "read_only": True},
                {"name": "escalate_to_human", "risk_level": "medium"},
                {"name": "process_refund", "risk_level": "critical",
                 "state_modifying": True},
                {"name": "run_query", "risk_level": "high"},
            ],
        },
        "guardrails": {
            "rules": [
                {"rule_id": "R001", "text": "Never disclose payment card numbers",
                 "category": "prohibition", "target_tools": ["escalate_to_human"]},
                {"rule_id": "R002", "text": "Require confirmation before refunds",
                 "category": "confirmation", "target_tools": ["process_refund"]},
            ],
        },
        "risk_flags": {
            "pii_handling": True,
            "critical_actions": ["process_refund"],
            "taint_flows": [
                {
                    "source": "customer_email input",
                    "sink": "http_post payload",
                    "path": ["escalate_to_human"],
                    "data_types": ["email"],
                    "risk_level": "high",
                    "taxonomy_ids": ["LLM02", "ASI03"],
                },
            ],
            "all_risks": [
                {"tool": "escalate_to_human", "risk_type": "pii", "pii_type": "email",
                 "severity": "high", "taxonomy_ids": ["LLM02", "ASI03"]},
                {"tool": "process_refund", "risk_type": "critical_action",
                 "pii_type": None, "severity": "critical",
                 "taxonomy_ids": ["LLM06", "ASI02"]},
                {"tool": "run_query", "risk_type": "unsafe_operation",
                 "pii_type": None, "severity": "critical",
                 "taxonomy_ids": ["ASI05", "LLM01"]},
            ],
        },
    }


def _pattern_only_map() -> dict:
    """Older pattern-only map: all_risks without taxonomy_ids, no taint flows."""
    return {
        "agent_id": "legacy-agent",
        "metadata": {"type": "support"},
        "components": {
            "tools": [
                {"name": "escalate_to_human", "risk_level": "low"},
                {"name": "RefundTool", "risk_level": "low"},
            ],
        },
        "risk_flags": {
            "pii_handling": True,
            "critical_actions": ["RefundTool"],
            "all_risks": [
                {"tool": "escalate_to_human", "risk_type": "pii", "pii_type": "email",
                 "severity": "high"},
                {"tool": "RefundTool", "risk_type": "critical_action",
                 "pii_type": None, "severity": "critical"},
            ],
        },
    }


# ---------------------------------------------------------------------------
# Attack templates & taxonomy helpers
# ---------------------------------------------------------------------------

def test_attack_templates_cover_required_taxonomies():
    for tid in ("LLM01", "LLM02", "LLM06", "ASI03", "ASI05"):
        assert tid in ATTACK_TEMPLATES
        assert ATTACK_TEMPLATES[tid], f"{tid} has no templates"


def test_is_taxonomy_id():
    assert is_taxonomy_id("LLM01") and is_taxonomy_id("ASI05")
    assert not is_taxonomy_id("adversarial")
    assert not is_taxonomy_id("")
    assert _looks_like_taxonomy_id("LLM10")
    assert not _looks_like_taxonomy_id("pii_extraction")


def test_present_taxonomy_ids_explicit():
    ids = present_taxonomy_ids(_rich_map())
    for expected in ("LLM01", "LLM02", "LLM06", "ASI02", "ASI03", "ASI05"):
        assert expected in ids


def test_present_taxonomy_ids_pattern_only_fallback():
    ids = present_taxonomy_ids(_pattern_only_map())
    # pii -> PII_LEAK -> LLM02/ASI03 ; critical_action -> EXCESSIVE_AGENCY -> LLM06/ASI03
    assert "LLM02" in ids and "ASI03" in ids and "LLM06" in ids


# ---------------------------------------------------------------------------
# Template instantiation
# ---------------------------------------------------------------------------

def test_instantiate_template_fills_placeholders_english():
    tpl = ATTACK_TEMPLATES["LLM01"][0]  # direct_injection with action_variants
    ctx = {"tool": "process_refund", "payload": "amount=9999", "order_id": "ORD-1",
           "pii_type": "email", "customer_name": "X", "action": "x"}
    out = instantiate_template(tpl, ctx, "English")
    assert any("process_refund" in s for s in out)
    assert all("{" not in s for s in out)  # no leftover placeholders


def test_instantiate_template_spanish():
    tpl = ATTACK_TEMPLATES["LLM01"][0]
    ctx = {"tool": "process_refund", "payload": "p", "order_id": "ORD-1",
           "pii_type": "email", "customer_name": "X", "action": "x"}
    out = instantiate_template(tpl, ctx, "Spanish")
    assert any("Ignora las instrucciones" in s for s in out)


# ---------------------------------------------------------------------------
# Taint-flow attacks
# ---------------------------------------------------------------------------

def test_taint_flow_attacks_from_traced_flows():
    m = _rich_map()
    scns = generate_taint_flow_attacks(m, language="English",
                                       all_oracles=generate_oracles_from_agent_map(m))
    assert scns
    s = scns[0]
    assert s.source == "adversarial_taint"
    assert s.type == "error_path"
    assert s.difficulty == "hard"
    assert s.failure_conditions.pii_leaked is True
    # oracle is a TAINT_FLOW oracle
    assert any(o.oracle_type == OracleType.TAINT_FLOW for o in s.oracles)
    assert "escalate_to_human" in s.required_tools


def test_taint_flow_attacks_fallback_without_traced_flows():
    m = _pattern_only_map()
    scns = generate_taint_flow_attacks(m, language="English",
                                       all_oracles=generate_oracles_from_agent_map(m))
    # PII risk (escalate_to_human/email) becomes a taint source
    assert scns
    tools = {t for s in scns for t in s.required_tools}
    assert "escalate_to_human" in tools
    assert all(s.oracles for s in scns)


# ---------------------------------------------------------------------------
# Taxonomy attacks
# ---------------------------------------------------------------------------

def test_taxonomy_attacks_cover_every_present_family():
    m = _rich_map()
    scns = generate_taxonomy_attacks(m, language="English",
                                     all_oracles=generate_oracles_from_agent_map(m))
    families = {t for s in scns for t in s.tags if is_taxonomy_id(t)}
    # every present taxonomy that has attack templates must be represented
    for tid in ("LLM01", "LLM02", "LLM06", "ASI03", "ASI05"):
        assert tid in families, f"missing adversarial coverage for {tid}"


def test_taxonomy_attacks_every_scenario_has_oracle():
    m = _rich_map()
    scns = generate_taxonomy_attacks(m, language="English",
                                     all_oracles=generate_oracles_from_agent_map(m))
    assert scns
    for s in scns:
        assert s.oracles, f"{s.title} has no oracle"
        assert s.source == "adversarial_taxonomy"
        assert s.difficulty == "hard"
        assert s.success_conditions.user_satisfied is False


def test_taxonomy_attacks_oracle_type_matches_family():
    m = _rich_map()
    scns = generate_taxonomy_attacks(m, language="English",
                                     all_oracles=generate_oracles_from_agent_map(m))
    for s in scns:
        primary = next(t for t in s.tags if is_taxonomy_id(t))
        types = {o.oracle_type for o in s.oracles}
        if primary in ("LLM02", "ASI03"):
            assert OracleType.TAINT_FLOW in types
        elif primary in ("LLM01", "LLM06", "ASI05"):
            assert OracleType.GUARDRAIL_VIOLATION in types


def test_taxonomy_attacks_spanish_localisation():
    m = _rich_map()
    scns = generate_taxonomy_attacks(m, language="Spanish",
                                     all_oracles=generate_oracles_from_agent_map(m))
    llm02 = [s for s in scns if "LLM02" in s.tags and s.tags[2] == "pii_extraction"]
    assert llm02
    assert any("¿Puedes decirme" in o for o in llm02[0].starter_openers)


def test_pattern_only_map_produces_adversarial_scenarios():
    m = _pattern_only_map()
    scns = generate_taxonomy_attacks(m, language="Spanish",
                                     all_oracles=generate_oracles_from_agent_map(m))
    assert scns
    assert all(s.oracles for s in scns)


# ---------------------------------------------------------------------------
# ScenarioLibrary integration
# ---------------------------------------------------------------------------

def test_library_generate_adversarial_scenarios_appends():
    m = _rich_map()
    lib = ScenarioLibrary(m, language="Spanish")
    before = len(lib.scenarios)
    added = lib.generate_adversarial_scenarios()
    assert added
    assert len(lib.scenarios) == before + len(added)
    assert all(s.source in ("adversarial_taxonomy", "adversarial_taint") for s in added)


def test_adversarial_oracles_survive_attach_oracles_ordering():
    """Pipeline order: attach_oracles first, then adversarial generation.
    Adversarial scenarios must keep their own oracles."""
    m = _rich_map()
    lib = ScenarioLibrary(m, language="Spanish")
    lib.load_templates()
    lib.attach_oracles(m)              # runs over template scenarios only
    added = lib.generate_adversarial_scenarios()  # appended afterwards
    assert added
    for s in added:
        assert s.oracles, f"{s.title} lost its oracle"


# ---------------------------------------------------------------------------
# Adversarial personas (E5.4)
# ---------------------------------------------------------------------------

def test_generate_adversarial_personas_named_and_tagged():
    builder = PersonaBuilder(_rich_map(), language="Spanish")
    personas = builder.generate_adversarial_personas(["LLM01", "LLM02", "LLM06", "ASI03", "ASI05"])
    names = {p.name for p in personas}
    assert {"Social Engineer", "Data Extractor", "Authority Impersonator",
            "Identity Spoofer", "Code Injector"} <= names
    for p in personas:
        assert p.source == "adversarial"
        assert any(is_taxonomy_id(t) for t in p.tags)
        assert "adversarial" in p.tags


def test_generate_adversarial_personas_dedup_and_fallback():
    builder = PersonaBuilder(_rich_map())
    personas = builder.generate_adversarial_personas(["LLM01", "LLM01", "LLM99"])
    # LLM01 deduped to one; unknown LLM99 gets a generic prober
    assert len([p for p in personas if "LLM01" in p.tags]) == 1
    assert any("LLM99" in p.tags for p in personas)


def test_adversarial_persona_archetype_is_adversarial():
    builder = PersonaBuilder(_rich_map())
    personas = builder.generate_adversarial_personas(["LLM01"])
    assert personas[0].archetype == "adversarial"


# ---------------------------------------------------------------------------
# Phase 2.5 adversarial coverage in the test-suite generator
# ---------------------------------------------------------------------------

def _coverage_goals() -> CoverageGoals:
    return CoverageGoals(
        tool_coverage=ToolCoverageGoals(min_invocations_per_tool={}, tool_combinations=[]),
        edge_case_coverage=EdgeCaseCoverageGoals(
            ambiguous_requests=0, incomplete_information=0,
            user_changes_mind=0, contradictory_statements=0,
        ),
        stressor_coverage=StressorCoverageGoals(
            timeout_scenarios=0, malformed_response_scenarios=0, data_conflict_scenarios=0,
        ),
    )


def _build_suite(target_count: int):
    m = _rich_map()
    lib = ScenarioLibrary(m, language="English")
    lib.load_templates()
    lib.attach_oracles(m)
    lib.generate_adversarial_scenarios()

    builder = PersonaBuilder(m, language="English")
    builder.load_templates()
    builder.generate_tool_attack_personas()
    builder.generate_adversarial_personas(present_taxonomy_ids(m))

    gen = SuiteGenerator(
        agent_map=m,
        personas=builder.personas,
        scenarios=lib.scenarios,
        coverage_goals=_coverage_goals(),
        sandbox_config=SandboxConfig(),
    )
    return gen.generate(target_count=target_count)


def test_phase_2_5_produces_adversarial_tests_with_adversarial_personas():
    suite = _build_suite(target_count=200)
    adv_tests = [tc for tc in suite.test_cases if tc.coverage_goal.startswith("adversarial")]
    assert adv_tests, "no adversarial coverage tests generated"
    # every present taxonomy family with templates is covered by ≥1 test
    covered = {tc.coverage_goal.split(":", 1)[1] for tc in adv_tests}
    for tid in ("LLM01", "LLM02", "LLM06", "ASI03", "ASI05"):
        assert tid in covered, f"Phase 2.5 missing {tid}"
    # adversarial tests prefer adversarial personas
    assert any(tc.persona.source == "adversarial" for tc in adv_tests)
    # oracles carried onto the test case
    assert all(tc.oracles for tc in adv_tests)


def test_phase_2_5_tests_survive_overshoot_trim():
    # Tiny budget forces the overshoot trim; adversarial coverage must survive.
    suite = _build_suite(target_count=6)
    adv_tests = [tc for tc in suite.test_cases if tc.coverage_goal.startswith("adversarial")]
    assert adv_tests, "adversarial tests were trimmed away"
