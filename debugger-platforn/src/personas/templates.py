"""
Pre-built persona templates organized by agent domain.
Each template provides default traits, style, and edge behaviors.
"""

from __future__ import annotations

from typing import Dict, List

PERSONA_TEMPLATES: Dict[str, List[Dict]] = {
    "support": [
        {
            "name": "Karen Mitchell",
            "traits": {
                "patience": 2, "clarity": 4, "tech_savviness": 3,
                "politeness": 3, "verbosity": 5,
                "emotional_volatility": 8, "trust_level": 3,
                "detail_orientation": 4, "decision_speed": 7,
                "language_proficiency": 7,
            },
            "style": {
                "tone": "frustrated", "formality": "casual",
                "typo_rate": 0.15, "abbreviation_use": "high", "emoji_use": "rare",
            },
            "edge_behaviors": {
                "rage_quits": True, "changes_mind": False,
                "provides_incomplete_info": False, "asks_off_topic": False,
                "tests_boundaries": False,
            },
        },
        {
            "name": "Tommy Brennan",
            "traits": {
                "patience": 6, "clarity": 3, "tech_savviness": 2,
                "politeness": 8, "verbosity": 8,
                "emotional_volatility": 4, "trust_level": 7,
                "detail_orientation": 3, "decision_speed": 3,
                "language_proficiency": 8,
            },
            "style": {
                "tone": "neutral", "formality": "casual",
                "typo_rate": 0.10, "abbreviation_use": "low", "emoji_use": "rare",
            },
            "edge_behaviors": {
                "rage_quits": False, "changes_mind": False,
                "provides_incomplete_info": True, "asks_off_topic": False,
                "tests_boundaries": False,
            },
        },
        {
            "name": "Derek Lawson",
            "traits": {
                "patience": 7, "clarity": 9, "tech_savviness": 9,
                "politeness": 6, "verbosity": 5,
                "emotional_volatility": 3, "trust_level": 4,
                "detail_orientation": 8, "decision_speed": 7,
                "language_proficiency": 9,
            },
            "style": {
                "tone": "neutral", "formality": "formal",
                "typo_rate": 0.02, "abbreviation_use": "low", "emoji_use": "none",
            },
            "edge_behaviors": {
                "rage_quits": False, "changes_mind": False,
                "provides_incomplete_info": False, "asks_off_topic": False,
                "tests_boundaries": True,
            },
        },
        {
            "name": "Victor Ramos",
            "traits": {
                "patience": 1, "clarity": 6, "tech_savviness": 5,
                "politeness": 1, "verbosity": 7,
                "emotional_volatility": 10, "trust_level": 2,
                "detail_orientation": 5, "decision_speed": 8,
                "language_proficiency": 7,
            },
            "style": {
                "tone": "angry", "formality": "casual",
                "typo_rate": 0.20, "abbreviation_use": "medium", "emoji_use": "none",
            },
            "edge_behaviors": {
                "rage_quits": True, "changes_mind": False,
                "provides_incomplete_info": False, "asks_off_topic": True,
                "tests_boundaries": True,
            },
        },
        {
            "name": "Margaret Sullivan",
            "traits": {
                "patience": 9, "clarity": 5, "tech_savviness": 2,
                "politeness": 10, "verbosity": 9,
                "emotional_volatility": 2, "trust_level": 8,
                "detail_orientation": 4, "decision_speed": 3,
                "language_proficiency": 9,
            },
            "style": {
                "tone": "polite", "formality": "formal",
                "typo_rate": 0.08, "abbreviation_use": "low", "emoji_use": "none",
            },
            "edge_behaviors": {
                "rage_quits": False, "changes_mind": False,
                "provides_incomplete_info": True, "asks_off_topic": True,
                "tests_boundaries": False,
            },
        },
        # ── New support personas ──
        {
            "name": "Hiroshi Tanaka",
            "traits": {
                "patience": 7, "clarity": 4, "tech_savviness": 5,
                "politeness": 7, "verbosity": 6,
                "emotional_volatility": 5, "trust_level": 6,
                "detail_orientation": 5, "decision_speed": 4,
                "language_proficiency": 3,
            },
            "style": {
                "tone": "neutral", "formality": "casual",
                "typo_rate": 0.18, "abbreviation_use": "low", "emoji_use": "rare",
            },
            "edge_behaviors": {
                "rage_quits": False, "changes_mind": False,
                "provides_incomplete_info": True, "asks_off_topic": False,
                "tests_boundaries": False,
            },
        },
        {
            "name": "Sarah Winters",
            "traits": {
                "patience": 7, "clarity": 7, "tech_savviness": 6,
                "politeness": 8, "verbosity": 7,
                "emotional_volatility": 4, "trust_level": 5,
                "detail_orientation": 8, "decision_speed": 5,
                "language_proficiency": 9,
            },
            "style": {
                "tone": "polite", "formality": "formal",
                "typo_rate": 0.05, "abbreviation_use": "low", "emoji_use": "none",
            },
            "edge_behaviors": {
                "rage_quits": False, "changes_mind": False,
                "provides_incomplete_info": False, "asks_off_topic": False,
                "tests_boundaries": True,
            },
        },
        {
            "name": "Lisa Huang",
            "traits": {
                "patience": 4, "clarity": 5, "tech_savviness": 5,
                "politeness": 6, "verbosity": 4,
                "emotional_volatility": 6, "trust_level": 5,
                "detail_orientation": 4, "decision_speed": 8,
                "language_proficiency": 8,
            },
            "style": {
                "tone": "neutral", "formality": "casual",
                "typo_rate": 0.12, "abbreviation_use": "high", "emoji_use": "moderate",
            },
            "edge_behaviors": {
                "rage_quits": False, "changes_mind": True,
                "provides_incomplete_info": True, "asks_off_topic": True,
                "tests_boundaries": False,
            },
        },
    ],

    "sales": [
        {
            "name": "Nina Petrov",
            "traits": {
                "patience": 8, "clarity": 7, "tech_savviness": 6,
                "politeness": 7, "verbosity": 4,
                "emotional_volatility": 3, "trust_level": 4,
                "detail_orientation": 8, "decision_speed": 3,
                "language_proficiency": 8,
            },
            "style": {
                "tone": "neutral", "formality": "casual",
                "typo_rate": 0.05, "abbreviation_use": "low", "emoji_use": "none",
            },
            "edge_behaviors": {
                "rage_quits": False, "changes_mind": True,
                "provides_incomplete_info": False, "asks_off_topic": False,
                "tests_boundaries": False,
            },
        },
        {
            "name": "Jake Morrison",
            "traits": {
                "patience": 3, "clarity": 5, "tech_savviness": 4,
                "politeness": 5, "verbosity": 3,
                "emotional_volatility": 7, "trust_level": 7,
                "detail_orientation": 2, "decision_speed": 10,
                "language_proficiency": 7,
            },
            "style": {
                "tone": "neutral", "formality": "casual",
                "typo_rate": 0.12, "abbreviation_use": "high", "emoji_use": "moderate",
            },
            "edge_behaviors": {
                "rage_quits": False, "changes_mind": False,
                "provides_incomplete_info": True, "asks_off_topic": False,
                "tests_boundaries": False,
            },
        },
        {
            "name": "Richard Okonkwo",
            "traits": {
                "patience": 6, "clarity": 8, "tech_savviness": 8,
                "politeness": 5, "verbosity": 6,
                "emotional_volatility": 3, "trust_level": 2,
                "detail_orientation": 9, "decision_speed": 4,
                "language_proficiency": 9,
            },
            "style": {
                "tone": "neutral", "formality": "formal",
                "typo_rate": 0.02, "abbreviation_use": "low", "emoji_use": "none",
            },
            "edge_behaviors": {
                "rage_quits": False, "changes_mind": True,
                "provides_incomplete_info": False, "asks_off_topic": False,
                "tests_boundaries": True,
            },
        },
        # ── New sales personas ──
        {
            "name": "Patricia Vega",
            "traits": {
                "patience": 7, "clarity": 7, "tech_savviness": 5,
                "politeness": 8, "verbosity": 5,
                "emotional_volatility": 3, "trust_level": 8,
                "detail_orientation": 6, "decision_speed": 6,
                "language_proficiency": 8,
            },
            "style": {
                "tone": "polite", "formality": "casual",
                "typo_rate": 0.04, "abbreviation_use": "low", "emoji_use": "rare",
            },
            "edge_behaviors": {
                "rage_quits": False, "changes_mind": False,
                "provides_incomplete_info": False, "asks_off_topic": False,
                "tests_boundaries": True,
            },
        },
        {
            "name": "Angela Dubois",
            "traits": {
                "patience": 5, "clarity": 8, "tech_savviness": 7,
                "politeness": 5, "verbosity": 7,
                "emotional_volatility": 4, "trust_level": 3,
                "detail_orientation": 9, "decision_speed": 2,
                "language_proficiency": 9,
            },
            "style": {
                "tone": "neutral", "formality": "formal",
                "typo_rate": 0.02, "abbreviation_use": "low", "emoji_use": "none",
            },
            "edge_behaviors": {
                "rage_quits": False, "changes_mind": True,
                "provides_incomplete_info": False, "asks_off_topic": True,
                "tests_boundaries": False,
            },
        },
    ],

    "scheduling": [
        {
            "name": "Diego Navarro",
            "traits": {
                "patience": 3, "clarity": 5, "tech_savviness": 5,
                "politeness": 4, "verbosity": 4,
                "emotional_volatility": 7, "trust_level": 5,
                "detail_orientation": 3, "decision_speed": 9,
                "language_proficiency": 7,
            },
            "style": {
                "tone": "frustrated", "formality": "casual",
                "typo_rate": 0.15, "abbreviation_use": "high", "emoji_use": "moderate",
            },
            "edge_behaviors": {
                "rage_quits": True, "changes_mind": True,
                "provides_incomplete_info": False, "asks_off_topic": False,
                "tests_boundaries": False,
            },
        },
        {
            "name": "Helen Crawford",
            "traits": {
                "patience": 9, "clarity": 8, "tech_savviness": 6,
                "politeness": 8, "verbosity": 8,
                "emotional_volatility": 2, "trust_level": 6,
                "detail_orientation": 10, "decision_speed": 2,
                "language_proficiency": 9,
            },
            "style": {
                "tone": "polite", "formality": "formal",
                "typo_rate": 0.03, "abbreviation_use": "low", "emoji_use": "none",
            },
            "edge_behaviors": {
                "rage_quits": False, "changes_mind": True,
                "provides_incomplete_info": False, "asks_off_topic": False,
                "tests_boundaries": False,
            },
        },
        {
            "name": "Omar Siddiqui",
            "traits": {
                "patience": 5, "clarity": 6, "tech_savviness": 5,
                "politeness": 7, "verbosity": 7,
                "emotional_volatility": 5, "trust_level": 6,
                "detail_orientation": 6, "decision_speed": 4,
                "language_proficiency": 8,
            },
            "style": {
                "tone": "neutral", "formality": "casual",
                "typo_rate": 0.08, "abbreviation_use": "medium", "emoji_use": "rare",
            },
            "edge_behaviors": {
                "rage_quits": False, "changes_mind": True,
                "provides_incomplete_info": True, "asks_off_topic": True,
                "tests_boundaries": False,
            },
        },
        # ── New scheduling personas ──
        {
            "name": "Yuki Abe",
            "traits": {
                "patience": 6, "clarity": 3, "tech_savviness": 4,
                "politeness": 6, "verbosity": 6,
                "emotional_volatility": 6, "trust_level": 5,
                "detail_orientation": 4, "decision_speed": 5,
                "language_proficiency": 6,
            },
            "style": {
                "tone": "neutral", "formality": "casual",
                "typo_rate": 0.10, "abbreviation_use": "medium", "emoji_use": "rare",
            },
            "edge_behaviors": {
                "rage_quits": False, "changes_mind": True,
                "provides_incomplete_info": True, "asks_off_topic": False,
                "tests_boundaries": False,
            },
        },
        {
            "name": "Tanya Brooks",
            "traits": {
                "patience": 7, "clarity": 8, "tech_savviness": 7,
                "politeness": 8, "verbosity": 3,
                "emotional_volatility": 2, "trust_level": 6,
                "detail_orientation": 8, "decision_speed": 7,
                "language_proficiency": 9,
            },
            "style": {
                "tone": "neutral", "formality": "formal",
                "typo_rate": 0.01, "abbreviation_use": "low", "emoji_use": "none",
            },
            "edge_behaviors": {
                "rage_quits": False, "changes_mind": True,
                "provides_incomplete_info": False, "asks_off_topic": False,
                "tests_boundaries": False,
            },
        },
    ],

    "research": [
        {
            "name": "Alex Romero",
            "traits": {
                "patience": 8, "clarity": 9, "tech_savviness": 8,
                "politeness": 7, "verbosity": 6,
                "emotional_volatility": 2, "trust_level": 5,
                "detail_orientation": 9, "decision_speed": 5,
                "language_proficiency": 9,
            },
            "style": {
                "tone": "neutral", "formality": "formal",
                "typo_rate": 0.02, "abbreviation_use": "low", "emoji_use": "none",
            },
            "edge_behaviors": {
                "rage_quits": False, "changes_mind": False,
                "provides_incomplete_info": False, "asks_off_topic": False,
                "tests_boundaries": True,
            },
        },
        {
            "name": "Sam Delgado",
            "traits": {
                "patience": 7, "clarity": 5, "tech_savviness": 6,
                "politeness": 7, "verbosity": 8,
                "emotional_volatility": 4, "trust_level": 6,
                "detail_orientation": 5, "decision_speed": 4,
                "language_proficiency": 8,
            },
            "style": {
                "tone": "polite", "formality": "casual",
                "typo_rate": 0.05, "abbreviation_use": "low", "emoji_use": "rare",
            },
            "edge_behaviors": {
                "rage_quits": False, "changes_mind": True,
                "provides_incomplete_info": True, "asks_off_topic": True,
                "tests_boundaries": False,
            },
        },
    ],

    "coding": [
        {
            "name": "Ethan Park",
            "traits": {
                "patience": 6, "clarity": 4, "tech_savviness": 5,
                "politeness": 7, "verbosity": 7,
                "emotional_volatility": 5, "trust_level": 7,
                "detail_orientation": 4, "decision_speed": 4,
                "language_proficiency": 7,
            },
            "style": {
                "tone": "neutral", "formality": "casual",
                "typo_rate": 0.08, "abbreviation_use": "medium", "emoji_use": "rare",
            },
            "edge_behaviors": {
                "rage_quits": False, "changes_mind": True,
                "provides_incomplete_info": True, "asks_off_topic": True,
                "tests_boundaries": False,
            },
        },
        {
            "name": "Monica Shah",
            "traits": {
                "patience": 5, "clarity": 9, "tech_savviness": 10,
                "politeness": 5, "verbosity": 3,
                "emotional_volatility": 3, "trust_level": 3,
                "detail_orientation": 9, "decision_speed": 7,
                "language_proficiency": 9,
            },
            "style": {
                "tone": "neutral", "formality": "casual",
                "typo_rate": 0.01, "abbreviation_use": "medium", "emoji_use": "none",
            },
            "edge_behaviors": {
                "rage_quits": False, "changes_mind": False,
                "provides_incomplete_info": False, "asks_off_topic": False,
                "tests_boundaries": True,
            },
        },
    ],
}

