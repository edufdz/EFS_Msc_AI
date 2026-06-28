"""
PersonaBuilder: creates, manages, and exports synthetic user personas
for agent testing.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import random

from dotenv import load_dotenv

from src.execution.llm_config import LLMProviderConfig
from src.personas.models import (
    Persona, PersonaLibrary,
    PersonaTraits, PersonaStyle, PersonaEdgeBehaviors,
)
from src.personas.templates import load_persona_templates, GENERIC_PERSONAS

# Load .env from project root
_project_root = Path(__file__).parent.parent.parent
load_dotenv(_project_root / ".env")

# Realistic fake names for generated personas — avoids leaking tool names
_FAKE_NAMES = [
    "Marcus Johnson", "Sofia Rivera", "James Chen", "Priya Patel",
    "Carlos Mendoza", "Emma Thompson", "David Kim", "Aisha Williams",
    "Robert Garcia", "Mei-Lin Wu", "Daniel Okafor", "Laura Petrov",
    "Ahmed Hassan", "Rachel Nguyen", "Tyler Brooks", "Camila Santos",
    "Nathan Fischer", "Olivia Reyes", "Kevin O'Brien", "Zara Mitchell",
    "Brian Taylor", "Diana Kowalski", "Samuel Jones", "Fatima Al-Rashid",
    "Chris Martinez", "Hannah Lee", "Victor Dubois", "Isabel Moreno",
    "Ryan Cooper", "Ananya Sharma",
]


class PersonaBuilder:
    """
    Builds a library of synthetic user personas from templates,
    AI generation, or manual input.
    """

    def __init__(
        self,
        agent_map: Dict,
        language: str = "English",
        usage_tracker: Any = None,
        llm_config: Optional[LLMProviderConfig] = None,
    ):
        self.agent_map = agent_map
        self.agent_type: str = agent_map.get("metadata", {}).get("type", "custom")
        self.agent_purpose: str = agent_map.get("metadata", {}).get("purpose", "")
        self.language: str = language
        self.personas: List[Persona] = []
        self._usage_tracker = usage_tracker
        self._llm_config = llm_config or LLMProviderConfig()
        self._llm_client = None

    def _get_llm_client(self):
        if self._llm_client is None:
            self._llm_client = self._llm_config.create_sync_client()
        return self._llm_client

    def _pick_unique_name(self) -> str:
        """Pick a realistic fake name not already used by any persona."""
        used = {p.name for p in self.personas}
        available = [n for n in _FAKE_NAMES if n not in used]
        if not available:
            # All names used — append a number to a random one
            base = random.choice(_FAKE_NAMES)
            suffix = len(self.personas) + 1
            return f"{base} #{suffix}"
        return random.choice(available)

    # ------------------------------------------------------------------
    # Template loading
    # ------------------------------------------------------------------

    def load_templates(self, selected_names: Optional[List[str]] = None) -> List[Persona]:
        """
        Load persona templates matching the agent's domain.
        Optionally filter by name.
        """
        templates = load_persona_templates(self.agent_type, language=self.language)

        if selected_names:
            templates = [t for t in templates if t["name"] in selected_names]

        for tpl in templates:
            persona = Persona(
                persona_id=str(uuid.uuid4()),
                name=tpl["name"],
                agent_type=self.agent_type,
                source="template",
                traits=PersonaTraits(**tpl["traits"]),
                style=PersonaStyle(**tpl["style"]),
                edge_behaviors=PersonaEdgeBehaviors(**tpl.get("edge_behaviors", {})),
                sample_messages=[],
                created_at=datetime.now(timezone.utc),
            )
            self.personas.append(persona)

        return self.personas

    # ------------------------------------------------------------------
    # External persona loading (file-based or API)
    # ------------------------------------------------------------------

    def load_from_external(
        self,
        data_dir: str,
        selected_ids: Optional[List[str]] = None,
    ) -> List[Persona]:
        """Load personas from an external persona pack directory.

        Reads personas.json from the directory, auto-detects format
        (debugger-native or tlahuac-style), and converts as needed.
        No external API service required.
        """
        from src.personas.tlahuac_adapter import ExternalPersonaLoader

        loader = ExternalPersonaLoader(data_dir)
        raw_personas = loader.load_personas(selected_ids=selected_ids)
        return self._ingest_raw_personas(raw_personas)

    def load_from_provider(
        self,
        endpoint: str,
        provider_name: str = "external",
        selected_ids: Optional[List[str]] = None,
    ) -> List[Persona]:
        """Load personas from an external persona provider API.

        Works with any provider that implements the standard contract
        (health, personas, generate-conversation endpoints).
        """
        from src.personas.tlahuac_adapter import PersonaProviderClient

        client = PersonaProviderClient(endpoint, provider_name)
        client.health_check()
        raw_personas = client.fetch_personas(persona_ids=selected_ids)
        return self._ingest_raw_personas(raw_personas, default_source=provider_name)

    def _ingest_raw_personas(
        self,
        raw_personas: List[Dict],
        default_source: str = "external",
    ) -> List[Persona]:
        """Convert raw persona dicts to Persona objects and add to library."""
        loaded: List[Persona] = []
        for p in raw_personas:
            persona = Persona(
                persona_id=p.get("persona_id", str(uuid.uuid4())),
                name=p["name"],
                agent_type=p.get("agent_type", self.agent_type),
                source=p.get("source", default_source),
                traits=PersonaTraits(**p["traits"]),
                style=PersonaStyle(**p["style"]),
                edge_behaviors=PersonaEdgeBehaviors(**p.get("edge_behaviors", {})),
                sample_messages=p.get("sample_messages", []),
                created_at=datetime.now(timezone.utc),
                tlahuac_data=p.get("tlahuac_data"),
            )
            loaded.append(persona)
            self.personas.append(persona)

        return loaded

    # ------------------------------------------------------------------
    # AI-powered persona generation
    # ------------------------------------------------------------------

    def generate_personas(self, count: int = 3) -> List[Persona]:
        """
        Use Claude to generate novel personas tailored to the agent's
        purpose and tool set.  Includes diversity hints and duplicate filtering.
        """
        import json, re

        tool_names = [t["name"] for t in self.agent_map.get("components", {}).get("tools", [])]
        risks = self.agent_map.get("risk_flags", {})

        lang_instruction = (
            f"\nIMPORTANT: Generate all persona names in {self.language}."
            if self.language != "English" else ""
        )

        # Analyze existing trait distribution for diversity hints
        diversity_hint = self._build_diversity_hint(
            self._analyze_trait_distribution(), count,
        )

        prompt = f"""You are designing synthetic user personas to test an AI agent.

