"""
APFD Calculator (Sprint E12.2).

Average Percentage of Faults Detected (Rothermel et al.) — measures how early
in a test ordering faults are first detected:

    APFD = 1 - (sum of first-detection positions) / (n_tests * n_faults)
             + 1 / (2 * n_tests)

Higher is better; 1.0 means every fault is detected by the first test.
Faults never detected by any test in the ordering are penalised with a
first-detection position of n_tests + 1.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set


def _first_detection_positions(
    test_order: List[str],
    fault_detection_matrix: Dict[str, Set[str]],
) -> Dict[str, int]:
    """Map each fault to the 1-indexed position of the first test detecting it.

    The fault universe is the union of all faults in the matrix.  Faults not
    detected by any test in *test_order* get position ``len(test_order) + 1``.
    """
    all_faults: Set[str] = set()
    for faults in fault_detection_matrix.values():
        all_faults.update(faults)

    n = len(test_order)
    positions: Dict[str, int] = {f: n + 1 for f in all_faults}
    for i, test_id in enumerate(test_order, start=1):
        for fault in fault_detection_matrix.get(test_id, set()):
            if positions[fault] > i:
                positions[fault] = i
    return positions


def calculate_apfd(
    test_order: List[str],
    fault_detection_matrix: Dict[str, Set[str]],
) -> float:
    """Compute APFD for a test ordering.

    Args:
        test_order: test IDs in execution order.
        fault_detection_matrix: test_id -> set of fault IDs that test detects.

    Returns:
        APFD in [0, 1]; 0.0 when there are no tests or no faults.
    """
    positions = _first_detection_positions(test_order, fault_detection_matrix)
    n_tests = len(test_order)
    n_faults = len(positions)
    if n_tests == 0 or n_faults == 0:
        return 0.0

    return 1.0 - sum(positions.values()) / (n_tests * n_faults) + 1.0 / (2 * n_tests)


def calculate_weighted_apfd(
    test_order: List[str],
    fault_matrix: Dict[str, Set[str]],
    fault_weights: Dict[str, float],
) -> float:
    """Severity-weighted APFD: critical faults contribute more to the score.

        wAPFD = 1 - sum(w_f * pos_f) / (n_tests * sum(w_f)) + 1/(2 * n_tests)

    Faults missing from *fault_weights* default to weight 1.0.  With uniform
    weights this reduces to :func:`calculate_apfd`.
    """
    positions = _first_detection_positions(test_order, fault_matrix)
    n_tests = len(test_order)
    if n_tests == 0 or not positions:
        return 0.0

    total_weight = sum(fault_weights.get(f, 1.0) for f in positions)
    if total_weight <= 0:
        return 0.0

    weighted_positions = sum(
        fault_weights.get(f, 1.0) * pos for f, pos in positions.items()
    )
    return 1.0 - weighted_positions / (n_tests * total_weight) + 1.0 / (2 * n_tests)


def compare_orderings(
    ordering_a: List[str],
    ordering_b: List[str],
    fault_matrix: Dict[str, Set[str]],
    fault_weights: Optional[Dict[str, float]] = None,
) -> Dict[str, object]:
    """Compare two test orderings by APFD.

    Returns a dict with APFD for both orderings, the delta (a - b), and the
    winner ("a", "b", or "tie").  When *fault_weights* is given, weighted
    APFD values are included as well.
    """
    apfd_a = calculate_apfd(ordering_a, fault_matrix)
    apfd_b = calculate_apfd(ordering_b, fault_matrix)
    delta = apfd_a - apfd_b

    if abs(delta) < 1e-12:
        winner = "tie"
    else:
        winner = "a" if delta > 0 else "b"

    result: Dict[str, object] = {
        "apfd_a": apfd_a,
        "apfd_b": apfd_b,
        "delta": delta,
        "winner": winner,
    }
    if fault_weights is not None:
        result["weighted_apfd_a"] = calculate_weighted_apfd(ordering_a, fault_matrix, fault_weights)
        result["weighted_apfd_b"] = calculate_weighted_apfd(ordering_b, fault_matrix, fault_weights)
    return result
