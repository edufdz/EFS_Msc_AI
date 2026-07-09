"""
Tests for Production-Grounded Personas (Sprint E6).

Covers: the trace-to-trait analyser (per-trait distribution statistics and
style distributions), distribution fitting (mean/std + dominant language),
truncated-normal persona sampling (population match, determinism, cultural
names), the PersonaBuilder integration, and the generate_tests.py CLI wiring
(offline, graceful degradation).
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.personas.builder import PersonaBuilder
from src.personas.models import Persona
from src.personas.trace_grounding import (
    TRAIT_NAMES,
    PRODUCTION_SOURCE,
    analyse_user_traits,
    fit_trait_distributions,
    sample_production_personas,
)


# ---------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------

def _spanish_conversations() -> list:
    """Mexican-Spanish support conversations (TechRepair-style)."""
    return [
        {
            "trace_id": "t1",
            "outcome": "escalation",
            "messages": [
                {"role": "user", "content": "Buenos días, necesito ayuda con mi pedido por favor"},
                {"role": "assistant", "content": "Claro, con gusto"},
                {"role": "user", "content": "Muchas gracias, usted es muy amable"},
            ],
        },
        {
            "trace_id": "t2",
            "outcome": "success",
            "messages": [
                {"role": "user", "content": "hola necesito el codigo de mi pedido"},
                {"role": "user", "content": "gracias"},
            ],
        },
        {
            "trace_id": "t3",
            "outcome": "complaint",
            "messages": [
                {"role": "user", "content": "ESTO ES INUTIL!!! llevo horas esperando, PESIMO servicio"},
            ],
        },
        {
            "trace_id": "t4",
            "outcome": "success",
            "messages": [
                {"role": "user", "content": "Estimado, quisiera consultar el estado de mi pedido numero ABC123456, se lo agradezco mucho"},
                {"role": "assistant", "content": "Con gusto"},
                {"role": "user", "content": "Perfecto, muchas gracias por su atencion"},
            ],
        },
    ]


def _agent_map() -> dict:
    return {
        "agent_id": "tech_repair_wa",
        "metadata": {"type": "support", "purpose": "TechRepair support", "conversation_language": "Spanish"},
        "components": {"tools": [{"name": "get_order_status", "risk_level": "low"}]},
    }


# ---------------------------------------------------------------
# E6.1 — analyse_user_traits
# ---------------------------------------------------------------

def test_analyse_returns_all_ten_trait_distributions():
    result = analyse_user_traits(_spanish_conversations())
    assert result["n_conversations"] == 4
    for name in TRAIT_NAMES:
        stats = result["traits"][name]
        assert set(stats) >= {"mean", "std", "p25", "p50", "p75", "min", "max"}
        assert 1.0 <= stats["mean"] <= 10.0
        assert stats["std"] >= 0.0
        assert stats["min"] <= stats["p50"] <= stats["max"]


def test_analyse_style_distributions_present():
    style = analyse_user_traits(_spanish_conversations())["style"]
    assert style["formality"]  # non-empty distribution
    assert abs(sum(style["formality"].values()) - 1.0) < 1e-6
    assert "Spanish" in style["language"]
    assert 0.0 <= style["typo_rate_mean"] <= 1.0


def test_analyse_skips_conversations_without_user_text():
    convs = [
        {"trace_id": "empty", "messages": [{"role": "assistant", "content": "hi"}]},
        {"trace_id": "real", "messages": [{"role": "user", "content": "hola necesito ayuda"}]},
    ]
    assert analyse_user_traits(convs)["n_conversations"] == 1


def test_analyse_empty_is_graceful():
    result = analyse_user_traits([])
    assert result["n_conversations"] == 0
    for name in TRAIT_NAMES:
        assert result["traits"][name]["std"] == 0.0


def test_rude_conversation_lowers_politeness_signal():
    calm = analyse_user_traits([{"messages": [{"role": "user", "content": "gracias, muy amable, por favor"}]}])
    rude = analyse_user_traits([{"messages": [{"role": "user", "content": "esto es inutil y pesimo, terrible"}]}])
    assert rude["traits"]["politeness"]["mean"] < calm["traits"]["politeness"]["mean"]


def test_accepts_bare_list_of_turns():
    conv = [{"role": "user", "content": "hola necesito ayuda con mi pedido por favor"}]
    result = analyse_user_traits([conv])
    assert result["n_conversations"] == 1


# ---------------------------------------------------------------
# E6.1 — fit_trait_distributions
# ---------------------------------------------------------------

def test_fit_returns_mean_std_tuples_for_all_traits():
    fitted = fit_trait_distributions(_spanish_conversations())
    assert set(fitted["traits"]) == set(TRAIT_NAMES)
    for name in TRAIT_NAMES:
        mean, std = fitted["traits"][name]
        assert isinstance(mean, float) and isinstance(std, float)
        assert 1.0 <= mean <= 10.0
        assert std >= 0.0


def test_fit_dominant_language_spanish():
    fitted = fit_trait_distributions(_spanish_conversations())
    assert fitted["dominant_language"] == "Spanish"
    assert fitted["n_conversations"] == 4


# ---------------------------------------------------------------
# E6.2 — sample_production_personas
# ---------------------------------------------------------------

def test_sample_count_and_source():
    fitted = fit_trait_distributions(_spanish_conversations())
    personas = sample_production_personas(fitted, count=5)
    assert len(personas) == 5
    assert all(isinstance(p, Persona) for p in personas)
    assert all(p.source == PRODUCTION_SOURCE for p in personas)
    assert all("production_grounded" in p.tags for p in personas)


def test_sample_is_deterministic():
    fitted = fit_trait_distributions(_spanish_conversations())
    a = sample_production_personas(fitted, count=6, seed=7)
    b = sample_production_personas(fitted, count=6, seed=7)
    assert [p.name for p in a] == [p.name for p in b]
    assert [p.traits.model_dump() for p in a] == [p.traits.model_dump() for p in b]
    # A different seed should (very likely) differ
    c = sample_production_personas(fitted, count=6, seed=999)
    assert [p.traits.model_dump() for p in a] != [p.traits.model_dump() for p in c]


def test_sampled_traits_within_bounds():
    fitted = fit_trait_distributions(_spanish_conversations())
    for p in sample_production_personas(fitted, count=20):
        for name in TRAIT_NAMES:
            v = getattr(p.traits, name)
            assert 1 <= v <= 10
        assert 0.0 <= p.style.typo_rate <= 1.0


def test_sampled_population_matches_distribution_mean():
    """Sampled trait means should track the fitted means (population match)."""
    fitted = fit_trait_distributions(_spanish_conversations())
    personas = sample_production_personas(fitted, count=400, seed=1)
    for name in TRAIT_NAMES:
        fit_mean, fit_std = fitted["traits"][name]
        sampled_mean = sum(getattr(p.traits, name) for p in personas) / len(personas)
        # Within ~1.5 std (clipping/rounding pull toward the mean) or 1.0 abs
        tol = max(1.0, 1.5 * fit_std)
        assert abs(sampled_mean - fit_mean) <= tol, (name, sampled_mean, fit_mean)


def test_spanish_traces_yield_mexican_names():
    fitted = fit_trait_distributions(_spanish_conversations())
    personas = sample_production_personas(fitted, count=5)
    from src.personas.trace_grounding import _MX_SPANISH_NAMES
    assert all(p.name in _MX_SPANISH_NAMES for p in personas)


def test_sample_zero_count():
    fitted = fit_trait_distributions(_spanish_conversations())
    assert sample_production_personas(fitted, count=0) == []


def test_sample_tolerates_bare_trait_mapping():
    """sample should also accept a plain {trait: (mean, std)} mapping."""
    bare = {name: (5.0, 1.0) for name in TRAIT_NAMES}
    personas = sample_production_personas(bare, count=3)
    assert len(personas) == 3


# ---------------------------------------------------------------
# E6.3 — PersonaBuilder integration
# ---------------------------------------------------------------

def test_builder_generate_production_grounded():
    builder = PersonaBuilder(_agent_map(), language="Spanish")
    trace_result = {"conversations": _spanish_conversations()}
    personas = builder.generate_production_grounded_personas(trace_result, count=5)
    assert len(personas) == 5
    assert all(p.source == PRODUCTION_SOURCE for p in personas)
    assert all(p.agent_type == "support" for p in personas)
    # Added to the library
    assert all(p in builder.personas for p in personas)


def test_builder_graceful_without_conversations():
    builder = PersonaBuilder(_agent_map())
    assert builder.generate_production_grounded_personas({"conversations": []}, count=5) == []
    assert builder.generate_production_grounded_personas(None, count=5) == []


def test_builder_accepts_object_trace_result():
    class _TR:
        conversations = _spanish_conversations()

    builder = PersonaBuilder(_agent_map())
    personas = builder.generate_production_grounded_personas(_TR(), count=3)
    assert len(personas) == 3


# ---------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------

def test_cli_wiring_offline(tmp_path):
    """generate_tests.py should run with --use-traces and a traces file, adding
    production-grounded personas, fully offline."""
    import json
    from click.testing import CliRunner
    from generate_tests import main

    agent_map = _agent_map()
    map_path = tmp_path / "map.json"
    map_path.write_text(json.dumps(agent_map))

    traces_path = tmp_path / "traces.json"
    traces_path.write_text(json.dumps({"conversations": _spanish_conversations()}))

    out_dir = tmp_path / "out"
    runner = CliRunner()
    result = runner.invoke(main, [
        str(map_path), "--skip-ai", "--include-templates",
        "--use-traces", "--traces-file", str(traces_path),
        "-o", str(out_dir),
    ])
    assert result.exit_code == 0, result.output

    library = json.loads((out_dir / "persona_library.json").read_text())
    sources = {p["source"] for p in library["personas"]}
    assert PRODUCTION_SOURCE in sources
