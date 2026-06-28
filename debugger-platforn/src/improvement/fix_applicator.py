"""
FixApplicationEngine: applies proposed fixes from Phase D to the agent.

Supports prompt patches, config changes, code changes, validation rules,
and tool-schema fixes.  Every mutation is recorded as an AppliedFix with
before/after diff so it can be rolled back.
"""

from __future__ import annotations

import difflib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from .models import AppliedFix, FixStatus


class FixApplicationEngine:
    """Apply Phase D fixes to an agent's source tree."""

    def __init__(self, agent_map: Dict, agent_source_dir: Path):
        self.agent_map = agent_map
        self.agent_source_dir = agent_source_dir
        self.applied_fixes: List[AppliedFix] = []

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def apply_fixes(
        self,
        proposed_fixes: List[Dict],
        dry_run: bool = True,
    ) -> List[AppliedFix]:
        """Apply all proposed fixes and return records.

        Args:
            proposed_fixes: list of fix dicts from Phase D
            dry_run: if True nothing is written to disk
        """
        applied: List[AppliedFix] = []

        for fix in proposed_fixes:
            try:
                handler = {
                    "prompt_patch": self._apply_prompt_patch,
                    "code_change": self._apply_code_change,
                    "config_change": self._apply_config_change,
                    "validation_rule": self._apply_validation_rule,
                    "tool_fix": self._apply_tool_fix,
                }.get(fix.get("fix_type", ""))

                if handler is None:
                    applied.append(self._skipped(fix, f"Unknown fix type: {fix.get('fix_type')}"))
                    continue

                result = handler(fix, dry_run)
                applied.append(result)

            except Exception as exc:
                applied.append(self._failed(fix, str(exc)))

        self.applied_fixes = applied
        return applied

    def rollback_fix(self, fix: AppliedFix) -> bool:
        """Mark a fix as rolled back (actual revert is manual)."""
        if not fix.can_rollback:
            return False
        fix.status = FixStatus.ROLLED_BACK
        return True

    # ------------------------------------------------------------------
    # Fix-type handlers
    # ------------------------------------------------------------------

    def _apply_prompt_patch(self, fix: Dict, dry_run: bool) -> AppliedFix:
        changes = fix.get("changes", {})
        new_text = changes.get("new_text") or changes.get("add_to_prompt", "")
        if not new_text:
            new_text = fix.get("description", "")

        # Locate prompt file from agent_map
        prompts = self.agent_map.get("components", {}).get("prompts", [])
        prompt_file = None
        current_prompt = ""
        if prompts:
            prompt_file = prompts[0].get("file_path")
            if prompt_file:
                p = self.agent_source_dir / prompt_file
                if p.exists():
                    current_prompt = p.read_text()
                else:
                    current_prompt = prompts[0].get("content", "")
            else:
                current_prompt = prompts[0].get("content", "")

        location = changes.get("location", "end_of_system_prompt")
        if location in ("beginning", "start"):
            new_prompt = new_text + "\n\n" + current_prompt
        else:
            new_prompt = current_prompt + "\n\n" + new_text

        diff = _diff(current_prompt, new_prompt)

        if not dry_run and prompt_file:
            target = self.agent_source_dir / prompt_file
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(new_prompt)

        return AppliedFix(
            fix_id=fix["fix_id"],
            cluster_id=fix.get("cluster_id", ""),
            fix_type="prompt_patch",
            status=FixStatus.APPLIED if not dry_run else FixStatus.PENDING,
            applied_at=datetime.now(timezone.utc),
            applied_to=str(prompt_file or "inline_prompt"),
            before=current_prompt[:500],
            after=new_prompt[:500],
            diff=diff,
            rollback_instructions="Restore original prompt from backup",
        )

    def _apply_code_change(self, fix: Dict, dry_run: bool) -> AppliedFix:
        changes = fix.get("changes", {})
        component = changes.get("component", "orchestrator")
        modification = changes.get("modification", fix.get("description", ""))
        rationale = changes.get("rationale", "")

        comment_block = (
            f"\n# FIX: {fix.get('description', '')}\n"
            f"# Component: {component}\n"
            f"# Rationale: {rationale}\n"
            f"# TODO: Review and integrate this change\n"
        )

        target_file = changes.get("file")
        if target_file:
            target = self.agent_source_dir / target_file
        else:
            target = self.agent_source_dir / "agent_fixes.py"

        current = target.read_text() if target.exists() else ""
        new_content = current + comment_block

        diff = _diff(current, new_content)

        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(new_content)

        return AppliedFix(
            fix_id=fix["fix_id"],
            cluster_id=fix.get("cluster_id", ""),
            fix_type="code_change",
            status=FixStatus.APPLIED if not dry_run else FixStatus.PENDING,
            applied_at=datetime.now(timezone.utc),
            applied_to=str(target),
            before=current[:500],
            after=new_content[:500],
            diff=diff,
            rollback_instructions=f"Revert file: {target}",
        )

    def _apply_config_change(self, fix: Dict, dry_run: bool) -> AppliedFix:
        changes = fix.get("changes", {})

        config_path = self.agent_source_dir / "config.json"
        config: Dict[str, Any] = {}
        if config_path.exists():
            config = json.loads(config_path.read_text())

        before_snapshot = json.dumps(config, indent=2)

        # Merge all key/value pairs from changes into config
        for key, value in changes.items():
            if key == "rationale":
                continue
            if isinstance(value, dict) and "proposed" in value:
                config[key] = value["proposed"]
            else:
                config[key] = value

        after_snapshot = json.dumps(config, indent=2)
        diff = _diff(before_snapshot, after_snapshot)

        if not dry_run:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(after_snapshot)

        return AppliedFix(
            fix_id=fix["fix_id"],
            cluster_id=fix.get("cluster_id", ""),
            fix_type="config_change",
            status=FixStatus.APPLIED if not dry_run else FixStatus.PENDING,
            applied_at=datetime.now(timezone.utc),
            applied_to=str(config_path),
            before=before_snapshot[:500],
            after=after_snapshot[:500],
            diff=diff,
            rollback_instructions="Restore config.json from backup",
        )

    def _apply_validation_rule(self, fix: Dict, dry_run: bool) -> AppliedFix:
        changes = fix.get("changes", {})
        condition = changes.get("condition", fix.get("description", ""))
        action = changes.get("action", "fallback")

        rule = {
            "validation_type": changes.get("validation_type", "output"),
            "condition": condition,
            "error_message": changes.get("error_message", ""),
            "action": action,
        }

        rules_path = self.agent_source_dir / "validation_rules.json"
        existing: List[Dict] = []
        if rules_path.exists():
            existing = json.loads(rules_path.read_text())

        before = json.dumps(existing, indent=2)
        existing.append(rule)
        after = json.dumps(existing, indent=2)

        if not dry_run:
            rules_path.parent.mkdir(parents=True, exist_ok=True)
            rules_path.write_text(after)

        return AppliedFix(
            fix_id=fix["fix_id"],
            cluster_id=fix.get("cluster_id", ""),
            fix_type="validation_rule",
            status=FixStatus.APPLIED if not dry_run else FixStatus.PENDING,
            applied_at=datetime.now(timezone.utc),
            applied_to=str(rules_path),
            before=before[:500],
            after=after[:500],
            diff=_diff(before, after),
            rollback_instructions="Remove last rule from validation_rules.json",
        )

    def _apply_tool_fix(self, fix: Dict, dry_run: bool) -> AppliedFix:
        changes = fix.get("changes", {})
        affected_tools = changes.get("affected_tools", [])
        modification = changes.get("modification", fix.get("description", ""))

        description_text = (
            f"Tool fix for {', '.join(affected_tools)}: {modification}"
        )

        return AppliedFix(
            fix_id=fix["fix_id"],
            cluster_id=fix.get("cluster_id", ""),
            fix_type="tool_fix",
            status=FixStatus.PENDING,  # always manual review for tool changes
            applied_at=datetime.now(timezone.utc),
            applied_to=f"Tools: {', '.join(affected_tools)}",
            before=None,
            after=description_text,
            diff=None,
            rollback_instructions="Revert tool definitions in agent_map",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _skipped(fix: Dict, reason: str) -> AppliedFix:
        return AppliedFix(
            fix_id=fix.get("fix_id", "unknown"),
            cluster_id=fix.get("cluster_id", ""),
            fix_type=fix.get("fix_type", "unknown"),
            status=FixStatus.SKIPPED,
            applied_at=datetime.now(timezone.utc),
            applied_to=f"Skipped: {reason}",
        )

    @staticmethod
    def _failed(fix: Dict, reason: str) -> AppliedFix:
        return AppliedFix(
            fix_id=fix.get("fix_id", "unknown"),
            cluster_id=fix.get("cluster_id", ""),
            fix_type=fix.get("fix_type", "unknown"),
            status=FixStatus.FAILED,
            applied_at=datetime.now(timezone.utc),
            applied_to=f"Failed: {reason}",
        )


def _diff(before: str, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile="before",
            tofile="after",
        )
    )
