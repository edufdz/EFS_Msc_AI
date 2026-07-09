"""
Suite-Quality Measurement Harness (Sprint E12).

Measures test-suite quality along four axes:
  - Fault-detection rate against a shared failure taxonomy (taxonomy.py)
  - APFD test-ordering effectiveness (apfd.py)
  - Precision/recall of synthetic failures vs production signals (predictive_validity.py)
  - Behaviour-space diversity / archive coverage (diversity.py)
  - Mutation score against seeded agent faults (mutation.py)

The unified entry point is ``evaluate_suite`` in harness.py.
"""

from src.evaluation.taxonomy import (
    FailureCategory,
    CATEGORY_TAXONOMY_IDS,
    CATEGORY_SEVERITY,
    SEVERITY_WEIGHTS,
    severity_weight,
)
from src.evaluation.apfd import calculate_apfd, calculate_weighted_apfd, compare_orderings
from src.evaluation.predictive_validity import (
    ProductionSignal,
    compute_predictive_validity,
    load_production_signals,
)
from src.evaluation.diversity import compute_suite_diversity
from src.evaluation.mutation import MutationOperator, generate_mutants, compute_mutation_score
from src.evaluation.harness import evaluate_suite

__all__ = [
    "FailureCategory",
    "CATEGORY_TAXONOMY_IDS",
    "CATEGORY_SEVERITY",
    "SEVERITY_WEIGHTS",
    "severity_weight",
    "calculate_apfd",
    "calculate_weighted_apfd",
    "compare_orderings",
    "ProductionSignal",
    "compute_predictive_validity",
    "load_production_signals",
    "compute_suite_diversity",
    "MutationOperator",
    "generate_mutants",
    "compute_mutation_score",
    "evaluate_suite",
]
