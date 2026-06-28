"""
Agent connectors: abstract interface + concrete implementations.

MockAgentConnector  – deterministic responses for testing the pipeline.
APIAgentConnector   – real HTTP calls to a running agent endpoint.
"""

from __future__ import annotations

import asyncio
import random
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class AgentConnector(ABC):
    """Abstract base for connecting to an agent under test."""

    @abstractmethod
    async def send_message(self, message: str, context: Dict | None = None) -> Dict[str, Any]:
        """Send a user message and return the agent's response.

        Returns:
            {
                "success": bool,
                "response": str,          # agent text reply
                "tool_calls": [...],       # list of tool-call dicts
                "error": str | None
            }
        """

    @abstractmethod
    async def reset(self) -> None:
        """Reset conversation / session state."""


# ──────────────────────────────────────────────────────────────────
# Mock connector (for pipeline testing without a live agent)
# ──────────────────────────────────────────────────────────────────


_MOCK_RESPONSES = [
    "I'd be happy to help you with that. Let me look into it.",
    "Sure, let me check that information for you right away.",
    "I've found the details you're looking for. Here's what I have:",
    "Let me process that request. One moment please.",
    "I understand your concern. Here's what I can do for you.",
    "Great question! Based on our records, here's the information:",
    "I've completed that action for you. Is there anything else?",
    "Thank you for your patience. The request has been processed.",
]

_MOCK_RESPONSES_ES = [
    "Con gusto te ayudo con eso. Déjame revisarlo.",
    "Claro, déjame verificar esa información de inmediato.",
    "Encontré los detalles que buscas. Aquí está lo que tengo:",
    "Déjame procesar esa solicitud. Un momento por favor.",
    "Entiendo tu inquietud. Esto es lo que puedo hacer por ti.",
    "¡Buena pregunta! Según nuestros registros, aquí está la información:",
    "He completado esa acción por ti. ¿Hay algo más en lo que pueda ayudarte?",
    "Gracias por tu paciencia. La solicitud ha sido procesada.",
]

_MOCK_TOOL_NAMES = [
    "executeToolCall",
    "createClientsRoutes",
    "createAppointmentsRoutes",
    "executeEscalateToHuman",
    "createLeadsRoutes",
    "fetchData",
]


