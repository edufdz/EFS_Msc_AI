"""
Fixture-loading utilities for the Phase B enhancement test-suite (Sprint E-T).

Everything here is fully offline: the fixtures are hand-built agent maps and
simulated Langfuse trace/production data. No API key or network access is
required.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

# Make ``src`` importable when these helpers are used from any test module.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.evaluation.predictive_validity import ProductionSignal  # noqa: E402
from src.evaluation.taxonomy import FailureCategory  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parent

# Named agent-map fixtures. "tech_repair"/"enriched" is the rich map exercising
# every Phase B enhancement; "python"/"minimal" is a stripped-down map used
# for graceful-degradation tests.
_AGENT_MAPS = {
    "tech_repair": "enriched_agent_map.json",
    "enriched": "enriched_agent_map.json",
    "python": "python_agent_map.json",
    "minimal": "python_agent_map.json",
}


def agent_map_path(name: str = "tech_repair") -> Path:
    """Absolute path to a named agent-map fixture."""
    fname = _AGENT_MAPS.get(name)
    if fname is None:
        raise KeyError(f"Unknown agent map fixture '{name}'. Known: {sorted(_AGENT_MAPS)}")
    return FIXTURES_DIR / fname


def load_agent_map(name: str = "tech_repair") -> Dict[str, Any]:
    """Load a named agent-map fixture as a dict."""
    with open(agent_map_path(name)) as f:
        return json.load(f)


def traces_path() -> Path:
    """Absolute path to the mock trace-result fixture."""
    return FIXTURES_DIR / "mock_trace_result.json"


def load_mock_traces() -> Dict[str, Any]:
    """Load the simulated Langfuse trace-analysis result as a dict.

    Shape matches what ``src.scenarios.seed_corpus.load_trace_result`` and
    ``build_seed_corpus`` expect: ``conversations``, ``failure_patterns``,
    ``tool_frequency``, ``common_sequences``.
    """
    with open(traces_path()) as f:
        return json.load(f)


def load_mock_production_signals() -> List[ProductionSignal]:
    """Load the mock production signals as ``ProductionSignal`` objects."""
    with open(FIXTURES_DIR / "mock_production_signals.json") as f:
        raw = json.load(f)
    signals: List[ProductionSignal] = []
    for entry in raw:
        signals.append(ProductionSignal(
            signal_id=entry["signal_id"],
            trace_id=entry["trace_id"],
            failure_category=FailureCategory(entry["failure_category"]),
            description=entry.get("description", ""),
            tool_involved=entry.get("tool_involved"),
            guardrail_rule_id=entry.get("guardrail_rule_id"),
            source=entry.get("source", "human_label"),
        ))
    return signals