# Fallback: generic personas usable for any agent type
GENERIC_PERSONAS: List[Dict] = [
    {
        "name": "Amanda Foster",
        "traits": {
            "patience": 8, "clarity": 8, "tech_savviness": 6,
            "politeness": 8, "verbosity": 5,
            "emotional_volatility": 2, "trust_level": 8,
            "detail_orientation": 5, "decision_speed": 6,
            "language_proficiency": 9,
        },
        "style": {
            "tone": "polite", "formality": "casual",
            "typo_rate": 0.03, "abbreviation_use": "low", "emoji_use": "rare",
        },
        "edge_behaviors": {
            "rage_quits": False, "changes_mind": False,
            "provides_incomplete_info": False, "asks_off_topic": False,
            "tests_boundaries": False,
        },
    },
    {
        "name": "Leo Fernandez",
        "traits": {
            "patience": 6, "clarity": 7, "tech_savviness": 8,
            "politeness": 5, "verbosity": 5,
            "emotional_volatility": 5, "trust_level": 4,
            "detail_orientation": 7, "decision_speed": 5,
            "language_proficiency": 8,
        },
        "style": {
            "tone": "neutral", "formality": "casual",
            "typo_rate": 0.05, "abbreviation_use": "medium", "emoji_use": "none",
        },
        "edge_behaviors": {
            "rage_quits": False, "changes_mind": True,
            "provides_incomplete_info": True, "asks_off_topic": True,
            "tests_boundaries": True,
        },
    },
    {
        "name": "Ray Kowalski",
        "traits": {
            "patience": 4, "clarity": 6, "tech_savviness": 9,
            "politeness": 2, "verbosity": 4,
            "emotional_volatility": 8, "trust_level": 1,
            "detail_orientation": 7, "decision_speed": 8,
            "language_proficiency": 8,
        },
        "style": {
            "tone": "angry", "formality": "slang",
            "typo_rate": 0.10, "abbreviation_use": "high", "emoji_use": "none",
        },
        "edge_behaviors": {
            "rage_quits": True, "changes_mind": True,
            "provides_incomplete_info": True, "asks_off_topic": True,
            "tests_boundaries": True,
        },
    },
    # ── New generic personas ──
    {
        "name": "Jenny Blackwood",
        "traits": {
            "patience": 5, "clarity": 4, "tech_savviness": 5,
            "politeness": 6, "verbosity": 2,
            "emotional_volatility": 4, "trust_level": 5,
            "detail_orientation": 2, "decision_speed": 7,
            "language_proficiency": 7,
        },
        "style": {
            "tone": "neutral", "formality": "casual",
            "typo_rate": 0.15, "abbreviation_use": "high", "emoji_use": "moderate",
        },
        "edge_behaviors": {
            "rage_quits": False, "changes_mind": True,
            "provides_incomplete_info": True, "asks_off_topic": True,
            "tests_boundaries": False,
        },
    },
    {
        "name": "Arthur Lindgren",
        "traits": {
            "patience": 8, "clarity": 6, "tech_savviness": 6,
            "politeness": 7, "verbosity": 9,
            "emotional_volatility": 6, "trust_level": 4,
            "detail_orientation": 9, "decision_speed": 2,
            "language_proficiency": 8,
        },
        "style": {
            "tone": "neutral", "formality": "formal",
            "typo_rate": 0.03, "abbreviation_use": "low", "emoji_use": "none",
        },
        "edge_behaviors": {
            "rage_quits": False, "changes_mind": True,
            "provides_incomplete_info": False, "asks_off_topic": True,
            "tests_boundaries": False,
        },
    },
]


