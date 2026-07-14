"""Production ingestion: real deployed-agent conversations -> ground truth.

Implements the structured-signal analysis plan in docs/Agent_Failure_Plan.md:
load the WhatsApp conversation export, score every conversation from
human-process signals only (no LLM judge — that independence is the
methodological core of the study), classify failures into the eight
production categories, and build a time-split ground-truth failure set.
"""

from src.production.loader import load_export
from src.production.scoring import score_conversation
from src.production.ground_truth import (
    GroundTruthFailure,
    GroundTruthSet,
    build_ground_truth,
    time_split,
    to_production_signals,
)

__all__ = [
    "load_export",
    "score_conversation",
    "GroundTruthFailure",
    "GroundTruthSet",
    "build_ground_truth",
    "time_split",
    "to_production_signals",
]
