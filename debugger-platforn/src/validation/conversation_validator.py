"""
ConversationValidator: filters fake failures and catches fake successes
between Phase C (execution) and Phase D (diagnosis).

Reviews each conversation transcript and classifies it as genuine or spurious,
so only real failures feed into clustering.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ValidationResult:
    genuine_failures: List[Dict] = field(default_factory=list)
    persona_failures: List[Dict] = field(default_factory=list)
    chaos_failures: List[Dict] = field(default_factory=list)
    false_successes: List[Dict] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)


def _load_trace(trace_file: str) -> Optional[Dict]:
    if not trace_file or not os.path.exists(trace_file):
        return None
    with open(trace_file) as f:
        return json.load(f)


def _parse_json_response(text: str) -> List[Dict]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        text = text.strip()
    return json.loads(text)


VALIDATION_PROMPT = """You are validating test conversations from an AI agent debugger.

For each conversation, determine if the result (pass/fail) is GENUINE or SPURIOUS.

A failure is SPURIOUS (persona_incompetence) when:
- The simulated user was unrealistically vague, contradictory, or hostile
- A real customer would never behave this way
- The persona changed their mind multiple times making it impossible to help them
- The persona refused to provide basic required information

A failure is SPURIOUS (chaos_induced) when:
- The failure was directly caused by injected chaos (timeout, malformed response)
- The agent handled the chaos reasonably but still couldn't complete

A success is SPURIOUS (false_success) when:
- Required tools were never called or called with wrong arguments
- The agent claimed to complete a task but the tool results show it didn't
- Critical validation steps were skipped
- The agent hallucinated a successful outcome

For each conversation below, output a JSON array with one entry per conversation:
[{{
  "test_id": "...",
  "verdict": "genuine_failure|persona_incompetence|chaos_induced|genuine_success|false_success",
  "confidence": 0.0-1.0,
  "reasoning": "1-2 sentence explanation"
}}]

Here are the conversations to validate:

