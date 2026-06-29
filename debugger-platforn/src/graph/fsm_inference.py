"""
FSM Inference from Trace Data (Sprint 8).

Infers a finite-state machine abstraction of the agent's decision flow
from observed trace conversations.  Uses a simplified k-tail state merging
algorithm.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from src.graph.behavioural_model import FSMState, FSMTransition


def _state_name(tool: str | None, is_initial: bool = False, is_terminal: bool = False) -> str:
    """Generate a human-readable state name."""
    if is_initial:
        return "initial"
    if is_terminal:
        return "completed"
    if tool:
        return f"after_{tool.lower().replace(' ', '_')}"
    return "unknown"


def infer_fsm(
    conversations: list,
    agent_map: dict,
    k: int = 2,
) -> tuple[list[FSMState], list[FSMTransition]]:
    """Infer an FSM from trace conversations using k-tail merging.

    Parameters
    ----------
    conversations : list[TraceConversation]
        Parsed trace conversations with ``tool_sequence`` attribute.
    agent_map : dict
        The agent map (used for tool names / risk info).
    k : int
        Suffix length for state merging (default 2).

    Returns
    -------
    (states, transitions)
    """
    if not conversations:
        return [], []

    tool_names = {t["name"] for t in agent_map.get("components", {}).get("tools", [])}

    # ── Step 1: Collect all unique tool sequences ──
    sequences: list[list[str]] = []
    for conv in conversations:
        seq = getattr(conv, "tool_sequence", [])
        if seq:
            sequences.append(list(seq))

    if not sequences:
        return [], []

    # ── Step 2: Build state set via k-tail suffix merging ──
    # Each state is identified by the k-length suffix of tool calls
    # that led to it.  The initial state has suffix ().
    state_suffixes: dict[tuple[str, ...], str] = {}
    transition_counter: Counter[tuple[str, str, str]] = Counter()  # (from_state, to_state, trigger)

    initial_id = "S0"
    state_suffixes[()] = initial_id

    for seq in sequences:
        current_suffix: tuple[str, ...] = ()
        current_state = initial_id

        for tool in seq:
            # Compute new suffix (last k tools)
            new_suffix = (current_suffix + (tool,))[-k:]

            if new_suffix not in state_suffixes:
                sid = f"S{len(state_suffixes)}"
                state_suffixes[new_suffix] = sid

            next_state = state_suffixes[new_suffix]
            transition_counter[(current_state, next_state, tool)] += 1
            current_state = next_state
            current_suffix = new_suffix

    # ── Step 3: Build state objects ──
    # Determine terminal states (states that are the last state in any sequence)
    terminal_states: set[str] = set()
    for seq in sequences:
        if seq:
            suffix = tuple(seq[-k:])
            if suffix in state_suffixes:
                terminal_states.add(state_suffixes[suffix])

    # Tools available from each state
    tools_from_state: dict[str, set[str]] = {}
    for (from_s, _to_s, trigger), _count in transition_counter.items():
        tools_from_state.setdefault(from_s, set()).add(trigger)

    states: list[FSMState] = []
    for suffix, sid in state_suffixes.items():
        is_initial = (sid == initial_id)
        is_terminal = (sid in terminal_states)
        name = _state_name(suffix[-1] if suffix else None, is_initial, is_terminal)

        states.append(FSMState(
            state_id=sid,
            name=name,
            description=f"State after calling: {' → '.join(suffix)}" if suffix else "Initial state",
            tools_available=sorted(tools_from_state.get(sid, [])),
            is_initial=is_initial,
            is_terminal=is_terminal,
        ))

    # ── Step 4: Build transitions with frequencies ──
    # Group transitions by source state to compute frequencies
    transitions_from: dict[str, int] = Counter()
    for (from_s, _to_s, _trigger), count in transition_counter.items():
        transitions_from[from_s] += count

    transitions: list[FSMTransition] = []
    for (from_s, to_s, trigger), count in transition_counter.items():
        total = transitions_from[from_s]
        freq = round(count / total, 3) if total > 0 else 0.0

        transitions.append(FSMTransition(
            from_state=from_s,
            to_state=to_s,
            trigger=trigger,
            guard=None,
            frequency=freq,
        ))

    # Sort for deterministic output
    states.sort(key=lambda s: s.state_id)
    transitions.sort(key=lambda t: (t.from_state, t.to_state))

    return states, transitions