class MockAgentConnector(AgentConnector):
    """Simulates an agent with deterministic (random-seeded) responses.

    Configurable behaviours:
    - ``fail_rate``: probability [0..1] that a response fails.
    - ``tool_call_rate``: probability a response includes mock tool calls.
    - ``latency_range``: (min_ms, max_ms) simulated network latency.
    - ``available_tools``: tool names the mock agent can "call".

    When the agent_map contains ``tool_chains``, the mock simulates
    realistic multi-turn tool chains: it calls one tool per turn in
    sequence, and emits a confirmation message when the chain completes.
    """

    def __init__(
        self,
        agent_map: Dict,
        fail_rate: float = 0.05,
        tool_call_rate: float = 0.4,
        latency_range: tuple[int, int] = (50, 300),
        available_tools: List[str] | None = None,
        language: str = "English",
    ):
        self.agent_map = agent_map
        self.fail_rate = fail_rate
        self.tool_call_rate = tool_call_rate
        self.latency_range = latency_range
        self.language = language
        self.session_id: str | None = None
        self.turn_count = 0
        self._responses = _MOCK_RESPONSES_ES if language == "Spanish" else _MOCK_RESPONSES

        self.available_tools = available_tools or [
            t["name"]
            for t in agent_map.get("components", {}).get("tools", [])
        ]
        # Dedupe
        self.available_tools = list(dict.fromkeys(self.available_tools))

        # Tool chain simulation state
        self._tool_chains: List[Dict] = agent_map.get("tool_chains", [])
        self._current_chain: List[str] = []
        self._chain_index: int = 0

        # Configurable confirmation messages (from agent_map or defaults)
        self._confirmation_msgs = agent_map.get("mock_confirmation_messages", {})
        self._confirm_en = self._confirmation_msgs.get(
            "en", "I've completed that for you. Everything has been confirmed and booked."
        )
        self._confirm_es = self._confirmation_msgs.get(
            "es", "He completado eso por ti. Todo ha sido confirmado y reservado."
        )

    async def send_message(self, message: str, context: Dict | None = None) -> Dict[str, Any]:
        # Simulate latency
        latency_ms = random.randint(*self.latency_range)
        await asyncio.sleep(latency_ms / 1000)

        self.turn_count += 1

        # Simulate failure
        if random.random() < self.fail_rate:
            return {
                "success": False,
                "response": "",
                "tool_calls": [],
                "error": "Mock agent error: service unavailable",
            }

        # Pick a response
        response_text = random.choice(self._responses)

        # --- Tool chain simulation ---
        tool_calls: List[Dict] = []

        if self._current_chain and self._chain_index < len(self._current_chain):
            # Continue current chain: call next tool in sequence
            tool_name = self._current_chain[self._chain_index]
            self._chain_index += 1
            tool_calls.append(self._make_tool_call(tool_name, message))

            # If chain is now complete, emit confirmation
            if self._chain_index >= len(self._current_chain):
                response_text = self._confirm_en if self.language != "Spanish" else self._confirm_es
                self._current_chain = []
                self._chain_index = 0

        elif self._tool_chains and self.turn_count == 1:
            # First turn: pick a chain to simulate and call its first tool
            chain = random.choice(self._tool_chains)
            self._current_chain = list(chain.get("sequence", []))
            self._chain_index = 0

            if self._current_chain:
                tool_name = self._current_chain[self._chain_index]
                self._chain_index += 1
                tool_calls.append(self._make_tool_call(tool_name, message))

                if self._chain_index >= len(self._current_chain):
                    response_text = self._confirm_en if self.language != "Spanish" else self._confirm_es
                    self._current_chain = []
                    self._chain_index = 0

        elif random.random() < self.tool_call_rate and self.available_tools:
            # Fallback: random single tool call (original behavior)
            tool_name = random.choice(self.available_tools)
            tool_calls.append(self._make_tool_call(tool_name, message))

        return {
            "success": True,
            "response": response_text,
            "tool_calls": tool_calls,
            "error": None,
        }

    def _make_tool_call(self, tool_name: str, message: str) -> Dict[str, Any]:
        """Build a mock tool call dict with realistic result data."""
        return {
            "tool_name": tool_name,
            "tool_id": str(uuid.uuid4())[:8],
            "arguments": {"query": message[:50]},
            "result": {
                "status": "ok",
                "data": f"mock_result_for_{tool_name}",
                "tool": tool_name,
            },
        }

    async def reset(self) -> None:
        self.session_id = str(uuid.uuid4())
        self.turn_count = 0
        self._current_chain = []
        self._chain_index = 0


# ──────────────────────────────────────────────────────────────────
# API connector (for real agent endpoints)
# ──────────────────────────────────────────────────────────────────


class APIAgentConnector(AgentConnector):
    """Connect to an agent via HTTP API.

    NOTE: ``max_latency_ms`` from success_criteria is a *quality metric*
    (how fast the agent *should* respond), NOT the HTTP timeout.
    The HTTP timeout is set separately (default 120s) to allow LLM-backed
    agents enough time to respond under load.
    """

    def __init__(self, agent_map: Dict):
        self.endpoint: str = agent_map.get("api_endpoint", "")
        self.api_key: str = agent_map.get("api_key", "")
        self.session_id: str | None = None
        # HTTP timeout: generous to handle LLM latency under load
        self.timeout_sec: int = agent_map.get("metadata", {}).get(
            "http_timeout_sec", 120
        )

    async def send_message(self, message: str, context: Dict | None = None) -> Dict[str, Any]:
        import aiohttp

        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "message": message,
            "session_id": self.session_id,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.endpoint}/chat",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.timeout_sec),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return {
                            "success": True,
                            "response": data.get("response", ""),
                            "tool_calls": data.get("tool_calls", []),
                            "error": None,
                        }
                    else:
                        body = await resp.text()
                        return {
                            "success": False,
                            "response": "",
                            "tool_calls": [],
                            "error": f"HTTP {resp.status}: {body[:200]}",
                        }
        except asyncio.TimeoutError:
            return {"success": False, "response": "", "tool_calls": [], "error": "Request timed out"}
        except Exception as e:
            return {"success": False, "response": "", "tool_calls": [], "error": str(e)}

    async def reset(self) -> None:
        self.session_id = str(uuid.uuid4())


