"""
Retry decorator for Anthropic API calls with exponential backoff.

Handles rate-limit (429), overloaded (529), and connection errors
without adding any external dependencies beyond the stdlib.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from functools import wraps
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable)


@dataclass
class RetryConfig:
    """Configuration for API retry behaviour."""

    max_retries: int = 3
    backoff_base: float = 2.0
    backoff_max: float = 60.0


_DEFAULT_CONFIG = RetryConfig()


def retry_anthropic(config: RetryConfig | None = None):
    """Decorator that retries a function on transient Anthropic errors.

    Retryable errors (lazy-imported so the decorator works even when
    ``anthropic`` is not installed):
      - ``RateLimitError``   (HTTP 429)
      - ``APIStatusError`` with status 529 (overloaded)
      - ``APIConnectionError``

    All other exceptions are re-raised immediately.
    """
    cfg = config or _DEFAULT_CONFIG

    def decorator(fn: F) -> F:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            import anthropic

            retryable = (
                anthropic.RateLimitError,
                anthropic.APIConnectionError,
            )

            last_exc: Exception | None = None
            for attempt in range(cfg.max_retries + 1):
                try:
                    return fn(*args, **kwargs)
                except retryable as exc:
                    last_exc = exc
                except anthropic.APIStatusError as exc:
                    if exc.status_code == 529:
                        last_exc = exc
                    else:
                        raise
                else:
                    break  # pragma: no cover – unreachable after return

                if attempt < cfg.max_retries:
                    delay = min(
                        cfg.backoff_base * (2 ** attempt) + random.random(),
                        cfg.backoff_max,
                    )
                    logger.warning(
                        "Anthropic API error (attempt %d/%d), retrying in %.1fs: %s",
                        attempt + 1,
                        cfg.max_retries,
                        delay,
                        last_exc,
                    )
                    time.sleep(delay)

            # All retries exhausted — raise the last error
            raise last_exc  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator
