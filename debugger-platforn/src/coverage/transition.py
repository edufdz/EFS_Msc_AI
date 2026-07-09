"""
FSM transition coverage — Sprint E3.

Computes transition-based coverage targets from the Agent Map's
behavioural model FSM (``agent_map["behavioural_model"]["fsm"]``):

- all-transitions coverage (0-switch): every transition at least once
- transition-pair coverage (1-switch): every pair of consecutive
  transitions
- round-trip paths: initial → ... → initial/terminal paths, prioritised
  through high-risk tools

Round-trip / transition-tree coverage is a validated cost-effective
middle ground for FSM testing (Binder; Utting & Legeard).

The FSM dict shape (produced by ``src/graph/builder.py``):

    {"states": [{"state_id", "name", ..., "is_initial", "is_terminal"}],
     "transitions": [{"from_state", "to_state", "trigger", "guard", "frequency"}]}

All functions degrade gracefully when the FSM (or the whole
behavioural_model section) is absent or malformed.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

MAX_ROUND_TRIP_PATHS = 20
_MAX_PATH_TRANSITIONS = 12  # depth cap per path (avoid combinatorial explosion)


def _clean_transitions(fsm: Optional[Dict]) -> List[Tuple[str, str, str]]:
    """Extract well-formed (from_state, trigger, to_state) triples,
    deduplicated and order-preserving."""
    if not fsm or not isinstance(fsm, dict):
        return []
    out: List[Tuple[str, str, str]] = []
    seen: Set[Tuple[str, str, str]] = set()
    for tr in fsm.get("transitions") or []:
        if not isinstance(tr, dict):
            continue
        frm = tr.get("from_state")
        to = tr.get("to_state")
        trig = tr.get("trigger")
        if not frm or not to or not trig:
            continue
        key = (str(frm), str(trig), str(to))
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def compute_all_transitions(fsm: Optional[Dict]) -> List[Tuple[str, str, str]]:
    """All-transitions (0-switch) coverage targets.

    Returns ``(from_state, trigger, to_state)`` triples — every FSM
    transition exercised at least once.
    """
    return _clean_transitions(fsm)


def compute_transition_pairs(fsm: Optional[Dict]) -> List[Tuple[str, str, str, str]]:
    """Transition-pair (1-switch) coverage targets.

    For each pair of consecutive transitions (T1, T2) with
    ``T1.to_state == T2.from_state``, returns a
    ``(state_A, trigger_1, state_B, trigger_2)`` tuple: exercising
    trigger_1 out of state_A reaches state_B, then trigger_2 fires.
    """
    transitions = _clean_transitions(fsm)
    by_from: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)
    for frm, trig, to in transitions:
        by_from[frm].append((frm, trig, to))

    pairs: List[Tuple[str, str, str, str]] = []
    seen: Set[Tuple[str, str, str, str]] = set()
    for frm, trig, to in transitions:
        for _f2, trig2, _t2 in by_from.get(to, []):
            key = (frm, trig, to, trig2)
            if key not in seen:
                seen.add(key)
                pairs.append(key)
    return pairs


def _state_flags(fsm: Dict) -> Tuple[List[str], Set[str]]:
    """Return (initial_state_ids, terminal_state_ids) from the FSM."""
    initial: List[str] = []
    terminal: Set[str] = set()
    for st in fsm.get("states") or []:
        if not isinstance(st, dict):
            continue
        sid = st.get("state_id") or st.get("name")
        if not sid:
            continue
        if st.get("is_initial"):
            initial.append(str(sid))
        if st.get("is_terminal"):
            terminal.add(str(sid))
    return initial, terminal


def compute_round_trip_paths(
    fsm: Optional[Dict],
    high_risk_tools: Optional[Set[str]] = None,
    max_paths: int = MAX_ROUND_TRIP_PATHS,
) -> List[List[str]]:
    """Round-trip path coverage targets.

    Finds paths from an initial state back to an initial state or to a
    terminal state, capped at ``max_paths`` (default 20).  Paths are
    returned as alternating state/trigger sequences, e.g.
    ``["S0", "check_order", "S1", "process_refund", "S3"]``.

    When ``high_risk_tools`` is given, paths whose triggers include more
    high-risk tools are prioritised (kept first when trimming to cap).
    """
    transitions = _clean_transitions(fsm)
    if not transitions:
        return []

    initial, terminal = _state_flags(fsm)
    if not initial:
        # Fall back: treat the most common source state as initial
        sources = [frm for frm, _t, _to in transitions]
        initial = [max(set(sources), key=sources.count)]

    by_from: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)
    for frm, trig, to in transitions:
        by_from[frm].append((frm, trig, to))

    initial_set = set(initial)
    goal_states = initial_set | terminal
    raw_paths: List[List[str]] = []
    # Generous exploration budget; final list is trimmed to max_paths
    exploration_cap = max_paths * 5

    def dfs(state: str, path: List[str], used: Set[Tuple[str, str, str]]) -> None:
        if len(raw_paths) >= exploration_cap:
            return
        if len(used) >= _MAX_PATH_TRANSITIONS:
            return
        for edge in by_from.get(state, []):
            if edge in used:
                continue  # do not reuse a transition within one path
            frm, trig, to = edge
            new_path = path + [trig, to]
            if to in goal_states and len(new_path) > 1:
                raw_paths.append(new_path)
                if len(raw_paths) >= exploration_cap:
                    return
            else:
                dfs(to, new_path, used | {edge})

    for start in initial:
        dfs(start, [start], set())

    if not raw_paths:
        return []

    high_risk = high_risk_tools or set()

    def priority(path: List[str]) -> Tuple[int, int]:
        triggers = path[1::2]
        risky = sum(1 for t in triggers if t in high_risk)
        # More high-risk triggers first, then shorter paths (cheaper)
        return (-risky, len(path))

    raw_paths.sort(key=priority)

    # Deduplicate while preserving priority order
    deduped: List[List[str]] = []
    seen: Set[Tuple[str, ...]] = set()
    for p in raw_paths:
        key = tuple(p)
        if key not in seen:
            seen.add(key)
            deduped.append(p)
        if len(deduped) >= max_paths:
            break
    return deduped


def extract_fsm(agent_map: Optional[Dict]) -> Optional[Dict]:
    """Fetch the FSM dict from an agent map, or None when absent."""
    if not agent_map:
        return None
    bm = agent_map.get("behavioural_model") or {}
    fsm = bm.get("fsm")
    if not fsm or not isinstance(fsm, dict) or not fsm.get("transitions"):
        return None
    return fsm
