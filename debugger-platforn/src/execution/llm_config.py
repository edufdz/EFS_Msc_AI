"""
LLM provider configuration — supports Anthropic and any OpenAI-compatible provider.

Supported providers (presets):
  anthropic  — Claude models via Anthropic SDK (default)
  ollama     — Local models via Ollama (http://localhost:11434)
  groq       — llama-3.1-8b-instant, mixtral, etc. (free tier, very fast)
  together   — Meta Llama, Mistral, etc.
  fireworks  — Llama, Mixtral, etc.
  openai     — GPT-4o-mini, etc.
  custom     — any OpenAI-compatible endpoint (set base_url + model manually)

Usage
-----
# Anthropic (default — no config needed)
config = LLMProviderConfig()

# Groq with default model (reads GROQ_API_KEY from env)
config = LLMProviderConfig(provider="groq")

# Together AI with explicit model
config = LLMProviderConfig(provider="together", model="mistralai/Mistral-7B-Instruct-v0.3")

# Fully custom endpoint
config = LLMProviderConfig(
    provider="custom",
    model="my-model",
    base_url="http://localhost:1234/v1",
    api_key="sk-...",
)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Known provider presets:
#   base_url        — API endpoint (None = SDK default)
#   default_model   — cheapest/fastest model for the provider
#   key_env         — environment variable name for the API key
#   input_cost_per_m  — USD per 1 million input tokens
#   output_cost_per_m — USD per 1 million output tokens
# Costs are approximate list prices (2025). Set to 0 if unknown.
_PROVIDER_PRESETS: dict[str, dict] = {
    "anthropic": {
        "base_url": None,
        "default_model": "claude-haiku-4-5",
        "key_env": "ANTHROPIC_API_KEY",
        "input_cost_per_m": 1.00,   # Haiku 4.5
        "output_cost_per_m": 5.00,
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "default_model": "mistral",
        "key_env": None,            # Ollama needs no API key
        "input_cost_per_m": 0.0,    # local — free
        "output_cost_per_m": 0.0,
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.1-8b-instant",
        "key_env": "GROQ_API_KEY",
        "input_cost_per_m": 0.05,   # llama-3.1-8b-instant on Groq
        "output_cost_per_m": 0.08,
    },
    "together": {
        "base_url": "https://api.together.xyz/v1",
        "default_model": "meta-llama/Llama-3.1-8B-Instruct-Turbo",
        "key_env": "TOGETHER_API_KEY",
        "input_cost_per_m": 0.18,   # Llama-3.1-8B on Together
        "output_cost_per_m": 0.18,
    },
    "fireworks": {
        "base_url": "https://api.fireworks.ai/inference/v1",
        "default_model": "accounts/fireworks/models/llama-v3p1-8b-instruct",
        "key_env": "FIREWORKS_API_KEY",
        "input_cost_per_m": 0.20,   # Llama-3.1-8B on Fireworks
        "output_cost_per_m": 0.20,
    },
    "openai": {
        "base_url": None,
        "default_model": "gpt-4o-mini",
        "key_env": "OPENAI_API_KEY",
        "input_cost_per_m": 0.15,   # gpt-4o-mini
        "output_cost_per_m": 0.60,
    },
    "custom": {
        "base_url": None,   # must be provided via base_url param
        "default_model": "",
        "key_env": "CUSTOM_LLM_API_KEY",
        "input_cost_per_m": 0.0,    # unknown — user must track externally
        "output_cost_per_m": 0.0,
    },
}

# Providers that use the Anthropic SDK. All others use the OpenAI-compatible SDK.
_ANTHROPIC_PROVIDERS = {"anthropic"}


@dataclass
class LLMProviderConfig:
    """
    Configuration for one LLM endpoint (persona generator or critic agent).

    Parameters
    ----------
    provider : str
        Provider name. One of: anthropic, groq, together, fireworks, openai, custom.
    model : str | None
        Model name. None → use the provider's default cheap model.
    api_key : str | None
        API key. None → read from the provider's standard env var.
    base_url : str | None
        Base URL override. Required for provider="custom".
    """

    provider: str = "anthropic"
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None

    # ------------------------------------------------------------------ #
    # Resolved properties                                                  #
    # ------------------------------------------------------------------ #

    @property
    def resolved_model(self) -> str:
        if self.model:
            return self.model
        preset = _PROVIDER_PRESETS.get(self.provider)
        default = preset["default_model"] if preset else ""
        if not default:
            raise ValueError(
                f"provider='{self.provider}' requires an explicit model= argument. "
                "No default model is defined for this provider."
            )
        return default

    @property
    def resolved_base_url(self) -> Optional[str]:
        if self.base_url:
            return self.base_url
        preset = _PROVIDER_PRESETS.get(self.provider)
        return preset.get("base_url") if preset else None

    @property
    def resolved_api_key(self) -> Optional[str]:
        if self.api_key:
            return self.api_key
        preset = _PROVIDER_PRESETS.get(self.provider)
        if preset and preset.get("key_env"):
            return os.getenv(preset["key_env"])
        return None

    @property
    def is_anthropic(self) -> bool:
        return self.provider in _ANTHROPIC_PROVIDERS

    @property
    def needs_api_key(self) -> bool:
        """Whether this provider requires an API key (False for ollama/local)."""
        preset = _PROVIDER_PRESETS.get(self.provider, {})
        return preset.get("key_env") is not None

    # ------------------------------------------------------------------ #
    # Client factory                                                       #
    # ------------------------------------------------------------------ #

    def create_sync_client(self):
        """Instantiate and return the appropriate synchronous LLM client."""
        if self.is_anthropic:
            from anthropic import Anthropic

            kwargs: dict = {}
            key = self.resolved_api_key
            if key:
                kwargs["api_key"] = key
            return Anthropic(**kwargs)
        else:
            from openai import OpenAI

            if self.provider == "custom" and not self.resolved_base_url:
                raise ValueError(
                    "provider='custom' requires an explicit base_url= argument."
                )

            kwargs: dict = {}
            url = self.resolved_base_url
            if url:
                kwargs["base_url"] = url
            key = self.resolved_api_key
            if not key:
                if not self.needs_api_key:
                    # Ollama and local servers don't need a real key,
                    # but the OpenAI SDK requires a non-empty string.
                    key = "no-key-needed"
                else:
                    preset = _PROVIDER_PRESETS.get(self.provider, {})
                    logger.warning(
                        "No API key found for provider '%s' (expected env var: %s). "
                        "Calls will likely fail with an authentication error.",
                        self.provider,
                        preset.get("key_env", "unknown"),
                    )
            kwargs["api_key"] = key
            return OpenAI(**kwargs)

    def create_async_client(self):
        """Instantiate and return the appropriate async LLM client (lazy)."""
        if self.is_anthropic:
            from anthropic import AsyncAnthropic

            kwargs: dict = {}
            key = self.resolved_api_key
            if key:
                kwargs["api_key"] = key
            return AsyncAnthropic(**kwargs)
        else:
            from openai import AsyncOpenAI

            # Custom provider must supply a base_url — without it, the OpenAI
            # client would silently route requests to api.openai.com.
            if self.provider == "custom" and not self.resolved_base_url:
                raise ValueError(
                    "provider='custom' requires an explicit base_url= argument."
                )

            kwargs = {}
            url = self.resolved_base_url
            if url:
                kwargs["base_url"] = url
            key = self.resolved_api_key
            if not key:
                if not self.needs_api_key:
                    # Ollama and local servers don't need a real key,
                    # but the OpenAI SDK requires a non-empty string.
                    key = "no-key-needed"
                else:
                    preset = _PROVIDER_PRESETS.get(self.provider, {})
                    logger.warning(
                        "No API key found for provider '%s' (expected env var: %s). "
                        "Calls will likely fail with an authentication error.",
                        self.provider,
                        preset.get("key_env", "unknown"),
                    )
            kwargs["api_key"] = key
            return AsyncOpenAI(**kwargs)

    # ------------------------------------------------------------------ #
    # Unified call                                                         #
    # ------------------------------------------------------------------ #

    async def call(
        self,
        client,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> tuple[str, int, int]:
        """
        Call the LLM and return ``(text, input_tokens, output_tokens)``.

        Handles both Anthropic SDK and OpenAI-compatible SDK response shapes.
        """
        if self.is_anthropic:
            response = await client.messages.create(
                model=self.resolved_model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            return (
                response.content[0].text,
                response.usage.input_tokens,
                response.usage.output_tokens,
            )
        else:
            response = await client.chat.completions.create(
                model=self.resolved_model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            return (
                response.choices[0].message.content or "",
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
            )

    def call_sync(
        self,
        client,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> tuple[str, int, int]:
        """
        Synchronous variant of ``call()``.
        Returns ``(text, input_tokens, output_tokens)``.
        """
        if self.is_anthropic:
            response = client.messages.create(
                model=self.resolved_model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            return (
                response.content[0].text,
                response.usage.input_tokens,
                response.usage.output_tokens,
            )
        else:
            response = client.chat.completions.create(
                model=self.resolved_model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            usage = response.usage
            return (
                response.choices[0].message.content or "",
                usage.prompt_tokens if usage else 0,
                usage.completion_tokens if usage else 0,
            )

    # ------------------------------------------------------------------ #
    # Cost estimation                                                      #
    # ------------------------------------------------------------------ #

    def cost_for_tokens(self, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost in USD for the given token counts using provider pricing."""
        preset = _PROVIDER_PRESETS.get(self.provider, {})
        input_cost_per_m = preset.get("input_cost_per_m", 0.0)
        output_cost_per_m = preset.get("output_cost_per_m", 0.0)
        return (
            (input_tokens / 1_000_000) * input_cost_per_m
            + (output_tokens / 1_000_000) * output_cost_per_m
        )

    # ------------------------------------------------------------------ #
    # Display                                                              #
    # ------------------------------------------------------------------ #

    def display_name(self) -> str:
        """Human-readable label for CLI/dashboard display."""
        return f"{self.provider}/{self.resolved_model}"
