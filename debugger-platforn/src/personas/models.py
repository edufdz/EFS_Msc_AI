"""
Pydantic models for the Persona Builder system.
Defines persona traits, style, edge behaviors, and the persona library.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PersonaTraits(BaseModel):
    patience: int = Field(ge=1, le=10, description="1=very impatient, 10=endlessly patient")
    clarity: int = Field(ge=1, le=10, description="1=very vague, 10=crystal clear")
    tech_savviness: int = Field(ge=1, le=10, description="1=technophobe, 10=expert")
    politeness: int = Field(ge=1, le=10, description="1=rude, 10=extremely polite")
    verbosity: int = Field(ge=1, le=10, description="1=terse, 10=very wordy")
    emotional_volatility: int = Field(default=5, ge=1, le=10, description="1=stoic, 10=extreme mood swings between turns")
    trust_level: int = Field(default=5, ge=1, le=10, description="1=very suspicious, 10=blind trust")
    detail_orientation: int = Field(default=5, ge=1, le=10, description="1=big-picture only, 10=obsessive about details")
    decision_speed: int = Field(default=5, ge=1, le=10, description="1=agonizes over decisions, 10=decides instantly")
    language_proficiency: int = Field(default=8, ge=1, le=10, description="1=broken grammar, 10=native fluency")


class PersonaStyle(BaseModel):
    tone: str = Field(description="polite|neutral|frustrated|angry")
    formality: str = Field(description="formal|casual|slang")
    typo_rate: float = Field(ge=0.0, le=1.0, description="0.0=perfect typing, 1.0=constant typos")
    abbreviation_use: str = Field(default="low", description="low|medium|high")
    emoji_use: str = Field(default="none", description="none|rare|moderate|frequent")


class PersonaEdgeBehaviors(BaseModel):
    rage_quits: bool = False
    changes_mind: bool = False
    provides_incomplete_info: bool = False
    asks_off_topic: bool = False
    tests_boundaries: bool = False


class MoodState(BaseModel):
    """Tracks persona mood during a conversation (used by mood drift in Step 5)."""
    frustration: float = Field(default=0.0, ge=0.0, le=10.0)
    trust: float = Field(default=5.0, ge=0.0, le=10.0)
    current_patience: float = Field(default=5.0, ge=0.0, le=10.0)
    escalation_level: int = Field(default=0, ge=0, le=3, description="0=calm, 1=annoyed, 2=frustrated, 3=angry")
    turns_without_progress: int = Field(default=0, ge=0)


class Persona(BaseModel):
    persona_id: str
    name: str
    agent_type: str  # support|sales|scheduling|etc
    source: str  # template|ai_generated|custom|tlahuac|tool_attack|flow_attack
    traits: PersonaTraits
    style: PersonaStyle
    edge_behaviors: PersonaEdgeBehaviors
    sample_messages: List[str] = []
    created_at: datetime
    tlahuac_data: Optional[Dict[str, Any]] = None  # Extra tlahuac persona data (common_phrases, action_weights, etc.)
    target_tool: Optional[str] = None  # tool name this persona is designed to stress-test
    target_flow: Optional[str] = None  # tool chain name this persona is designed to test

    @property
    def archetype(self) -> str:
        """Classify persona into a broad archetype based on trait clustering."""
        t = self.traits
        e = self.edge_behaviors

        # Adversarial: low politeness + tests boundaries or rage quits
        if t.politeness <= 3 and (e.tests_boundaries or e.rage_quits):
            return "adversarial"

        # Demanding expert: high tech savviness + high detail orientation + low patience
        if t.tech_savviness >= 7 and t.detail_orientation >= 7 and t.patience <= 4:
            return "demanding_expert"

        # Confused novice: low clarity + low tech savviness
        if t.clarity <= 4 and t.tech_savviness <= 4:
            return "confused_novice"

        # Rambler: high verbosity + asks off topic or low clarity
        if t.verbosity >= 7 and (e.asks_off_topic or t.clarity <= 4):
            return "rambler"

        # Ideal customer: high patience + high clarity + high politeness
        if t.patience >= 7 and t.clarity >= 7 and t.politeness >= 7:
            return "ideal_customer"

        return "general"


class PersonaLibrary(BaseModel):
    persona_library_id: str
    agent_id: str
    personas: List[Persona]
    created_at: datetime
