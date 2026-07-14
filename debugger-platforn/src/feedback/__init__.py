"""Production-feedback loop: real failures -> seeds -> re-seeded generation."""

from src.feedback.loop import (
    LeakageError,
    build_feedback_corpus,
    generate_blind_suite,
    generate_feedback_suite,
    production_failure_to_seed,
    verify_no_leakage,
)

__all__ = [
    "LeakageError",
    "build_feedback_corpus",
    "generate_blind_suite",
    "generate_feedback_suite",
    "production_failure_to_seed",
    "verify_no_leakage",
]
