"""
External Persona Pack Loader + HTTP Provider Client.

Supports two modes for loading external personas into the debugger:

1. ExternalPersonaLoader — reads persona/scenario JSON files from any
   directory on disk. Auto-detects whether personas are already in
   debugger format or need conversion (e.g. tlahuac format).

2. PersonaProviderClient — HTTP client for any external persona provider
   API implementing the standard contract.

Persona Pack Directory Layout
-----------------------------
A persona pack is any directory containing:
  - personas.json          (required) — persona definitions
  - scenarios.json         (optional) — test scenarios with openers
  - scenario_variants.json (optional) — scenario variants with openers

Persona format auto-detection:
  - If personas have numeric traits (patience: 8), used directly as debugger format
  - If personas have string traits (["polite", "patient"]), treated as
    tlahuac-style and converted using the built-in mapping or a
    conversion_map.json file in the pack directory
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Optional

import requests


# ── Default conversion: tlahuac string-trait format → debugger numeric ──
# This mapping is used when personas.json has tlahuac-style string traits
# instead of debugger-style numeric traits. Other pack formats with numeric
# traits are used directly without conversion.

_TLAHUAC_CONVERT = {
    "calm_cooperative": {
        "traits": {"patience": 8, "clarity": 7, "tech_savviness": 5, "politeness": 8, "verbosity": 6},
        "style": {"tone": "polite", "formality": "formal", "typo_rate": 0.0, "abbreviation_use": "low", "emoji_use": "rare"},
        "edge_behaviors": {},
    },
    "impatient_urgent": {
        "traits": {"patience": 2, "clarity": 6, "tech_savviness": 5, "politeness": 4, "verbosity": 4},
        "style": {"tone": "frustrated", "formality": "casual", "typo_rate": 0.05, "abbreviation_use": "medium", "emoji_use": "none"},
        "edge_behaviors": {"rage_quits": True},
    },
    "angry_escalating": {
        "traits": {"patience": 1, "clarity": 6, "tech_savviness": 5, "politeness": 1, "verbosity": 7},
        "style": {"tone": "angry", "formality": "casual", "typo_rate": 0.1, "abbreviation_use": "low", "emoji_use": "none"},
        "edge_behaviors": {"rage_quits": True, "asks_off_topic": True, "tests_boundaries": True},
    },
    "confused_low_context": {
        "traits": {"patience": 6, "clarity": 3, "tech_savviness": 2, "politeness": 7, "verbosity": 6},
        "style": {"tone": "neutral", "formality": "casual", "typo_rate": 0.08, "abbreviation_use": "low", "emoji_use": "rare"},
        "edge_behaviors": {"provides_incomplete_info": True},
    },
    "ultra_short": {
        "traits": {"patience": 5, "clarity": 5, "tech_savviness": 5, "politeness": 5, "verbosity": 1},
        "style": {"tone": "neutral", "formality": "slang", "typo_rate": 0.0, "abbreviation_use": "high", "emoji_use": "frequent"},
        "edge_behaviors": {"provides_incomplete_info": True},
    },
    "price_sensitive": {
        "traits": {"patience": 7, "clarity": 7, "tech_savviness": 5, "politeness": 6, "verbosity": 5},
        "style": {"tone": "neutral", "formality": "casual", "typo_rate": 0.03, "abbreviation_use": "low", "emoji_use": "none"},
        "edge_behaviors": {"changes_mind": True},
    },
    "need_it_today": {
        "traits": {"patience": 2, "clarity": 7, "tech_savviness": 5, "politeness": 3, "verbosity": 4},
        "style": {"tone": "frustrated", "formality": "casual", "typo_rate": 0.05, "abbreviation_use": "medium", "emoji_use": "rare"},
        "edge_behaviors": {"rage_quits": True, "tests_boundaries": True},
    },
    "friendly_chatty": {
        "traits": {"patience": 7, "clarity": 5, "tech_savviness": 5, "politeness": 8, "verbosity": 9},
        "style": {"tone": "polite", "formality": "casual", "typo_rate": 0.05, "abbreviation_use": "low", "emoji_use": "moderate"},
        "edge_behaviors": {"asks_off_topic": True},
    },
}

_CATEGORY_DIFFICULTY = {
    "booking": "medium",
    "status": "easy",
    "warranty": "hard",
    "pricing": "medium",
    "diagnostic": "hard",
    "docs": "medium",
    "parts": "medium",
}

_DEFAULT_TRAITS = {
    "patience": 5, "clarity": 5, "tech_savviness": 5,
    "politeness": 5, "verbosity": 5,
}
_DEFAULT_STYLE = {
    "tone": "neutral", "formality": "casual",
    "typo_rate": 0.05, "abbreviation_use": "low", "emoji_use": "none",
}


class ExternalPersonaLoader:
    """
    Reads persona/scenario files from any external directory and converts
    them to debugger platform format.

    Supports:
      - Debugger-native format (personas with numeric traits 1-10)
      - Tlahuac format (personas with string traits + action_weights)
      - Any format with a conversion_map.json in the pack directory
    """

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self._conversion_map: dict | None = None

    def _load_json(self, filename: str) -> dict | list:
        path = self.data_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Data file not found: {path}")
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _get_conversion_map(self) -> dict:
        """Load conversion_map.json if it exists, else fall back to tlahuac defaults."""
        if self._conversion_map is not None:
            return self._conversion_map

        map_path = self.data_dir / "conversion_map.json"
        if map_path.exists():
            with open(map_path, encoding="utf-8") as f:
                self._conversion_map = json.load(f)
        else:
            self._conversion_map = _TLAHUAC_CONVERT

        return self._conversion_map

    def _is_debugger_format(self, persona_data: dict) -> bool:
        """Check if a persona dict already has debugger-style numeric traits."""
        traits = persona_data.get("traits", {})
        if isinstance(traits, dict) and "patience" in traits:
            return isinstance(traits["patience"], (int, float))
        return False

    # ── Personas ──────────────────────────────────────────────────

    def load_personas(self, selected_ids: Optional[list[str]] = None) -> list[dict]:
        """Load personas and convert to debugger format if needed."""
        raw = self._load_json("personas.json")

        # Handle both {id: data} dict and [data, ...] list formats
        if isinstance(raw, list):
            items = [(p.get("persona_id", f"persona_{i}"), p) for i, p in enumerate(raw)]
        else:
            items = list(raw.items())

        personas = []
        for pid, pdata in items:
            if selected_ids and pid not in selected_ids:
                continue

            if self._is_debugger_format(pdata):
                persona = self._load_native_persona(pid, pdata)
            else:
                persona = self._convert_external_persona(pid, pdata)

            personas.append(persona)

        return personas

    def _load_native_persona(self, pid: str, pdata: dict) -> dict:
        """Load a persona that's already in debugger format."""
        return {
            "persona_id": pid,
            "name": pdata.get("name", pid),
            "agent_type": pdata.get("agent_type", "sales"),
            "source": pdata.get("source", "external"),
            "traits": pdata["traits"],
            "style": pdata.get("style", _DEFAULT_STYLE),
            "edge_behaviors": pdata.get("edge_behaviors", {}),
            "sample_messages": pdata.get("sample_messages", []),
            "tlahuac_data": pdata.get("tlahuac_data"),
        }

    def _convert_external_persona(self, pid: str, pdata: dict) -> dict:
        """Convert tlahuac-style persona to debugger format."""
        convert_map = self._get_conversion_map()
        convert = convert_map.get(pid, {})

        traits = convert.get("traits", _DEFAULT_TRAITS)
        style = convert.get("style", _DEFAULT_STYLE)
        edge = convert.get("edge_behaviors", {})

        common_phrases = pdata.get("message_style", {}).get("common_phrases", [])

        return {
            "persona_id": pid,
            "name": pdata.get("name", pid),
            "agent_type": "sales",
            "source": "tlahuac",
            "traits": traits,
            "style": style,
            "edge_behaviors": {
                "rage_quits": edge.get("rage_quits", False),
                "changes_mind": edge.get("changes_mind", False),
                "provides_incomplete_info": edge.get("provides_incomplete_info", False),
                "asks_off_topic": edge.get("asks_off_topic", False),
                "tests_boundaries": edge.get("tests_boundaries", False),
            },
            "sample_messages": common_phrases,
            "tlahuac_data": {
                "description": pdata.get("description", ""),
                "persona_traits": pdata.get("traits", []),
                "action_weights": pdata.get("action_weights", {}),
                "common_phrases": common_phrases,
                "message_style": pdata.get("message_style", {}),
            },
        }

    # ── Scenarios ─────────────────────────────────────────────────

    def load_scenarios(self, categories: Optional[list[str]] = None) -> list[dict]:
        """Load scenarios from scenarios.json (optional file)."""
        try:
            raw = self._load_json("scenarios.json")
        except FileNotFoundError:
            return []

        # Handle nested wrapper (e.g. {"scenarios": {...}})
        if isinstance(raw, dict) and "scenarios" in raw and len(raw) == 1:
            raw = raw["scenarios"]

        if isinstance(raw, list):
            items = [(s.get("scenario_id", f"scenario_{i}"), s) for i, s in enumerate(raw)]
        else:
            items = list(raw.items())

        scenarios = []
        for sid, sdata in items:
            cat = sdata.get("category", "")
            if categories and cat not in categories:
                continue

            openers = sdata.get("starter_openers", [])
            difficulty = _CATEGORY_DIFFICULTY.get(cat, "medium")

            scenarios.append({
                "scenario_id": sid,
                "title": sdata.get("description", sid),
                "description": sdata.get("description", ""),
                "category": cat,
                "user_goal": sdata.get("description", ""),
                "difficulty": difficulty,
                "starter_openers": openers,
                "required_slots": sdata.get("required_slots", []),
                "optional_slots": sdata.get("optional_slots", []),
                "success_endings": sdata.get("success_endings", []),
                "failure_endings": sdata.get("failure_endings", []),
            })

        return scenarios

    def load_variants(self) -> dict:
        """Load scenario_variants.json (optional file)."""
        try:
            return self._load_json("scenario_variants.json")
        except FileNotFoundError:
            return {}

    def pick_opener(self, scenario_id: Optional[str] = None) -> str:
        """Pick a random opener from variants or scenarios."""
        variants = self.load_variants()
        all_openers = []
        for family in variants.values():
            for variant in family.get("variants", []):
                all_openers.extend(variant.get("starter_openers", []))

        if not all_openers:
            for s in self.load_scenarios():
                all_openers.extend(s.get("starter_openers", []))

        return random.choice(all_openers) if all_openers else "Hola, necesito ayuda"


