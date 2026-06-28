"""
CriticAgent — the Discriminator in the GAN-style testing architecture.

Observes conversations between the Generator (persona simulator) and the
agent under test, then provides:

  - **verdict**: continue | restart | flag
  - **reasoning**: why the conversation is (or isn't) on track
  - **coaching**: advice for the Generator to improve its next message
  - **false_positive_check**: whether a detected "failure" is actually fine
  - **quality_score**: 0-10 rating of conversation pertinence

Design principles:
  - Uses a CHEAP model (Haiku) — the Generator also uses Haiku, so the
    pair self-corrects without needing an expensive model.
  - Stateless per call — receives the full conversation context each time.
  - Returns structured JSON for easy integration into the simulation loop.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .llm_config import LLMProviderConfig

logger = logging.getLogger(__name__)

@dataclass
class CriticVerdict:
    """Structured output from the Critic agent."""

    action: str  # "continue" | "restart" | "flag"
    quality_score: float  # 0-10
    reasoning: str
    coaching: str  # advice for the Generator
    is_false_positive: bool  # if a failure was flagged, is it actually fine?
    false_positive_reason: str  # explanation if is_false_positive is True
    confidence: float  # 0-1, how sure the Critic is

    # Cost tracking
    tokens_used: int = 0
    cost_usd: float = 0.0


@dataclass
class CriticMetrics:
    """Accumulated metrics across all Critic evaluations in a test."""

    total_evaluations: int = 0
    restarts_requested: int = 0
    flags_raised: int = 0
    false_positives_caught: int = 0
    avg_quality_score: float = 0.0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    coaching_messages: List[str] = field(default_factory=list)

    def record(self, verdict: CriticVerdict) -> None:
        self.total_evaluations += 1
        self.total_tokens += verdict.tokens_used
        self.total_cost_usd += verdict.cost_usd

        if verdict.action == "restart":
            self.restarts_requested += 1
        elif verdict.action == "flag":
            self.flags_raised += 1
        if verdict.is_false_positive:
            self.false_positives_caught += 1
        if verdict.coaching:
            self.coaching_messages.append(verdict.coaching)

        # Running average
        n = self.total_evaluations
        self.avg_quality_score = (
            (self.avg_quality_score * (n - 1) + verdict.quality_score) / n
        )


class CriticAgent:
    """
    The Discriminator: evaluates ongoing conversations for quality,
    relevance, and false positives.

    Parameters
    ----------
    model : str
        LLM model to use. Defaults to Haiku for cost efficiency.
    evaluate_every : int
        Evaluate every N turns (default 2 = every other turn).
    max_restarts : int
        Maximum times the Critic can request a restart before giving up.
    quality_threshold : float
        Below this score, the Critic requests a restart (0-10).
    """

    def __init__(
        self,
        model: str = "claude-haiku-4-5",
        evaluate_every: int = 2,
        max_restarts: int = 2,
        quality_threshold: float = 3.0,
        provider_config: Optional[LLMProviderConfig] = None,
    ):
        self._provider_config = provider_config or LLMProviderConfig(model=model)
        self.model = self._provider_config.resolved_model
        self.evaluate_every = evaluate_every
        self.max_restarts = max_restarts
        self.quality_threshold = quality_threshold
        self.metrics = CriticMetrics()
        self._client = None  # lazy-init, reused across calls

    def _get_client(self):
        """Return a shared LLM client (Anthropic or OpenAI-compatible), created once."""
        if self._client is None:
            self._client = self._provider_config.create_async_client()
        return self._client

    def should_evaluate(self, turn_number: int) -> bool:
        """Decide if the Critic should evaluate at this turn."""
        return turn_number > 0 and turn_number % self.evaluate_every == 0

    async def evaluate(
        self,
        conversation: List[Dict[str, str]],
        scenario: Dict[str, Any],
        persona: Dict[str, Any],
        current_failure_reason: Optional[str] = None,
    ) -> CriticVerdict:
        """
        Evaluate the conversation so far (mid-conversation check).

        Parameters
        ----------
        conversation : list of {"role": "user"|"agent", "message": str}
        scenario : the test scenario dict (user_goal, success_conditions, etc.)
        persona : the persona dict (traits, style, edge_behaviors)
        current_failure_reason : if the test would currently be marked as failed

        Returns
        -------
        CriticVerdict with action, coaching, and false positive analysis.
        """
        prompt = self._build_prompt(conversation, scenario, persona, current_failure_reason)

        try:
            verdict = await self._call_llm(prompt)
        except Exception as e:
            logger.warning("Critic LLM call failed: %s — defaulting to continue", e)
            verdict = CriticVerdict(
                action="continue",
                quality_score=5.0,
                reasoning=f"Critic evaluation failed: {e}",
                coaching="",
                is_false_positive=False,
                false_positive_reason="",
                confidence=0.0,
            )

        self.metrics.record(verdict)
        return verdict

    async def evaluate_final(
        self,
        conversation: List[Dict[str, str]],
        scenario: Dict[str, Any],
        persona: Dict[str, Any],
        test_success: bool,
        failure_reason: Optional[str] = None,
    ) -> CriticVerdict:
        """
        Final evaluation after conversation ends.
        Focuses on false positive / false negative detection.
        """
        prompt = self._build_final_prompt(
            conversation, scenario, persona, test_success, failure_reason
        )

        try:
            verdict = await self._call_llm(prompt)
        except Exception as e:
            logger.warning("Critic final eval failed: %s", e)
            verdict = CriticVerdict(
                action="flag" if not test_success else "continue",
                quality_score=5.0,
                reasoning=f"Final evaluation failed: {e}",
                coaching="",
                is_false_positive=False,
                false_positive_reason="",
                confidence=0.0,
            )

        self.metrics.record(verdict)
        return verdict

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_prompt(
        self,
        conversation: List[Dict[str, str]],
        scenario: Dict[str, Any],
        persona: Dict[str, Any],
        current_failure_reason: Optional[str],
    ) -> str:
        conv_text = self._format_conversation(conversation)
        failure_ctx = ""
        if current_failure_reason:
            failure_ctx = (
                f"\nThe test engine currently marks this as FAILED with reason: "
                f'"{current_failure_reason}"\n'
                f"Evaluate whether this is a genuine failure or a FALSE POSITIVE "
                f"(the agent actually handled it correctly but the test logic misjudged).\n"
            )

        return f"""You are a Critic Agent evaluating a test conversation between a simulated user persona and an AI agent under test.

