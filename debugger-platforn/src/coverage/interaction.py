"""
Interaction (t-way) coverage — Sprint E3.

Implements a covering-array generator based on the IPOG algorithm
(In-Parameter-Order-General, Lei et al. 2007) and a factor extractor
that turns an Agent Map's high/critical tools and their key parameter
values into combinatorial test factors.

Rationale (NIST interaction rule, Kuhn, Wallace & Gallo, IEEE TSE 2004):
~67% of faults are triggered by single factors, ~93% by 2-way
interactions, ~98% by 3-way.  A pairwise (t=2) covering array therefore
exercises the fault space far more efficiently than flat per-tool
repetition (critical=25x etc.), which finds almost nothing new after
the first few identical calls.
"""

from __future__ import annotations

import re
from itertools import combinations, product
from typing import Dict, List, Optional, Tuple

# Keep covering arrays manageable
MAX_FACTORS = 10
MAX_LEVELS_PER_FACTOR = 6

# A t-way "tuple" is a frozenset of (factor_name, level) assignments
_TupleKey = frozenset


# ---------------------------------------------------------------------------
# Covering array generation (IPOG)
# ---------------------------------------------------------------------------

def _normalize_factors(factors: List[Dict]) -> List[Dict]:
    """Validate and clean the factor list: unique names, non-empty
    string levels, deduplicated levels, capped level count."""
    cleaned: List[Dict] = []
    seen_names: set = set()
    for f in factors or []:
        name = f.get("name")
        levels = f.get("levels") or []
        if not name or name in seen_names:
            continue
        # Dedupe levels preserving order, coerce to str
        uniq: List[str] = []
        for lv in levels:
            lv = str(lv)
            if lv not in uniq:
                uniq.append(lv)
        if not uniq:
            continue
        seen_names.add(name)
        cleaned.append({"name": name, "levels": uniq[:MAX_LEVELS_PER_FACTOR]})
    return cleaned


def _tuples_for_factor_sets(
    factor_sets: List[Tuple[Dict, ...]],
) -> set:
    """All t-way value tuples for the given combinations of factors."""
    tuples: set = set()
    for fset in factor_sets:
        names = [f["name"] for f in fset]
        for values in product(*(f["levels"] for f in fset)):
            tuples.add(_TupleKey(zip(names, values)))
    return tuples


def _row_covers(row: Dict[str, str], tup: _TupleKey) -> bool:
    return all(row.get(name) == level for name, level in tup)


def generate_covering_array(factors: List[Dict], strength: int = 2) -> List[Dict]:
    """Generate a t-way covering array over the given factors.

    Parameters
    ----------
    factors : list of ``{"name": str, "levels": list[str]}``
    strength : int
        Interaction strength t (default 2 = pairwise).

    Returns
    -------
    list[dict]
        Test configurations; each row maps every factor name to one of
        its levels.  Every combination of ``strength`` factor-levels is
        guaranteed to appear in at least one row.

    Uses the IPOG construction: build an exhaustive array over the
    first t factors, then extend one factor at a time via horizontal
    growth (greedy level choice per existing row) and vertical growth
    (new rows for still-uncovered tuples), with don't-care back-fill.
    """
    factors = _normalize_factors(factors)
    if not factors:
        return []

    t = max(1, min(int(strength), len(factors)))

    if t == 1 or len(factors) == 1:
        # Each-choice coverage: enough rows to see every level of every factor
        n_rows = max(len(f["levels"]) for f in factors)
        return [
            {f["name"]: f["levels"][min(i, len(f["levels"]) - 1)] for f in factors}
            for i in range(n_rows)
        ]

    # IPOG works best when factors are ordered by descending level count
    ordered = sorted(factors, key=lambda f: -len(f["levels"]))

    # --- Initial exhaustive array over the first t factors ---
    first = ordered[:t]
    names_first = [f["name"] for f in first]
    rows: List[Dict[str, str]] = [
        dict(zip(names_first, values))
        for values in product(*(f["levels"] for f in first))
    ]

    # --- Extend one factor at a time ---
    for i in range(t, len(ordered)):
        fac = ordered[i]
        fname, flevels = fac["name"], fac["levels"]

        # Uncovered t-way tuples involving the new factor and (t-1) of
        # the already-placed factors
        prior_sets = [
            tuple(list(combo) + [fac])
            for combo in combinations(ordered[:i], t - 1)
        ]
        uncovered = _tuples_for_factor_sets(prior_sets)

        # Horizontal growth: assign the level that covers the most
        # still-uncovered tuples to each existing row
        for row in rows:
            best_level, best_covered = flevels[0], None
            for level in flevels:
                row[fname] = level
                covered = {tup for tup in uncovered if _row_covers(row, tup)}
                if best_covered is None or len(covered) > len(best_covered):
                    best_level, best_covered = level, covered
            row[fname] = best_level
            uncovered -= best_covered or set()

        # Vertical growth: place remaining tuples into rows with
        # don't-cares, or create new partial rows
        for tup in sorted(uncovered, key=lambda k: sorted(k)):
            assignments = dict(tup)
            placed = False
            for row in rows:
                if all(row.get(n) in (None, v) for n, v in assignments.items()):
                    row.update(assignments)
                    placed = True
                    break
            if not placed:
                rows.append(dict(assignments))
        uncovered = set()

    # --- Fill remaining don't-cares deterministically ---
    for row in rows:
        for f in ordered:
            if row.get(f["name"]) is None:
                row[f["name"]] = f["levels"][0]

    # Preserve the caller's factor order in each row
    caller_order = [f["name"] for f in factors]
    return [{n: row[n] for n in caller_order} for row in rows]


