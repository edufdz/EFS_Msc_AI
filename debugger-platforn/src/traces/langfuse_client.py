"""
Langfuse trace ingestion client.

Fetches observability traces from a Langfuse instance via its Python SDK.
Credentials are read from environment variables:
  LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST

If the ``langfuse`` package is not installed or credentials are missing,
all methods return empty results — the feature degrades gracefully.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class LangfuseTraceIngester:
    """Thin wrapper around the Langfuse Python SDK for read-only trace ingestion."""

    def __init__(
        self,
        public_key: str | None = None,
        secret_key: str | None = None,
        host: str | None = None,
    ):
        self.public_key = public_key or os.environ.get("LANGFUSE_PUBLIC_KEY", "")
        self.secret_key = secret_key or os.environ.get("LANGFUSE_SECRET_KEY", "")
        self.host = host or os.environ.get("LANGFUSE_HOST") or os.environ.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
        self._client = None

        if self.public_key and self.secret_key:
            try:
                from langfuse import Langfuse  # type: ignore[import-untyped]

                self._client = Langfuse(
                    public_key=self.public_key,
                    secret_key=self.secret_key,
                    host=self.host,
                )
                logger.info("Langfuse client initialised (host=%s)", self.host)
            except ImportError:
                logger.warning("langfuse package not installed — trace ingestion disabled")
            except Exception as exc:
                logger.warning("Langfuse client init failed: %s", exc)
        else:
            logger.info("Langfuse credentials not set — trace ingestion disabled")

    @property
    def available(self) -> bool:
        return self._client is not None

    def fetch_traces(
        self,
        limit: int = 500,
        since: datetime | None = None,
    ) -> list[dict]:
        """Fetch recent traces from Langfuse.

        Returns a list of raw trace dicts.  Returns ``[]`` if the client
        is unavailable.
        """
        if not self._client:
            return []

        try:
            # Langfuse API caps at 100 per page — paginate
            page_size = min(limit, 100)
            raw: list[dict] = []
            page = 1

            while len(raw) < limit:
                kwargs: dict = {"limit": page_size, "page": page}
                if since:
                    kwargs["from_timestamp"] = since

                response = self._client.api.trace.list(**kwargs)

                traces_data = getattr(response, "data", response) or []
                if not isinstance(traces_data, list):
                    traces_data = list(traces_data) if hasattr(traces_data, "__iter__") else []

                if not traces_data:
                    break  # No more pages

                for t in traces_data:
                    raw.append({
                        "id": getattr(t, "id", None) or (t.get("id") if isinstance(t, dict) else None),
                        "name": getattr(t, "name", None),
                        "timestamp": str(getattr(t, "timestamp", "")),
                        "metadata": getattr(t, "metadata", {}),
                        "input": getattr(t, "input", None),
                        "output": getattr(t, "output", None),
                        "status": getattr(t, "status", None),
                        "tags": getattr(t, "tags", []),
                    })

                if len(traces_data) < page_size:
                    break  # Last page
                page += 1

            raw = raw[:limit]
            logger.info("Fetched %d traces from Langfuse", len(raw))
            return raw
        except Exception as exc:
            logger.warning("Failed to fetch traces: %s", exc)
            return []

    def fetch_trace_detail(self, trace_id: str) -> dict:
        """Fetch a single trace with all observations (spans / generations)."""
        if not self._client:
            return {}

        try:
            # Langfuse SDK v4: use client.api.trace.get() and client.api.observations.get_many()
            trace = self._client.api.trace.get(trace_id)
            obs_response = self._client.api.observations.get_many(trace_id=trace_id)

            obs_data = getattr(obs_response, "data", obs_response) or []
            if not isinstance(obs_data, list):
                obs_data = list(obs_data) if hasattr(obs_data, "__iter__") else []

            obs_list = []
            for o in obs_data:
                obs_list.append({
                    "id": getattr(o, "id", None),
                    "type": getattr(o, "type", "span"),
                    "name": getattr(o, "name", None),
                    "start_time": str(getattr(o, "start_time", "")),
                    "end_time": str(getattr(o, "end_time", "")),
                    "input": getattr(o, "input", None),
                    "output": getattr(o, "output", None),
                    "metadata": getattr(o, "metadata", {}),
                    "status_message": getattr(o, "status_message", None),
                    "level": getattr(o, "level", None),
                })

            trace_id_val = getattr(trace, "id", None) or (trace.get("id") if isinstance(trace, dict) else trace_id)
            return {
                "trace": {
                    "id": trace_id_val,
                    "name": getattr(trace, "name", None),
                    "input": getattr(trace, "input", None),
                    "output": getattr(trace, "output", None),
                    "status": getattr(trace, "status", None),
                },
                "observations": obs_list,
            }
        except Exception as exc:
            logger.warning("Failed to fetch trace detail %s: %s", trace_id, exc)
            return {}
