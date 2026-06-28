"""
GANConversationSimulator — GAN-style adversarial testing architecture.

Thin wrapper around ConversationSimulator that adds a Critic agent via
the ``on_agent_turn`` callback hook.  All conversation features (chaos
injection, mood drift, edge behaviours, terminal outcomes, tool chains,
conversation logging) are inherited from the base simulator.

Architecture (inspired by GANs):

    Generator (G)              Discriminator (D)
    ┌──────────────┐          ┌──────────────────┐
    │ Conversation │          │ Critic Agent     │
    │ Simulator    │──conv──▶│                  │
    │ (Haiku)      │◀─coach──│ (Haiku)          │
    └──────┬───────┘          └──────────────────┘
           │
           ▼
    ┌──────────────┐
    │ Agent Under  │
    │ Test         │
    └──────────────┘

Both G and D use cheap models (Haiku) — they correct each other,
so neither needs to be individually brilliant. This keeps costs low
while maintaining test quality through adversarial self-correction.

Cost note: In --gan mode, each test makes ~2x the LLM calls (Generator +
Critic). With max_restarts=2, worst case is ~6x for a single test.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from .agent_connector import AgentConnector
from .conversation_simulator import ConversationSimulator
from .critic_agent import CriticAgent, CriticVerdict, OfflineCriticAgent
from .llm_config import LLMProviderConfig
from .models import ConversationTurn

logger = logging.getLogger(__name__)


class GANConversationSimulator:
    """
    GAN-style conversation simulator with mid-conversation Critic checks.

    Composes with :class:`ConversationSimulator` via the ``on_agent_turn``
    callback — no monkey-patching, no loop reimplementation.  The Critic
    evaluates every N agent turns and can request restarts or coach the
    Generator.

    All conversation features (chaos injection, mood drift, edge behaviours,
    terminal outcomes, tool chains, conversation logging, tool_called events,
    AI-powered first messages) are inherited from ConversationSimulator.

    Parameters
    ----------
    test_case : dict
        Standard test case from the test suite.
    agent_connector : AgentConnector
        Connection to the agent under test.
    event_queue : asyncio.Queue
        Event queue for the live monitor.
    use_ai : bool
        If True, use LLM-based Critic+Generator. If False, offline heuristics.
    evaluate_every : int
        Critic evaluates every N agent turns.
    max_restarts : int
        Maximum conversation restarts before giving up.
    quality_threshold : float
        Minimum quality score to continue (0-10).
    language : str
        Language for persona messages.
    conversation_log_file : str | None
        Path to conversation log file.
    """

    def __init__(
        self,
        test_case: Dict[str, Any],
        agent_connector: AgentConnector,
        event_queue: asyncio.Queue,
        use_ai: bool = True,
        evaluate_every: int = 2,
        max_restarts: int = 2,
        quality_threshold: float = 3.0,
        language: str = "English",
        conversation_log_file: str | None = None,
        persona_config: Optional[LLMProviderConfig] = None,
        critic_config: Optional[LLMProviderConfig] = None,
    ):
        self.test_case = test_case
        self.agent_connector = agent_connector
        self.event_queue = event_queue
        self.use_ai = use_ai
        self.max_restarts = max_restarts
        self.quality_threshold = quality_threshold
        self.language = language
        self.conversation_log_file = conversation_log_file
        self.persona_config = persona_config or LLMProviderConfig()

        self.scenario: Dict = test_case["scenario"]
        self.persona: Dict = test_case["persona"]

        # Initialize the Critic
        if use_ai:
            self.critic = CriticAgent(
                evaluate_every=evaluate_every,
                max_restarts=max_restarts,
                quality_threshold=quality_threshold,
                provider_config=critic_config or LLMProviderConfig(),
            )
        else:
            # Note: OfflineCriticAgent returns confidence 0.5–0.6, which is
            # below the 0.8 gate for false-positive detection. This means
            # FP detection is effectively disabled in offline mode — by design,
            # since offline heuristics are less reliable.
            self.critic = OfflineCriticAgent(
                evaluate_every=evaluate_every,
                max_restarts=max_restarts,
                quality_threshold=quality_threshold,
            )

        # State
        self.restart_count = 0
        self._coaching: str = ""
        self.test_id = test_case.get("test_id", "unknown")

        # Non-blocking mid-conversation Critic: fire evaluation as background task,
        # collect the result on the NEXT callback. This lets persona message
        # generation run in parallel with the Critic LLM call (~1.5s saved/eval).
        self._pending_critic_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def run(self) -> Dict[str, Any]:
        """
        Execute the GAN conversation loop with mid-conversation Critic checks.

        Returns the same dict shape as ConversationSimulator.run() but enriched
        with Critic metadata.
        """
        best_result: Optional[Dict[str, Any]] = None
        best_quality: float = -1.0
        last_result: Optional[Dict[str, Any]] = None

        while self.restart_count <= self.max_restarts:
            # Cancel any stale Critic task from a previous restart attempt.
            if self._pending_critic_task is not None:
                self._pending_critic_task.cancel()
                self._pending_critic_task = None

            # Create a fresh ConversationSimulator with Critic callback.
            # This inherits ALL features: chaos, mood, edge behaviours,
            # terminal outcomes, tool chains, conversation logging, etc.
            simulator = ConversationSimulator(
                test_case=self.test_case,
                agent_connector=self.agent_connector,
                event_queue=self.event_queue,
                use_ai_personas=self.use_ai,
                language=self.language,
                conversation_log_file=self.conversation_log_file,
                on_agent_turn=self._critic_callback,
                initial_coaching=self._coaching,
                persona_config=self.persona_config,
            )

            result = await simulator.run()
            last_result = result

            # Final Critic evaluation
            conv_for_critic = self._turns_to_critic_format(result["turns"])

            final_verdict = await self.critic.evaluate_final(
                conversation=conv_for_critic,
                scenario=self.scenario,
                persona=self.persona,
                test_success=result["success"],
                failure_reason=result.get("failure_reason"),
            )

            await self.event_queue.put({
                "type": "critic_evaluation",
                "test_id": self.test_id,
                "action": final_verdict.action,
                "quality_score": final_verdict.quality_score,
                "is_false_positive": final_verdict.is_false_positive,
                "reasoning": final_verdict.reasoning,
            })

            # Track best attempt
            if final_verdict.quality_score > best_quality:
                best_quality = final_verdict.quality_score
                best_result = result

            # Handle false positive detection
            if (
                final_verdict.is_false_positive
                and final_verdict.confidence >= 0.8
                and not result["success"]
            ):
                logger.info(
                    "Critic detected false positive for test %s: %s",
                    self.test_id,
                    final_verdict.false_positive_reason,
                )
                result["critic_false_positive"] = True
                result["critic_false_positive_reason"] = final_verdict.false_positive_reason
                best_result = result
                break

            # If quality is acceptable, stop
            if final_verdict.quality_score >= self.quality_threshold:
                break

            # Request restart with coaching
            self.restart_count += 1
            if self.restart_count > self.max_restarts:
                break  # exit immediately instead of waiting for while-condition

            self._coaching = final_verdict.coaching
            logger.info(
                "Critic requests restart (%d/%d) for test %s: %s",
                self.restart_count, self.max_restarts,
                self.test_id, final_verdict.reasoning,
            )

            await self.event_queue.put({
                "type": "critic_restart",
                "test_id": self.test_id,
                "restart_number": self.restart_count,
                "coaching": final_verdict.coaching,
            })

        # Use best result (guaranteed non-None since loop runs at least once)
        result = best_result if best_result is not None else last_result

        # Enrich result with Critic metadata
        result["critic_metrics"] = asdict(self.critic.metrics)
        result["critic_restarts"] = self.restart_count
        result["critic_final_quality"] = best_quality

        # Aggregate costs: Generator metrics come from ConversationSimulator
        # (which tracks llm_calls, tokens_used, cost_usd for its AI persona
        # calls). We add the Critic's metrics on top.
        result["cost_usd"] = result.get("cost_usd", 0.0) + self.critic.metrics.total_cost_usd
        result["tokens_used"] = result.get("tokens_used", 0) + self.critic.metrics.total_tokens
        result["llm_calls"] = result.get("llm_calls", 0) + self.critic.metrics.total_evaluations

        return result

    # ------------------------------------------------------------------
    # Critic callback (injected into ConversationSimulator)
    # ------------------------------------------------------------------

    async def _critic_callback(
        self,
        turns: List[ConversationTurn],
        agent_turn_count: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Called by ConversationSimulator after each agent turn.

        Non-blocking design: the Critic LLM call from the PREVIOUS evaluation
        is awaited here (it has had N turns to complete, so the await is nearly
        instant), and a NEW evaluation is fired as a background task so it runs
        in parallel with the Generator producing the next persona message.

        Returns None to continue, or a signal dict to restart/coach.
        """
        prev_coaching = ""

        # --- Collect result from the previous background evaluation ---
        if self._pending_critic_task is not None:
            try:
                verdict: CriticVerdict = await self._pending_critic_task
            except asyncio.CancelledError:
                # Task was cancelled at restart — safe to ignore.
                self._pending_critic_task = None
                return None
            except Exception as e:
                logger.warning(
                    "Pending Critic task raised an unexpected error: %s — skipping", e
                )
                self._pending_critic_task = None
                return None
            self._pending_critic_task = None

            await self.event_queue.put({
                "type": "critic_mid_eval",
                "test_id": self.test_id,
                "turn": len(turns),
                "quality_score": verdict.quality_score,
                "action": verdict.action,
                "coaching": verdict.coaching,
            })

            if verdict.action == "restart":
                return {
                    "action": "restart",
                    "reason": f"Critic requested restart: {verdict.reasoning}",
                }
            prev_coaching = verdict.coaching

        # --- Fire new evaluation in background (don't await) ---
        if self.critic.should_evaluate(agent_turn_count):
            conv_so_far = self._turns_to_critic_format(turns)
            self._pending_critic_task = asyncio.create_task(
                self.critic.evaluate(
                    conversation=conv_so_far,
                    scenario=self.scenario,
                    persona=self.persona,
                )
            )

        if prev_coaching:
            return {"action": "continue", "coaching": prev_coaching}
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _turns_to_critic_format(turns: List[ConversationTurn]) -> List[Dict[str, str]]:
        """Convert ConversationTurn list to Critic-friendly format."""
        return [
            {
                "role": t.role,
                "message": t.message,
                "tool_calls": t.tool_calls,
            }
            for t in turns
        ]