{conversations}"""


class ConversationValidator:
    """Validate Phase C results to filter fake failures and catch fake successes."""

    BATCH_SIZE = 3

    def __init__(self, use_ai: bool = True, retry_config: Optional[Dict] = None):
        self.use_ai = use_ai
        self._retry_config = retry_config or {}

    def validate_results(
        self,
        failure_inbox: Dict,
        passed_results: List[Dict],
        agent_map: Dict,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> ValidationResult:
        """Review failures for fake failures, and passes for fake successes."""
        result = ValidationResult()
        failures = failure_inbox.get("failures", [])

        def _progress(msg: str):
            if on_progress:
                on_progress(msg)

        # Extract expected tools from agent map
        expected_tools = [
            t.get("name", "")
            for t in agent_map.get("components", {}).get("tools", [])
        ]

        # --- Validate failures ---
        _progress(f"Validating {len(failures)} failures...")
        failure_verdicts = self._validate_batch(failures, "failure", expected_tools, _progress)

        for failure, verdict in zip(failures, failure_verdicts):
            v = verdict.get("verdict", "genuine_failure")
            enriched = {**failure, "_validation": verdict}
            if v == "persona_incompetence":
                result.persona_failures.append(enriched)
            elif v == "chaos_induced":
                result.chaos_failures.append(enriched)
            else:
                result.genuine_failures.append(enriched)

        # --- Validate passes ---
        _progress(f"Scanning {len(passed_results)} passed tests for false successes...")
        pass_verdicts = self._validate_batch(passed_results, "success", expected_tools, _progress)

        for passed, verdict in zip(passed_results, pass_verdicts):
            v = verdict.get("verdict", "genuine_success")
            if v == "false_success":
                # Convert to failure format for Phase D
                result.false_successes.append({
                    "test_id": passed.get("test_id", ""),
                    "test_number": passed.get("test_number", 0),
                    "scenario": passed.get("scenario", ""),
                    "persona": passed.get("persona", ""),
                    "difficulty": passed.get("difficulty", ""),
                    "coverage_goal": passed.get("coverage_goal", ""),
                    "status": "failed",
                    "failure_reason": f"False success: {verdict.get('reasoning', 'validation detected fake pass')}",
                    "total_turns": passed.get("total_turns", 0),
                    "duration_sec": 0.0,
                    "cost_usd": 0.0,
                    "outcome": passed.get("outcome"),
                    "tools_called_sequence": passed.get("tools_called_sequence", []),
                    "tool_results": passed.get("tool_results", []),
                    "chaos_events": [],
                    "trace_file": passed.get("trace_file"),
                    "_validation": verdict,
                })

        result.summary = {
            "total_failures_reviewed": len(failures),
            "total_passes_reviewed": len(passed_results),
            "genuine_failures": len(result.genuine_failures),
            "persona_incompetence_filtered": len(result.persona_failures),
            "chaos_induced_filtered": len(result.chaos_failures),
            "false_successes_caught": len(result.false_successes),
        }

        return result

    # ------------------------------------------------------------------
    # Batch validation dispatcher
    # ------------------------------------------------------------------

    def _validate_batch(
        self,
        items: List[Dict],
        mode: str,  # "failure" or "success"
        expected_tools: List[str],
        progress: Callable[[str], None],
    ) -> List[Dict]:
        """Validate a list of items, returning one verdict per item."""
        if not items:
            return []

        if self.use_ai:
            try:
                return self._ai_validate_all(items, mode, expected_tools, progress)
            except Exception as e:
                progress(f"AI validation failed ({e}), falling back to heuristics")

        return [self._heuristic_validate(item, mode, expected_tools) for item in items]

    # ------------------------------------------------------------------
    # AI-powered validation
    # ------------------------------------------------------------------

    def _ai_validate_all(
        self,
        items: List[Dict],
        mode: str,
        expected_tools: List[str],
        progress: Callable[[str], None],
    ) -> List[Dict]:
        from anthropic import Anthropic

        client = Anthropic()
        all_verdicts: List[Dict] = []

        for i in range(0, len(items), self.BATCH_SIZE):
            batch = items[i : i + self.BATCH_SIZE]
            progress(f"  AI validating batch {i // self.BATCH_SIZE + 1} ({len(batch)} items)...")

            conversations_text = self._format_batch(batch, mode, expected_tools)
            prompt = VALIDATION_PROMPT.format(conversations=conversations_text)

            max_retries = self._retry_config.get("max_retries", 3)
            backoff_base = self._retry_config.get("backoff_base", 2.0)

            verdicts = None
            for attempt in range(max_retries):
                try:
                    response = client.messages.create(
                        model="claude-sonnet-4-5-20250514",
                        max_tokens=1024,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    raw = response.content[0].text
                    verdicts = _parse_json_response(raw)
                    break
                except Exception:
                    if attempt < max_retries - 1:
                        import time
                        time.sleep(backoff_base ** attempt)
                    else:
                        raise

            if verdicts and len(verdicts) == len(batch):
                all_verdicts.extend(verdicts)
            else:
                # Fallback to heuristic for this batch
                for item in batch:
                    all_verdicts.append(self._heuristic_validate(item, mode, expected_tools))

        return all_verdicts

    def _format_batch(
        self, items: List[Dict], mode: str, expected_tools: List[str]
    ) -> str:
        parts = []
        for idx, item in enumerate(items, 1):
            test_id = item.get("test_id", f"unknown-{idx}")
            scenario = item.get("scenario", "N/A")
            persona = item.get("persona", "N/A")
            tools_called = item.get("tools_called_sequence", [])
            outcome = item.get("outcome", "N/A")

            # Load trace for conversation transcript
            trace = _load_trace(item.get("trace_file"))
            transcript = "No trace available"
            if trace:
                turns = trace.get("turns", [])
                lines = []
                for t in turns[:20]:  # Cap at 20 turns
                    role = t.get("role", "?")
                    msg = t.get("message", "")[:300]
                    lines.append(f"  [{role}]: {msg}")
                transcript = "\n".join(lines) if lines else "Empty conversation"

            chaos = item.get("chaos_events", [])
            chaos_text = f"Chaos events: {json.dumps(chaos)}" if chaos else "No chaos events"

            if mode == "failure":
                failure_reason = item.get("failure_reason", "N/A")
                parts.append(
                    f"--- Conversation {idx} (FAILED) ---\n"
                    f"Test ID: {test_id}\n"
                    f"Scenario: {scenario}\n"
                    f"Persona: {persona}\n"
                    f"Failure reason: {failure_reason}\n"
                    f"Tools called: {tools_called}\n"
                    f"Expected tools: {expected_tools}\n"
                    f"{chaos_text}\n"
                    f"Transcript:\n{transcript}\n"
                )
            else:
                parts.append(
                    f"--- Conversation {idx} (PASSED) ---\n"
                    f"Test ID: {test_id}\n"
                    f"Scenario: {scenario}\n"
                    f"Persona: {persona}\n"
                    f"Outcome: {outcome}\n"
                    f"Tools called: {tools_called}\n"
                    f"Expected tools: {expected_tools}\n"
                    f"{chaos_text}\n"
                    f"Transcript:\n{transcript}\n"
                )

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Heuristic fallback
    # ------------------------------------------------------------------

    def _heuristic_validate(
        self, item: Dict, mode: str, expected_tools: List[str]
    ) -> Dict:
        test_id = item.get("test_id", "unknown")

        if mode == "failure":
            return self._heuristic_failure(item, test_id)
        else:
            return self._heuristic_success(item, test_id, expected_tools)

    def _heuristic_failure(self, item: Dict, test_id: str) -> Dict:
        chaos_events = item.get("chaos_events", [])
        failure_reason = (item.get("failure_reason") or "").lower()

        # Check chaos-induced
        if chaos_events:
            chaos_types = {e.get("chaos_type", "") if isinstance(e, dict) else "" for e in chaos_events}
            chaos_keywords = {"timeout", "malformed", "error", "conflict"}
            if chaos_types & chaos_keywords or any(kw in failure_reason for kw in ("chaos", "timeout", "malformed")):
                return {
                    "test_id": test_id,
                    "verdict": "chaos_induced",
                    "confidence": 0.7,
                    "reasoning": "Failure correlates with injected chaos events",
                }

        # Check persona incompetence via trace
        trace = _load_trace(item.get("trace_file"))
        if trace:
            persona_traits = trace.get("persona", {}).get("traits", {})
            changes_mind = persona_traits.get("changes_mind", False)
            incomplete_info = persona_traits.get("provides_incomplete_info", False)
            patience = persona_traits.get("patience", 5)

            if changes_mind and incomplete_info and patience <= 2:
                return {
                    "test_id": test_id,
                    "verdict": "persona_incompetence",
                    "confidence": 0.65,
                    "reasoning": "Persona has contradictory traits: changes mind, provides incomplete info, and very low patience",
                }

        return {
            "test_id": test_id,
            "verdict": "genuine_failure",
            "confidence": 0.5,
            "reasoning": "Heuristic fallback: no indicators of spurious failure detected",
        }

    def _heuristic_success(
        self, item: Dict, test_id: str, expected_tools: List[str]
    ) -> Dict:
        tools_called = item.get("tools_called_sequence", [])

        # If no tools were called at all but expected tools exist → suspicious
        if expected_tools and not tools_called:
            return {
                "test_id": test_id,
                "verdict": "false_success",
                "confidence": 0.7,
                "reasoning": "No tools were called despite expected tools existing in agent map",
            }

        # Check tool results for errors
        tool_results = item.get("tool_results", [])
        if tool_results:
            error_count = sum(
                1 for tr in tool_results
                if isinstance(tr, dict) and tr.get("error")
            )
            if error_count > 0 and error_count == len(tool_results):
                return {
                    "test_id": test_id,
                    "verdict": "false_success",
                    "confidence": 0.6,
                    "reasoning": "All tool calls returned errors yet test was marked as passed",
                }

        return {
            "test_id": test_id,
            "verdict": "genuine_success",
            "confidence": 0.5,
            "reasoning": "Heuristic fallback: no indicators of false success detected",
        }
