"""
Static vs dynamic comparison.

Compares statically extracted Agent Map data against dynamically
observed trace data to validate AI predictions and discover
tools/sequences missed by static analysis.
"""

from __future__ import annotations

from src.traces.trace_parser import TraceAnalysisResult


def compare_static_dynamic(
    agent_map: dict,
    trace_result: TraceAnalysisResult,
) -> dict:
    """Compare static Agent Map against dynamic trace observations.

    Returns a comparison report with validated/contradicted predictions.
    """
    # Static tool names
    static_tools = {
        t["name"]
        for t in agent_map.get("components", {}).get("tools", [])
    }

    # Static predicted sequences (from dependency_analysis or AI)
    # These may exist in components.orchestrator.typical_flow or similar
    orchestrator = agent_map.get("components", {}).get("orchestrator", {})
    predicted_flow = orchestrator.get("typical_flow", [])

    # Compare tool sets
    trace_tools = set(trace_result.tool_frequency.keys())
    tools_only_static = sorted(static_tools - trace_tools)
    tools_only_traces = sorted(trace_tools - static_tools)

    # Validate predicted sequences against observed
    observed_bigrams: set[tuple[str, str]] = set()
    for seq, _count in trace_result.tool_sequences:
        if len(seq) == 2:
            observed_bigrams.add((seq[0], seq[1]))

    sequence_matches: list[dict] = []
    sequence_mismatches: list[dict] = []

    if len(predicted_flow) >= 2:
        for i in range(len(predicted_flow) - 1):
            pair = (predicted_flow[i], predicted_flow[i + 1])
            if pair in observed_bigrams:
                sequence_matches.append({
                    "predicted": list(pair),
                    "status": "confirmed",
                })
            else:
                sequence_mismatches.append({
                    "predicted": list(pair),
                    "status": "not_observed",
                })

    # Coverage: what fraction of static tools appear in traces
    coverage = (
        len(static_tools & trace_tools) / len(static_tools)
        if static_tools else 1.0
    )

    return {
        "tools_only_in_static": tools_only_static,
        "tools_only_in_traces": tools_only_traces,
        "sequence_matches": sequence_matches,
        "sequence_mismatches": sequence_mismatches,
        "static_tools_coverage": round(coverage, 2),
        "ai_predictions_confirmed": len(sequence_matches),
        "ai_predictions_contradicted": len(sequence_mismatches),
    }