# Backward-compat alias
TlahuacDirectLoader = ExternalPersonaLoader


# ── HTTP Client (for API-based persona providers) ─────────────────


class PersonaProviderClient:
    """HTTP client for any external persona provider API."""

    def __init__(self, endpoint: str, provider_name: str = "external"):
        self.endpoint = endpoint.rstrip("/")
        self.provider_name = provider_name

    def _url(self, path: str) -> str:
        return f"{self.endpoint}/{path.lstrip('/')}"

    def health_check(self) -> dict:
        """Check provider health. Raises on connection failure."""
        resp = requests.get(self._url("/health"), timeout=5)
        resp.raise_for_status()
        return resp.json()

    def fetch_personas(self, persona_ids: Optional[list[str]] = None) -> list[dict]:
        """Fetch all personas from the provider, optionally filtering by IDs."""
        resp = requests.get(self._url("/personas"), timeout=10)
        resp.raise_for_status()
        data = resp.json()
        personas = data.get("personas", [])

        if persona_ids:
            personas = [p for p in personas if p.get("persona_id") in persona_ids]

        return personas

    def fetch_persona(self, persona_id: str) -> dict:
        """Fetch a single persona by ID."""
        resp = requests.get(self._url(f"/personas/{persona_id}"), timeout=10)
        resp.raise_for_status()
        return resp.json()

    def generate_conversation(
        self,
        persona_id: str,
        target_tools: list[str],
        max_turns: int = 10,
    ) -> dict:
        """Generate a tool-targeting conversation for a persona."""
        resp = requests.post(
            self._url("/generate-conversation"),
            json={
                "persona_id": persona_id,
                "target_tools": target_tools,
                "max_turns": max_turns,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