Agent info:
- Type: {self.agent_type}
- Purpose: {self.agent_purpose}
- Tools available: {', '.join(tool_names) if tool_names else 'unknown'}
- Has PII handling: {risks.get('pii_handling', False)}
- Critical actions: {risks.get('critical_actions', [])}

Generate exactly {count} diverse personas. Each persona should test a different
aspect of the agent (happy path, edge cases, adversarial, etc.).{lang_instruction}
{diversity_hint}

Return ONLY valid JSON (no markdown fences):
{{
  "personas": [
    {{
      "name": "Persona Name",
      "traits": {{
        "patience": 5,
        "clarity": 5,
        "tech_savviness": 5,
        "politeness": 5,
        "verbosity": 5,
        "emotional_volatility": 5,
        "trust_level": 5,
        "detail_orientation": 5,
        "decision_speed": 5,
        "language_proficiency": 8
      }},
      "style": {{
        "tone": "neutral",
        "formality": "casual",
        "typo_rate": 0.05,
        "abbreviation_use": "low",
        "emoji_use": "none"
      }},
      "edge_behaviors": {{
        "rage_quits": false,
        "changes_mind": false,
        "provides_incomplete_info": false,
        "asks_off_topic": false,
        "tests_boundaries": false
      }},
      "rationale": "why this persona is useful for testing"
    }}
  ]
}}"""

        client = self._get_llm_client()

        # Attempt with 1 retry on JSON parse failure
        for attempt in range(2):
            if attempt == 0:
                current_prompt = prompt
            else:
                current_prompt = (
                    prompt
                    + "\n\n--- PREVIOUS RESPONSE (INVALID JSON) ---\n"
                    + raw
                    + "\n\n--- FIX ---\nThe previous response was not valid JSON. "
                    "Please fix it and return ONLY valid JSON, no explanation."
                )

            raw, in_tok, out_tok = self._llm_config.call_sync(
                client, current_prompt, max_tokens=8192, temperature=0.7,
            )
            if self._usage_tracker:
                self._usage_tracker.add_tokens(in_tok, out_tok)

            raw = raw.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```\w*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw)

            try:
                data = json.loads(raw)
                break
            except json.JSONDecodeError:
                if attempt == 1:
                    raise

        generated = []

        for p in data.get("personas", []):
            persona = Persona(
                persona_id=str(uuid.uuid4()),
                name=p["name"],
                agent_type=self.agent_type,
                source="ai_generated",
                traits=PersonaTraits(**p["traits"]),
                style=PersonaStyle(**p["style"]),
                edge_behaviors=PersonaEdgeBehaviors(**p.get("edge_behaviors", {})),
                sample_messages=[],
                created_at=datetime.now(timezone.utc),
            )
            # Skip duplicates
            if self._is_duplicate(persona):
                continue
            generated.append(persona)
            self.personas.append(persona)

        return generated

    # ------------------------------------------------------------------
    # Diversity helpers for AI generation
    # ------------------------------------------------------------------

    def _analyze_trait_distribution(self) -> Dict[str, List[int]]:
        """Map each trait name to the list of existing values across all personas."""
        dist: Dict[str, List[int]] = {}
        trait_names = [
            "patience", "clarity", "tech_savviness", "politeness", "verbosity",
            "emotional_volatility", "trust_level", "detail_orientation",
            "decision_speed", "language_proficiency",
        ]
        for name in trait_names:
            dist[name] = [getattr(p.traits, name, 5) for p in self.personas]
        return dist

    @staticmethod
    def _build_diversity_hint(dist: Dict[str, List[int]], count: int) -> str:
        """Identify under-represented trait ranges and build a hint string."""
        if not dist or not any(dist.values()):
            return ""

        gaps: List[str] = []
        for trait, values in dist.items():
            if not values:
                continue
            low = sum(1 for v in values if v <= 3)
            high = sum(1 for v in values if v >= 8)
            if low == 0:
                gaps.append(f"low {trait} (1-3)")
            if high == 0:
                gaps.append(f"high {trait} (8-10)")

        if not gaps:
            return ""

        sampled = gaps[:6]  # cap hint length
        return (
            f"\nDIVERSITY REQUIREMENTS: The current persona set is missing coverage for: "
            f"{', '.join(sampled)}. "
            f"Please ensure at least one generated persona covers each gap."
        )

    def _is_duplicate(self, new_persona: Persona, threshold: float = 0.85) -> bool:
        """Check if new_persona is too similar to any existing persona.

        Uses a cosine-like similarity on the 10 core numeric traits.
        """
        trait_names = [
            "patience", "clarity", "tech_savviness", "politeness", "verbosity",
            "emotional_volatility", "trust_level", "detail_orientation",
            "decision_speed", "language_proficiency",
        ]
        new_vec = [getattr(new_persona.traits, t, 5) for t in trait_names]

        for existing in self.personas:
            existing_vec = [getattr(existing.traits, t, 5) for t in trait_names]
            # Cosine similarity
            dot = sum(a * b for a, b in zip(new_vec, existing_vec))
            mag_new = sum(a ** 2 for a in new_vec) ** 0.5
            mag_existing = sum(a ** 2 for a in existing_vec) ** 0.5
            if mag_new == 0 or mag_existing == 0:
                continue
            similarity = dot / (mag_new * mag_existing)
            if similarity >= threshold and new_persona.name == existing.name:
                return True
        return False

    # ------------------------------------------------------------------
    # Sample message generation
    # ------------------------------------------------------------------

    def generate_sample_messages(
        self, persona: Persona, count: int = 3,
    ) -> List[str]:
        """
        Generate example messages that this persona would send to the agent.
        """
        tool_names = [t["name"] for t in self.agent_map.get("components", {}).get("tools", [])]

        edge_list = [k for k, v in persona.edge_behaviors.model_dump().items() if v]
        edge_desc = ", ".join(edge_list) if edge_list else "none"

        # Detect language from self.language or agent_map
        language = self.language
        if language == "English":
            language = self.agent_map.get("metadata", {}).get("conversation_language", "English")
        lang_instruction = f"\nIMPORTANT: Generate all messages in {language}." if language != "English" else ""

        prompt = f"""Generate exactly {count} example messages that this user persona
