"""
Sequence mining from parsed trace conversations.

Uses n-gram counting to extract frequent tool-call sequences,
mutually exclusive tools, failure-correlated patterns, and
decision-point statistics.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from src.traces.trace_parser import TraceConversation, TraceAnalysisResult


def mine_tool_sequences(
    conversations: list[TraceConversation],
    static_tool_names: list[str] | None = None,
) -> TraceAnalysisResult:
    """Mine tool-call patterns from a list of conversations.

    Parameters
    ----------
    conversations : list[TraceConversation]
        Parsed trace conversations.
    static_tool_names : list[str] | None
        Tool names discovered by static analysis, used to identify
        tools only present in traces or only in static.
    """
    if not conversations:
        return TraceAnalysisResult(
            conversations=[],
            tool_frequency={},
            tool_sequences=[],
            tools_not_in_static=[],
            tools_not_in_traces=[],
            common_first_tools=[],
            common_last_tools=[],
            avg_tools_per_conversation=0.0,
            failure_patterns=[],
        )

    static_names = set(static_tool_names or [])

    # ── Tool frequency ──
    freq: Counter[str] = Counter()
    for conv in conversations:
        for name in conv.tool_sequence:
            freq[name] += 1

    # ── Frequent bigram & trigram sequences ──
    bigram_counter: Counter[tuple[str, ...]] = Counter()
    trigram_counter: Counter[tuple[str, ...]] = Counter()
    for conv in conversations:
        seq = conv.tool_sequence
        for i in range(len(seq) - 1):
            bigram_counter[(seq[i], seq[i + 1])] += 1
        for i in range(len(seq) - 2):
            trigram_counter[(seq[i], seq[i + 1], seq[i + 2])] += 1

    threshold = max(1, int(len(conversations) * 0.05))
    frequent_seqs: list[tuple[list[str], int]] = []
    for gram, count in bigram_counter.most_common():
        if count >= threshold:
            frequent_seqs.append((list(gram), count))
    for gram, count in trigram_counter.most_common():
        if count >= threshold:
            frequent_seqs.append((list(gram), count))
    frequent_seqs.sort(key=lambda x: -x[1])

    # ── Mutually exclusive tools ──
    tool_cooccurrence: dict[frozenset[str], int] = {}
    all_trace_tools = set(freq.keys())
    for conv in conversations:
        tools_in_conv = set(conv.tool_sequence)
        for t1 in tools_in_conv:
            for t2 in tools_in_conv:
                if t1 < t2:
                    pair = frozenset([t1, t2])
                    tool_cooccurrence[pair] = tool_cooccurrence.get(pair, 0) + 1

    # Tools that appear individually but never together
    mutually_exclusive: list[list[str]] = []
    for t1 in all_trace_tools:
        for t2 in all_trace_tools:
            if t1 < t2:
                pair = frozenset([t1, t2])
                both_count = tool_cooccurrence.get(pair, 0)
                if both_count == 0 and freq[t1] >= threshold and freq[t2] >= threshold:
                    mutually_exclusive.append(sorted([t1, t2]))

    # ── First / last tools ──
    first_counter: Counter[str] = Counter()
    last_counter: Counter[str] = Counter()
    for conv in conversations:
        if conv.tool_sequence:
            first_counter[conv.tool_sequence[0]] += 1
            last_counter[conv.tool_sequence[-1]] += 1

    common_first = [t for t, _ in first_counter.most_common(5)]
    common_last = [t for t, _ in last_counter.most_common(5)]

    # ── Average tools per conversation ──
    total_tools = sum(len(c.tool_sequence) for c in conversations)
    avg_tools = total_tools / len(conversations) if conversations else 0.0

    # ── Static vs trace comparison ──
    trace_tool_names = set(freq.keys())
    tools_not_in_static = sorted(trace_tool_names - static_names) if static_names else []
    tools_not_in_traces = sorted(static_names - trace_tool_names) if static_names else []

    # ── Failure-correlated patterns ──
    failure_patterns = _mine_failure_patterns(conversations, threshold)

    return TraceAnalysisResult(
        conversations=conversations,
        tool_frequency=dict(freq.most_common()),
        tool_sequences=frequent_seqs,
        tools_not_in_static=tools_not_in_static,
        tools_not_in_traces=tools_not_in_traces,
        common_first_tools=common_first,
        common_last_tools=common_last,
        avg_tools_per_conversation=round(avg_tools, 2),
        failure_patterns=failure_patterns,
    )


def _mine_failure_patterns(
    conversations: list[TraceConversation],
    threshold: int,
) -> list[dict]:
    """Find tool sequences that correlate with failure outcomes."""
    failure_seqs: Counter[tuple[str, ...]] = Counter()
    total_seqs: Counter[tuple[str, ...]] = Counter()

    for conv in conversations:
        seq = conv.tool_sequence
        # Check bigrams
        for i in range(len(seq) - 1):
            gram = (seq[i], seq[i + 1])
            total_seqs[gram] += 1
            if conv.outcome == "failure":
                failure_seqs[gram] += 1

        # Check for retry patterns (same tool repeated)
        for i in range(len(seq) - 1):
            if seq[i] == seq[i + 1]:
                gram = (seq[i], seq[i])
                # Already counted above

    patterns: list[dict] = []
    for gram, fail_count in failure_seqs.most_common():
        total = total_seqs.get(gram, fail_count)
        if total >= threshold:
            rate = fail_count / total
            if rate >= 0.5:
                is_retry = len(set(gram)) == 1
                patterns.append({
                    "sequence": list(gram),
                    "failure_rate": round(rate, 2),
                    "occurrences": total,
                    "description": f"Retry loop on {gram[0]}" if is_retry else f"Sequence {' → '.join(gram)} fails {rate:.0%} of the time",
                })

    patterns.sort(key=lambda p: -p["failure_rate"])
    return patterns


def mine_decision_patterns(conversations: list[TraceConversation]) -> dict:
    """Extract decision-point statistics from conversations."""
    if not conversations:
        return {"branching_points": [], "avg_length_by_outcome": {}, "retry_tools": []}

    # Average conversation length by outcome
    by_outcome: dict[str, list[int]] = {}
    for conv in conversations:
        by_outcome.setdefault(conv.outcome, []).append(len(conv.tool_sequence))

    avg_length = {
        outcome: round(sum(lengths) / len(lengths), 1)
        for outcome, lengths in by_outcome.items()
    }

    # Retry patterns: tools called multiple times in a row
    retry_counter: Counter[str] = Counter()
    for conv in conversations:
        seq = conv.tool_sequence
        for i in range(len(seq) - 1):
            if seq[i] == seq[i + 1]:
                retry_counter[seq[i]] += 1

    retry_tools = [{"tool": t, "retry_count": c} for t, c in retry_counter.most_common(10)]

    # Branching points: positions where different conversations diverge
    branching: Counter[int] = Counter()
    max_len = max((len(c.tool_sequence) for c in conversations), default=0)
    for pos in range(max_len):
        tools_at_pos: set[str] = set()
        for conv in conversations:
            if pos < len(conv.tool_sequence):
                tools_at_pos.add(conv.tool_sequence[pos])
        if len(tools_at_pos) > 1:
            branching[pos] = len(tools_at_pos)

    branching_points = [
        {"position": pos, "distinct_tools": count}
        for pos, count in branching.most_common(10)
    ]

    return {
        "branching_points": branching_points,
        "avg_length_by_outcome": avg_length,
        "retry_tools": retry_tools,
    }