# ──────────────────────────────────────────────────────────────────
# Victoria connector (for Victoria agent's debug conversation API)
# ──────────────────────────────────────────────────────────────────


class VictoriaConnector(AgentConnector):
    """Connect to Victoria agent via its authenticated debug conversation API.

    Victoria uses session cookie authentication:
    1. Create debug conversation: POST /conversations/debug
    2. Send messages: POST /conversations/:id/debug-message

    Concurrency architecture:
    - A shared ``_api_semaphore`` limits how many HTTP requests are in-flight
      at once (default 3), regardless of how many test workers exist.
    - Transient failures (timeouts, 5xx) are retried with exponential backoff.
    - This allows 10-20 test workers without overwhelming the API.

    Requires a session cookie from Pulpoo authentication.
    """

    # Class-level semaphore shared across all per-conversation instances
    _api_semaphore: Optional[asyncio.Semaphore] = None
    _max_concurrent: int = 3

    @classmethod
    def configure_concurrency(cls, max_concurrent: int) -> None:
        """Set the max concurrent API calls (call before tests start)."""
        cls._max_concurrent = max_concurrent
        cls._api_semaphore = None  # will be lazily created

    @classmethod
    def _get_semaphore(cls) -> asyncio.Semaphore:
        if cls._api_semaphore is None:
            cls._api_semaphore = asyncio.Semaphore(cls._max_concurrent)
        return cls._api_semaphore

    def __init__(self, agent_map: Dict):
        import os

        # Extract endpoint from environment variable (preferred), then agent_map
        base_endpoint = (
            os.getenv("VICTORIA_API_ENDPOINT") or
            agent_map.get("api_endpoint") or
            agent_map.get("metadata", {}).get("api_endpoint", "")
        )

        if not base_endpoint:
            # Try to construct from app_id or use default
            app_id = agent_map.get("metadata", {}).get("app_id", "victoria-tlahuac")
            base_endpoint = f"http://localhost:3200/api/{app_id}"

        self.base_endpoint = base_endpoint.rstrip("/")
        self.api_key: str = agent_map.get("api_key", "")

        # Get session cookie from environment variable (preferred) or agent_map
        self.session_cookie: str = (
            os.getenv("VICTORIA_SESSION_COOKIE") or
            agent_map.get("session_cookie") or
            agent_map.get("metadata", {}).get("session_cookie", "")
        )

        if not self.session_cookie:
            raise ValueError(
                "VictoriaConnector requires 'VICTORIA_SESSION_COOKIE' environment variable or "
                "'session_cookie' in agent_map. "
                "Get it from your browser DevTools > Application > Cookies after logging into Victoria."
            )

        self.conversation_id: str | None = None
        # HTTP timeout: generous to handle LLM latency under load.
        # max_latency_ms in success_criteria is a quality metric, not a timeout.
        self.timeout_sec: int = agent_map.get("metadata", {}).get(
            "http_timeout_sec", 120
        )

        # Retry config
        self._max_retries: int = agent_map.get("metadata", {}).get("max_retries", 2)
        self._backoff_base: float = agent_map.get("metadata", {}).get("backoff_base", 3.0)

        # Concurrency from agent_map (overrides class default on first connector)
        max_conc = agent_map.get("metadata", {}).get("max_concurrent_requests", 0)
        if max_conc > 0:
            VictoriaConnector.configure_concurrency(max_conc)

    async def _request_with_retry(self, coro_factory, retryable_check=None):
        """Execute an async request with semaphore gating and retry.

        ``coro_factory`` is a callable that returns a new coroutine each call.
        ``retryable_check`` is an optional callable(result) -> bool for
        application-level retries (e.g. timeout error in result dict).
        """
        sem = self._get_semaphore()
        last_result = None

        for attempt in range(1 + self._max_retries):
            async with sem:
                last_result = await coro_factory()

            # Check if we should retry
            should_retry = False
            if retryable_check and retryable_check(last_result):
                should_retry = True

            if not should_retry or attempt >= self._max_retries:
                return last_result

            # Exponential backoff with jitter
            delay = self._backoff_base * (2 ** attempt) + random.uniform(0, 1)
            await asyncio.sleep(delay)

        return last_result

    async def reset(self) -> None:
        """Create a new debug conversation."""
        import aiohttp

        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "Cookie": f"session={self.session_cookie}",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        # Create debug conversation
        payload = {
            "clientPhone": f"DEBUG-{uuid.uuid4()}",
            "clientName": "Test User",
        }

        async def _do_reset():
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{self.base_endpoint}/conversations/debug",
                        json=payload,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=self.timeout_sec),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            self.conversation_id = data.get("conversationId") or data.get("conversation", {}).get("id")
                            if not self.conversation_id:
                                raise ValueError("Failed to get conversation ID from Victoria API")
                            return {"ok": True}
                        elif resp.status == 401:
                            raise Exception(
                                "Authentication failed. Session cookie may be invalid or expired. "
                                "Please get a fresh session cookie from your browser."
                            )
                        else:
                            body = await resp.text()
                            raise Exception(f"Failed to create debug conversation: HTTP {resp.status}: {body[:200]}")
            except Exception as e:
                raise Exception(f"Victoria connector reset failed: {e}")

        sem = self._get_semaphore()
        async with sem:
            await _do_reset()

    async def send_message(self, message: str, context: Dict | None = None) -> Dict[str, Any]:
        """Send message to Victoria debug conversation with concurrency gating and retry."""
        import aiohttp

        if not self.conversation_id:
            await self.reset()

        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "Cookie": f"session={self.session_cookie}",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {"message": message}

        async def _do_send() -> Dict[str, Any]:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{self.base_endpoint}/conversations/{self.conversation_id}/debug-message",
                        json=payload,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=self.timeout_sec),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()

                            # Extract response text
                            response_text = data.get("response", "") or data.get("aiResponse", "")

                            # Extract tool calls from actions
                            tool_calls = []
                            actions = data.get("actions", [])
                            for action in actions:
                                if isinstance(action, dict):
                                    action_type = action.get("actionType", "")
                                    action_data = action.get("actionData", {})
                                    if action_type and action_type != "ai_process_message":
                                        tool_calls.append({
                                            "tool_name": action_type,
                                            "tool_id": str(action.get("id", uuid.uuid4())),
                                            "arguments": action_data,
                                            "result": action.get("result"),
                                        })

                            return {
                                "success": True,
                                "response": response_text,
                                "tool_calls": tool_calls,
                                "error": None,
                            }
                        elif resp.status == 401:
                            return {
                                "success": False,
                                "response": "",
                                "tool_calls": [],
                                "error": "Authentication failed. Session cookie may be invalid or expired.",
                            }
                        elif resp.status >= 500:
                            body = await resp.text()
                            return {
                                "success": False,
                                "response": "",
                                "tool_calls": [],
                                "error": f"HTTP {resp.status}: {body[:200]}",
                                "_retryable": True,
                            }
                        else:
                            body = await resp.text()
                            return {
                                "success": False,
                                "response": "",
                                "tool_calls": [],
                                "error": f"HTTP {resp.status}: {body[:200]}",
                            }
            except asyncio.TimeoutError:
                return {"success": False, "response": "", "tool_calls": [], "error": "Request timed out", "_retryable": True}
            except Exception as e:
                return {"success": False, "response": "", "tool_calls": [], "error": str(e)}

        def _is_retryable(result: Dict) -> bool:
            return bool(result.get("_retryable"))

        result = await self._request_with_retry(_do_send, retryable_check=_is_retryable)
        result.pop("_retryable", None)
        return result