would send to a {self.agent_type} agent whose purpose is: {self.agent_purpose}
{lang_instruction}

Persona: {persona.name}
Traits: patience={persona.traits.patience}/10, clarity={persona.traits.clarity}/10, \
tech_savviness={persona.traits.tech_savviness}/10, politeness={persona.traits.politeness}/10, \
verbosity={persona.traits.verbosity}/10
Style: tone={persona.style.tone}, formality={persona.style.formality}, \
typo_rate={persona.style.typo_rate}, abbreviations={persona.style.abbreviation_use}, \
emojis={persona.style.emoji_use}
Edge behaviors: {edge_desc}
Available tools the agent has: {', '.join(tool_names) if tool_names else 'general'}

Each message should feel natural and reflect the persona's traits faithfully.
If typo_rate > 0, include realistic typos proportionally.
If the persona has edge behaviors, at least one message should demonstrate them.

Return ONLY a JSON array of strings (no markdown fences):
["message 1", "message 2", "message 3"]"""

        client = self._get_llm_client()
        raw, in_tok, out_tok = self._llm_config.call_sync(
            client, prompt, max_tokens=1024, temperature=0.7,
        )
        if self._usage_tracker:
            self._usage_tracker.add_tokens(in_tok, out_tok)

        import json, re
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```\w*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)

        messages = json.loads(raw)
        persona.sample_messages.extend(messages)
        return messages

    # ------------------------------------------------------------------
    # Tool-targeting persona generation
    # ------------------------------------------------------------------

    def generate_tool_attack_personas(self, tools: List[Dict] | None = None) -> List[Persona]:
        """Create one stress-test persona per tool from the agent_map.

        Persona traits are derived from tool metadata using a configurable
        mapping. The agent_map may provide ``persona_profiles`` to override
        the defaults::

            "persona_profiles": {
                "high_risk": {"patience": 2, "clarity": 7, ...},
                "low_risk":  {"patience": 8, "clarity": 9, ...},
                "default":   {"patience": 5, "clarity": 5, ...}
            }

        When no custom profiles are provided the built-in heuristic is used:

        - ``risk_level: "high"`` -> adversarial persona (low patience, tests boundaries)
        - ``risk_level: "low"`` -> happy-path persona (high patience, clear requests)
        - ``read_only: False`` -> persona that changes mind, gives conflicting data
        - ``handles_sensitive_data: True`` -> persona that provides PII to test guardrails
        """
        if tools is None:
            tools = self.agent_map.get("components", {}).get("tools", [])

        # Deduplicate by tool name
        seen: set[str] = set()
        unique_tools: List[Dict] = []
        for t in tools:
            name = t.get("name", "")
            if name and name not in seen:
                seen.add(name)
                unique_tools.append(t)

        # Allow agent_map to override persona trait profiles
        custom_profiles = self.agent_map.get("persona_profiles", {})

        # Build tool chain index for position detection
        tool_chains = self.agent_map.get("tool_chains", [])

        generated: List[Persona] = []
        for tool in unique_tools:
            tool_name = tool.get("name", "unknown")
            risk = tool.get("risk_level", "medium")
            read_only = tool.get("read_only", True)
            sensitive = tool.get("handles_sensitive_data", False)

            # Extract parameter metadata (supports list or dict formats)
            params = tool.get("parameters", [])
            if isinstance(params, list):
                param_count = len(params)
                required_count = sum(
                    1 for p in params
                    if isinstance(p, dict) and p.get("required")
                )
            elif isinstance(params, dict):
                param_count = len(params)
                required_count = sum(
                    1 for v in params.values()
                    if isinstance(v, dict) and v.get("required")
                )
            else:
                param_count = 0
                required_count = 0

            chain_position = self._get_chain_position(tool_name, tool_chains)

            traits, style, edge, _ = self._derive_tool_persona(
                tool_name, risk, custom_profiles,
                param_count=param_count,
                required_param_count=required_count,
                chain_position=chain_position,
            )

            # Mutate for write tools — user changes mind
            if not read_only:
                edge.changes_mind = True

            # Mutate for sensitive data — provides PII
            if sensitive:
                edge.tests_boundaries = True

            persona = Persona(
                persona_id=str(uuid.uuid4()),
                name=self._pick_unique_name(),
                agent_type=self.agent_type,
                source="tool_attack",
                traits=traits,
                style=style,
                edge_behaviors=edge,
                sample_messages=[],
                created_at=datetime.now(timezone.utc),
                target_tool=tool_name,
            )
            generated.append(persona)
            self.personas.append(persona)

        return generated

    @staticmethod
    def _get_chain_position(tool_name: str, tool_chains: List[Dict]) -> str:
        """Determine where a tool sits in any defined chain.

        Returns "start", "middle", "end", or "standalone".
        """
        positions: set[str] = set()
        for chain in tool_chains:
            seq = chain.get("sequence", [])
            if tool_name not in seq:
                continue
            idx = seq.index(tool_name)
            if len(seq) == 1:
                positions.add("standalone")
            elif idx == 0:
                positions.add("start")
            elif idx == len(seq) - 1:
                positions.add("end")
            else:
                positions.add("middle")
        if not positions:
            return "standalone"
        # Prioritize: if it appears at multiple positions, pick most constraining
        for p in ("end", "start", "middle"):
            if p in positions:
                return p
        return "standalone"

    @staticmethod
    def _derive_tool_persona(
        tool_name: str,
        risk: str,
        custom_profiles: Dict,
        *,
        param_count: int = 0,
        required_param_count: int = 0,
        chain_position: str = "standalone",
    ) -> tuple:
        """Derive persona traits from risk level and tool metadata.

        Adapts traits based on:
        - Risk level (high/low/default)
        - Parameter complexity (many required params → incomplete info persona)
        - Chain position (start → low clarity, end → high patience + changes_mind)
        """

        def _profile_to_traits(profile: Dict) -> PersonaTraits:
            return PersonaTraits(
                patience=profile.get("patience", 5),
                clarity=profile.get("clarity", 5),
                tech_savviness=profile.get("tech_savviness", 5),
                politeness=profile.get("politeness", 5),
                verbosity=profile.get("verbosity", 5),
                emotional_volatility=profile.get("emotional_volatility", 5),
                trust_level=profile.get("trust_level", 5),
                detail_orientation=profile.get("detail_orientation", 5),
                decision_speed=profile.get("decision_speed", 5),
                language_proficiency=profile.get("language_proficiency", 8),
            )

        # Default trait profiles keyed by risk category
        _RISK_PROFILES: Dict[str, Dict] = {
            "high_risk": {
                "defaults": {
                    "patience": 2, "clarity": 7, "tech_savviness": 8, "politeness": 3, "verbosity": 6,
                    "emotional_volatility": 8, "trust_level": 2, "detail_orientation": 7,
                    "decision_speed": 7, "language_proficiency": 8,
                },
                "style": {"tone": "frustrated", "formality": "casual", "typo_rate": 0.1, "abbreviation_use": "medium", "emoji_use": "none"},
                "edge": {"tests_boundaries": True, "rage_quits": True, "provides_incomplete_info": False},
                "suffix": "Boundary Tester",
            },
            "low_risk": {
                "defaults": {
                    "patience": 8, "clarity": 9, "tech_savviness": 6, "politeness": 8, "verbosity": 4,
                    "emotional_volatility": 2, "trust_level": 8, "detail_orientation": 6,
                    "decision_speed": 5, "language_proficiency": 9,
                },
                "style": {"tone": "polite", "formality": "formal", "typo_rate": 0.0, "abbreviation_use": "low", "emoji_use": "none"},
                "edge": {"tests_boundaries": False, "rage_quits": False, "provides_incomplete_info": False},
                "suffix": "Happy Path",
            },
            "default": {
                "defaults": {
                    "patience": 5, "clarity": 5, "tech_savviness": 5, "politeness": 5, "verbosity": 5,
                    "emotional_volatility": 5, "trust_level": 5, "detail_orientation": 5,
                    "decision_speed": 5, "language_proficiency": 8,
                },
                "style": {"tone": "neutral", "formality": "casual", "typo_rate": 0.05, "abbreviation_use": "low", "emoji_use": "none"},
                "edge": {"tests_boundaries": False, "rage_quits": False, "provides_incomplete_info": True},
                "suffix": "Stress Tester",
            },
        }

        # Map risk level to profile key
        if risk in ("high", "critical"):
            profile_key = "high_risk"
        elif risk == "low":
            profile_key = "low_risk"
        else:
            profile_key = "default"

        base = _RISK_PROFILES[profile_key]

        # Merge custom profile over defaults
        profile = {**base["defaults"], **(custom_profiles.get(profile_key, {}))}
        edge_dict = dict(base["edge"])

        # Tools with 5+ required params → incomplete info persona, reduce clarity
        if required_param_count >= 5:
            edge_dict["provides_incomplete_info"] = True
            profile["clarity"] = min(profile.get("clarity", 5), 4)
            profile["detail_orientation"] = max(profile.get("detail_orientation", 5), 3)

        # End-of-chain tools → increase patience (need to wait for flow), add changes_mind
        if chain_position == "end":
            profile["patience"] = max(profile.get("patience", 5), 7)
            edge_dict["changes_mind"] = True

        # Start-of-chain tools → reduce clarity (test info gathering ability)
        if chain_position == "start":
            profile["clarity"] = min(profile.get("clarity", 5), 4)

        traits = _profile_to_traits(profile)
        style = PersonaStyle(**base["style"])
        edge = PersonaEdgeBehaviors(**edge_dict)

        # Return None for name — caller will assign a realistic fake name
        return traits, style, edge, None

    # ------------------------------------------------------------------
    # Flow-targeting persona generation
    # ------------------------------------------------------------------

    def generate_flow_attack_personas(self, tool_chains: List[Dict] | None = None) -> List[Persona]:
        """Create one stress-test persona per tool chain.

        Each persona is designed to test a full flow end-to-end with
        edge behaviors that challenge multi-step tool sequences.

        Chain-level overrides are supported via ``persona_override`` on
        each chain entry::

            {
                "name": "book_appointment",
                "sequence": ["check_availability", "create_booking"],
                "persona_override": {
                    "patience": 3,
                    "changes_mind": true,
                    "provides_incomplete_info": false
                }
            }
        """
        if tool_chains is None:
            tool_chains = self.agent_map.get("tool_chains", [])

        generated: List[Persona] = []
        for chain in tool_chains:
            chain_name = chain.get("name", "unknown")
            sequence = chain.get("sequence", [])
            override = chain.get("persona_override", {})

            chain_len = len(sequence)
            # Longer chains → more impatient persona (adaptable formula)
            base_patience = max(2, 7 - chain_len)

            traits = PersonaTraits(
                patience=override.get("patience", base_patience),
                clarity=override.get("clarity", 6),
                tech_savviness=override.get("tech_savviness", 5),
                politeness=override.get("politeness", 4),
                verbosity=override.get("verbosity", 6),
            )
            style = PersonaStyle(
                tone=override.get("tone", "neutral"),
                formality=override.get("formality", "casual"),
                typo_rate=override.get("typo_rate", 0.05),
                abbreviation_use=override.get("abbreviation_use", "low"),
                emoji_use=override.get("emoji_use", "none"),
            )
            edge = PersonaEdgeBehaviors(
                changes_mind=override.get("changes_mind", True),
                provides_incomplete_info=override.get("provides_incomplete_info", True),
                tests_boundaries=override.get("tests_boundaries", False),
                rage_quits=override.get("rage_quits", False),
                asks_off_topic=override.get("asks_off_topic", False),
            )

            persona = Persona(
                persona_id=str(uuid.uuid4()),
                name=self._pick_unique_name(),
                agent_type=self.agent_type,
                source="flow_attack",
                traits=traits,
                style=style,
                edge_behaviors=edge,
                sample_messages=[],
                created_at=datetime.now(timezone.utc),
                target_flow=chain_name,
            )
            generated.append(persona)
            self.personas.append(persona)

        return generated

    # ------------------------------------------------------------------
    # Custom persona creation
    # ------------------------------------------------------------------

    def create_custom(self, persona_data: Dict) -> Persona:
        """Create a persona from user-supplied data."""
        persona = Persona(
            persona_id=str(uuid.uuid4()),
            name=persona_data["name"],
            agent_type=persona_data.get("agent_type", self.agent_type),
            source="custom",
            traits=PersonaTraits(**persona_data["traits"]),
            style=PersonaStyle(**persona_data["style"]),
            edge_behaviors=PersonaEdgeBehaviors(**persona_data.get("edge_behaviors", {})),
            sample_messages=persona_data.get("sample_messages", []),
            created_at=datetime.now(timezone.utc),
        )
        self.personas.append(persona)
        return persona

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_library(self) -> PersonaLibrary:
        """Export all personas as a PersonaLibrary."""
        return PersonaLibrary(
            persona_library_id=str(uuid.uuid4()),
            agent_id=self.agent_map.get("agent_id", "unknown"),
            personas=self.personas,
            created_at=datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------------
    # Diversity reporting
    # ------------------------------------------------------------------

    def report_diversity(self) -> Dict:
        """Return a diversity coverage report for the current persona set."""
        from src.personas.metrics import trait_coverage_report
        return trait_coverage_report(self.personas)