# ── Spanish translations ──────────────────────────────────────────
# Only persona names are translated; numeric traits/style/edge_behaviors stay identical.

# Real names are language-neutral — no translation needed.
# Keep the maps for backward compat but they're identity maps now.
_ES_NAME_MAP: Dict[str, str] = {}  # Names are real names, no translation


# ── Portuguese translations ──────────────────────────────────────
_PT_NAME_MAP: Dict[str, str] = {}  # Names are real names, no translation


def _translate_personas(templates: List[Dict], name_map: Dict[str, str]) -> List[Dict]:
    """Return a copy of *templates* with names translated using the given map."""
    translated = []
    for tpl in templates:
        t = dict(tpl)
        t["name"] = name_map.get(t["name"], t["name"])
        translated.append(t)
    return translated


PERSONA_TEMPLATES_ES: Dict[str, List[Dict]] = {
    domain: _translate_personas(personas, _ES_NAME_MAP)
    for domain, personas in PERSONA_TEMPLATES.items()
}

GENERIC_PERSONAS_ES: List[Dict] = _translate_personas(GENERIC_PERSONAS, _ES_NAME_MAP)

PERSONA_TEMPLATES_PT: Dict[str, List[Dict]] = {
    domain: _translate_personas(personas, _PT_NAME_MAP)
    for domain, personas in PERSONA_TEMPLATES.items()
}

GENERIC_PERSONAS_PT: List[Dict] = _translate_personas(GENERIC_PERSONAS, _PT_NAME_MAP)


def load_persona_templates(agent_type: str, language: str = "English") -> List[Dict]:
    """
    Load pre-built persona templates for an agent type.
    Falls back to generic personas if the type isn't recognised.
    When *language* is ``"Spanish"`` or ``"Portuguese"`` the translated templates are returned.
    """
    if language == "Spanish":
        templates = PERSONA_TEMPLATES_ES.get(agent_type, [])
        if not templates:
            templates = GENERIC_PERSONAS_ES
    elif language == "Portuguese":
        templates = PERSONA_TEMPLATES_PT.get(agent_type, [])
        if not templates:
            templates = GENERIC_PERSONAS_PT
    else:
        templates = PERSONA_TEMPLATES.get(agent_type, [])
        if not templates:
            templates = GENERIC_PERSONAS
    return templates