def verify_covering_array(
    rows: List[Dict], factors: List[Dict], strength: int = 2
) -> bool:
    """True if every t-way factor-level combination appears in some row."""
    factors = _normalize_factors(factors)
    if not factors:
        return True
    t = max(1, min(int(strength), len(factors)))
    required = _tuples_for_factor_sets(list(combinations(factors, t)))
    for row in rows:
        required = {tup for tup in required if not _row_covers(row, tup)}
    return not required


# ---------------------------------------------------------------------------
# Factor extraction from the Agent Map
# ---------------------------------------------------------------------------

_NOT_NONE_RE = re.compile(
    r"(must not be (none|null|empty)|is required|cannot be (none|null|empty)|required)",
    re.IGNORECASE,
)
_POSITIVE_RE = re.compile(r"(>\s*0|positive|greater than (zero|0))", re.IGNORECASE)

_TYPE_LEVELS: Dict[str, List[str]] = {
    "str": ["typical", "empty", "very_long"],
    "string": ["typical", "empty", "very_long"],
    "int": ["typical", "zero", "large"],
    "integer": ["typical", "zero", "large"],
    "float": ["typical", "zero", "large"],
    "number": ["typical", "zero", "large"],
    "bool": ["true", "false"],
    "boolean": ["true", "false"],
}


def _param_levels(param: Dict, preconditions: List[str]) -> List[str]:
    """Derive boundary levels for one tool parameter, using its declared
    type and any preconditions that mention it."""
    ptype = str(param.get("type", "str")).lower()
    # list types like "list[str]"
    base = _TYPE_LEVELS.get(ptype.split("[")[0], ["typical", "boundary"])
    levels = list(base)

    pname = param.get("name", "")
    mentions = [p for p in preconditions if pname and pname in str(p)]
    for pre in mentions:
        pre_s = str(pre)
        if _NOT_NONE_RE.search(pre_s) and "missing" not in levels:
            # Boundary the guard: what if the parameter is absent/None?
            levels.append("missing")
        if _POSITIVE_RE.search(pre_s) and "negative" not in levels:
            levels.append("negative")

    # Parameters with defaults can also be omitted legitimately
    if param.get("default") is not None and "default" not in levels:
        levels.append("default")

    return levels[:MAX_LEVELS_PER_FACTOR]


def extract_factors_from_agent_map(agent_map: Dict) -> List[Dict]:
    """Extract combinatorial test factors from an agent map.

    - One "tool" factor whose levels are the high/critical-risk tool
      names (interaction between which tool is exercised and the shape
      of its inputs).
    - One factor per key parameter of those tools, with boundary levels
      derived from the declared type and preconditions.
    - Capped at ``MAX_FACTORS`` factors (tool factor first, then
      parameters of critical tools before high tools).

    Returns an empty list when the map has fewer than two high/critical
    tools and no parameter information (caller should fall back to
    legacy pairwise tool combinations).
    """
    tools = (agent_map or {}).get("components", {}).get("tools", []) or []

    # Dedupe by name, keep order
    seen: set = set()
    unique_tools: List[Dict] = []
    for tool in tools:
        name = tool.get("name")
        if not name or name in seen:
            continue
        seen.add(name)
        unique_tools.append(tool)

    risky = [
        t for t in unique_tools
        if t.get("risk_level") in ("critical", "high")
    ]
    if not risky:
        return []

    factors: List[Dict] = []

    # Factor 1: which risky tool is exercised
    tool_levels = [t["name"] for t in risky][:MAX_LEVELS_PER_FACTOR]
    if len(tool_levels) >= 2:
        factors.append({"name": "tool", "levels": tool_levels})

    # Parameter factors: critical tools first, then high
    ranked = sorted(risky, key=lambda t: 0 if t.get("risk_level") == "critical" else 1)
    for tool in ranked:
        preconditions = [str(p) for p in (tool.get("preconditions") or [])]
        for param in tool.get("parameters") or []:
            if len(factors) >= MAX_FACTORS:
                return factors
            pname = param.get("name")
            if not pname:
                continue
            levels = _param_levels(param, preconditions)
            if len(levels) >= 2:
                factors.append({
                    "name": f"{tool['name']}.{pname}",
                    "levels": levels,
                })

    return factors[:MAX_FACTORS]


def tool_of_row(row: Dict[str, str]) -> Optional[str]:
    """The tool a covering-array row targets, if it has a tool factor.

    Falls back to the tool prefix of the first ``tool.param`` factor."""
    if not row:
        return None
    if "tool" in row:
        return row["tool"]
    for name in row:
        if "." in name:
            return name.split(".", 1)[0]
    return None