## Scenario
- Goal: {scenario.get('user_goal', 'unknown')}
- Type: {scenario.get('category', 'unknown')}
- Required tools: {scenario.get('required_tools', [])}
- Success conditions: {json.dumps(scenario.get('success_conditions', {}), indent=2)}
- Failure conditions: {json.dumps(scenario.get('failure_conditions', {}), indent=2)}

## Persona
- Name: {persona.get('name', 'User')}
- Patience: {persona.get('traits', {}).get('patience', 5)}/10
- Edge behaviors: {json.dumps(persona.get('edge_behaviors', {}), indent=2)}

## Conversation so far
{conv_text}
{failure_ctx}
## Your task

Evaluate this conversation and respond with ONLY valid JSON (no markdown, no explanation outside JSON):

{{
  "action": "continue" | "restart" | "flag",
  "quality_score": <0-10 float>,
  "reasoning": "<1-2 sentences: why this score>",
  "coaching": "<advice for the simulated user to improve the conversation's test value>",
  "is_false_positive": <true|false>,
  "false_positive_reason": "<explanation if true, empty string if false>",
  "confidence": <0-1 float>
}}

Evaluation criteria:
- **quality_score**: Is the conversation actually TESTING the agent? Is it exercising the scenario's goals? (10=perfect test, 0=completely off-track)
- **action**:
  - "continue" = conversation is productive, keep going
  - "restart" = conversation is off-track, wasting turns, or the persona is not testing the right thing. Score < {self.quality_threshold} should trigger restart.
  - "flag" = found a confirmed real bug in the agent
- **coaching**: What should the simulated user say/do differently to make this a better test?
- **is_false_positive**: If the test engine says FAILED, but the agent actually responded appropriately, mark as true. Be CONSERVATIVE — only mark as false positive if you are very confident (confidence >= 0.8) the agent handled it correctly.
"""

    def _build_final_prompt(
        self,
        conversation: List[Dict[str, str]],
        scenario: Dict[str, Any],
        persona: Dict[str, Any],
        test_success: bool,
        failure_reason: Optional[str],
    ) -> str:
        conv_text = self._format_conversation(conversation)
        result_text = "PASSED" if test_success else f"FAILED (reason: {failure_reason})"

        return f"""You are a Critic Agent performing FINAL evaluation of a completed test conversation.

