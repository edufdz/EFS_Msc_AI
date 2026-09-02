#!/usr/bin/env python3
"""Recompute an agent map's derived language fields with the current detectors.

Phase A's guardrail-language detection was fixed (word-boundary matching,
accent folding, and a single shared scorer instead of two that disagreed).
Maps generated before that fix carry stale values -- and, worse, two
contradictory ones: ``guardrails.guardrail_language`` said English while
``metadata.language.guardrail_language`` said Spanish for the same rules.

Rather than re-running the whole Phase A pipeline (which would perturb the
LLM-derived fields and invalidate artefacts the study depends on), this script
recomputes only the fields that are *derived from rule text already stored in
the map*:

    guardrails.rules[].language
    guardrails.guardrail_language
    guardrails.guardrail_language_matches_conversation
    metadata.language.guardrail_language
    metadata.language.language_mismatch

Everything else is left byte-identical. Use --check to report drift without
writing (suitable for CI).

Usage:
    python3 refresh_map_language.py MAP.json [MAP.json ...] [--check] [--no-backup]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.patterns.rule_extractor import _detect_rule_language


def recompute(agent_map: dict) -> tuple[dict, dict]:
    """Return (new_values, old_values) for the derived language fields."""
    guardrails = agent_map.get("guardrails") or {}
    rules = guardrails.get("rules") or []
    meta_lang = (agent_map.get("metadata") or {}).get("language") or {}

    old = {
        "guardrail_language": guardrails.get("guardrail_language"),
        "guardrail_language_matches_conversation": guardrails.get(
            "guardrail_language_matches_conversation"
        ),
        "metadata_guardrail_language": meta_lang.get("guardrail_language"),
        "metadata_language_mismatch": meta_lang.get("language_mismatch"),
        "per_rule": dict(Counter(r.get("language") for r in rules)),
    }

    per_rule = [_detect_rule_language(r.get("text") or "") for r in rules]
    majority = Counter(per_rule).most_common(1)[0][0] if per_rule else "English"
    primary = meta_lang.get("primary_language", "English")

    new = {
        "guardrail_language": majority,
        "guardrail_language_matches_conversation": majority == primary,
        "metadata_guardrail_language": majority,
        "metadata_language_mismatch": majority != primary,
        "per_rule": dict(Counter(per_rule)),
        "_per_rule_list": per_rule,
        "_primary_language": primary,
    }
    return new, old


def apply(agent_map: dict, new: dict) -> None:
    guardrails = agent_map.setdefault("guardrails", {})
    for rule, lang in zip(guardrails.get("rules") or [], new["_per_rule_list"]):
        rule["language"] = lang
    guardrails["guardrail_language"] = new["guardrail_language"]
    guardrails["guardrail_language_matches_conversation"] = new[
        "guardrail_language_matches_conversation"
    ]
    meta_lang = agent_map.setdefault("metadata", {}).setdefault("language", {})
    meta_lang["guardrail_language"] = new["metadata_guardrail_language"]
    meta_lang["language_mismatch"] = new["metadata_language_mismatch"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("maps", nargs="+", type=Path)
    ap.add_argument("--check", action="store_true",
                    help="Report drift and exit non-zero; do not write.")
    ap.add_argument("--no-backup", action="store_true",
                    help="Do not write a .bak alongside the map.")
    args = ap.parse_args()

    drifted = 0
    for path in args.maps:
        if not path.is_file():
            print(f"!! {path}: not found")
            drifted += 1
            continue

        agent_map = json.loads(path.read_text(encoding="utf-8"))
        new, old = recompute(agent_map)

        changed = [
            k for k in (
                "guardrail_language",
                "guardrail_language_matches_conversation",
                "metadata_guardrail_language",
                "metadata_language_mismatch",
            )
            if old[k] != new[k]
        ] or ([] if old["per_rule"] == new["per_rule"] else ["rules[].language"])

        print(f"\n{path}")
        print(f"  primary_language                : {new['_primary_language']}")
        print(f"  per-rule  {old['per_rule']}  ->  {new['per_rule']}")
        print(f"  guardrail_language              : {old['guardrail_language']} -> {new['guardrail_language']}")
        print(f"  ...matches_conversation         : {old['guardrail_language_matches_conversation']} -> {new['guardrail_language_matches_conversation']}")
        print(f"  metadata.guardrail_language     : {old['metadata_guardrail_language']} -> {new['metadata_guardrail_language']}")
        print(f"  metadata.language_mismatch      : {old['metadata_language_mismatch']} -> {new['metadata_language_mismatch']}")

        if not changed:
            print("  => already current")
            continue

        drifted += 1
        if args.check:
            print(f"  => STALE ({', '.join(changed)})")
            continue

        if not args.no_backup:
            shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
        apply(agent_map, new)
        path.write_text(json.dumps(agent_map, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        print(f"  => updated ({', '.join(changed)})")

    if args.check and drifted:
        print(f"\n{drifted} map(s) stale. Run without --check to update.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