## Scenario
- Goal: {scenario.get('user_goal', 'unknown')}
- Required tools: {scenario.get('required_tools', [])}
- Success conditions: {json.dumps(scenario.get('success_conditions', {}), indent=2)}

## Test Result: {result_text}

## Full Conversation
{conv_text}

## Your task

The test engine marked this conversation as {result_text}.
Evaluate whether this result is CORRECT or a false positive/negative.

Be CONSERVATIVE with false positive detection — only mark is_false_positive=true
if you are very confident (confidence >= 0.8) the agent genuinely handled the
scenario correctly despite the test engine marking it as failed.

Respond with ONLY valid JSON:

{{
  "action": "continue",
  "quality_score": <0-10 float>,
  "reasoning": "<1-2 sentences: is the test result correct?>",
  "coaching": "<what could the simulated user have done better?>",
  "is_false_positive": <true if test says FAILED but agent was actually fine>,
  "false_positive_reason": "<explanation if true>",
  "confidence": <0-1 float>
}}
"""

    def _format_conversation(self, conversation: List[Dict[str, str]]) -> str:
        lines = []
        for turn in conversation:
            role = turn.get("role", "unknown").upper()
            msg = turn.get("message", "")
            tool_calls = turn.get("tool_calls", [])
            lines.append(f"[{role}]: {msg}")
            if tool_calls:
                for tc in tool_calls:
                    name = tc.get("tool_name", "unknown")
                    result = tc.get("result", {})
                    status = "OK" if isinstance(result, dict) and result.get("status") == "ok" else "ERROR"
                    lines.append(f"  -> Tool: {name} [{status}]")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # LLM call
    # ------------------------------------------------------------------

    async def _call_llm(self, prompt: str) -> CriticVerdict:
        client = self._get_client()

        raw, input_tokens, output_tokens = await self._provider_config.call(
            client, prompt, max_tokens=400, temperature=0.3
        )
        raw = raw.strip()

        # Parse JSON response — robust to markdown fences and trailing text
        import re as _re
        raw = _re.sub(r"^```\w*\n?", "", raw)
        raw = _re.sub(r"\n?```\s*$", "", raw)
        raw = raw.strip()
        data = None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Fallback: extract first JSON object from response
            decoder = json.JSONDecoder()
            for i, ch in enumerate(raw):
                if ch == "{":
                    try:
                        data, _ = decoder.raw_decode(raw, i)
                        break
                    except json.JSONDecodeError:
                        continue
        if data is None:
            logger.warning("Critic returned invalid JSON: %s", raw[:200])
            data = {
                "action": "continue",
                "quality_score": 5.0,
                "reasoning": "Failed to parse critic response",
                "coaching": "",
                "is_false_positive": False,
                "false_positive_reason": "",
                "confidence": 0.3,
            }

        tokens = input_tokens + output_tokens
        cost = self._provider_config.cost_for_tokens(input_tokens, output_tokens)

        return CriticVerdict(
            action=data.get("action", "continue"),
            quality_score=float(data.get("quality_score", 5.0)),
            reasoning=data.get("reasoning", ""),
            coaching=data.get("coaching", ""),
            is_false_positive=bool(data.get("is_false_positive", False)),
            false_positive_reason=data.get("false_positive_reason", ""),
            confidence=float(data.get("confidence", 0.5)),
            tokens_used=tokens,
            cost_usd=cost,
        )


class OfflineCriticAgent(CriticAgent):
    """
    Offline Critic that uses heuristics instead of LLM calls.
    Zero cost, instant, deterministic. Used with --skip-ai.
    """

    async def evaluate(
        self,
        conversation: List[Dict[str, str]],
        scenario: Dict[str, Any],
        persona: Dict[str, Any],
        current_failure_reason: Optional[str] = None,
    ) -> CriticVerdict:
        score, reasoning, coaching = self._heuristic_eval(conversation, scenario)

        # FP detection: require BOTH high score AND high confidence signals
        is_fp = False
        fp_reason = ""
        if current_failure_reason and score >= 8.0:
            # Only flag FP if the failure is specifically about tool coverage
            # (not timeouts, errors, or agent misbehavior)
            benign_failures = ("max turns exceeded", "persona gave up")
            if any(f in current_failure_reason.lower() for f in benign_failures):
                is_fp = True
                fp_reason = (
                    f"Quality score ({score}/10) with benign failure type "
                    f"suggests false positive: {current_failure_reason}"
                )

        action = "continue"
        if score < self.quality_threshold:
            action = "restart"

        verdict = CriticVerdict(
            action=action,
            quality_score=score,
            reasoning=reasoning,
            coaching=coaching,
            is_false_positive=is_fp,
            false_positive_reason=fp_reason,
            confidence=0.6,  # heuristics are less confident than LLM
        )
        self.metrics.record(verdict)
        return verdict

    async def evaluate_final(
        self,
        conversation: List[Dict[str, str]],
        scenario: Dict[str, Any],
        persona: Dict[str, Any],
        test_success: bool,
        failure_reason: Optional[str] = None,
    ) -> CriticVerdict:
        score, reasoning, coaching = self._heuristic_eval(conversation, scenario)

        # Conservative FP: require high score + benign failure pattern
        is_fp = False
        fp_reason = ""
        if not test_success and failure_reason and score >= 8.0:
            benign_failures = ("max turns exceeded", "persona gave up")
            if any(f in failure_reason.lower() for f in benign_failures):
                is_fp = True
                fp_reason = (
                    f"Quality score ({score}/10) with benign failure "
                    f"({failure_reason}) suggests false positive"
                )

        verdict = CriticVerdict(
            action="continue",
            quality_score=score,
            reasoning=reasoning,
            coaching=coaching,
            is_false_positive=is_fp,
            false_positive_reason=fp_reason,
            confidence=0.5,
        )
        self.metrics.record(verdict)
        return verdict

    def _heuristic_eval(
        self,
        conversation: List[Dict[str, str]],
        scenario: Dict[str, Any],
    ) -> tuple[float, str, str]:
        """Return (score, reasoning, coaching) using simple heuristics."""
        score = 5.0
        reasons = []
        coaching_tips = []

        # 1. Conversation length check
        user_turns = [t for t in conversation if t.get("role") == "user"]
        agent_turns = [t for t in conversation if t.get("role") == "agent"]

        if len(user_turns) < 2:
            score -= 1.0
            reasons.append("Too few user turns")
            coaching_tips.append("Engage more with the agent")

        # 2. Tool usage check
        required_tools = set(scenario.get("required_tools", []))
        called_tools = set()
        for t in agent_turns:
            for tc in t.get("tool_calls", []):
                called_tools.add(tc.get("tool_name", ""))

        if required_tools:
            coverage = len(called_tools & required_tools) / len(required_tools)
            score += coverage * 2.0  # up to +2 (reduced from +3 to avoid inflated scores)
            if coverage < 0.5:
                reasons.append(f"Only {coverage:.0%} of required tools called")
                coaching_tips.append("Steer conversation toward using required tools")
        elif called_tools:
            score += 1.0  # some tools called even if none required

        # 3. Goal mention check — use keyword extraction instead of prefix truncation
        goal = scenario.get("user_goal", "").lower()
        if goal:
            goal_words = [w for w in goal.split() if len(w) > 3]  # meaningful words
            user_text = " ".join(t.get("message", "").lower() for t in user_turns)
            matched = sum(1 for w in goal_words if w in user_text)
            if goal_words and matched / len(goal_words) >= 0.3:
                score += 1.0
            else:
                reasons.append("User goal not clearly referenced")
                coaching_tips.append("Reference the goal more explicitly")

        # 4. Repetition penalty
        messages = [t.get("message", "") for t in user_turns]
        if len(messages) >= 3:
            unique_ratio = len(set(messages)) / len(messages)
            if unique_ratio < 0.7:
                score -= 2.0
                reasons.append("Too many repeated messages")
                coaching_tips.append("Vary your messages, don't repeat yourself")

        score = max(0.0, min(10.0, score))
        reasoning = "; ".join(reasons) if reasons else "Conversation is on track"
        coaching = ". ".join(coaching_tips) if coaching_tips else ""

        return score, reasoning, coaching
