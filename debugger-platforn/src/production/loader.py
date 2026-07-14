"""
Loader for the production WhatsApp conversation export.

Export schema (docs/tech_repair-conversations-export.json):

    {
      "exported_at": str,
      "total_conversations": int,
      "total_messages": int,
      "conversations": [
        {
          "id": str, "status": "active|closed|expired|escalated",
          "escalated_at": str|null, "escalation_reason": str|null,
          "is_human_handling": bool, "taken_over_at": str|null,
          "message_count": int, "created_at": str, ...,
          "messages": [
            {"source": "customer|ai_agent|human_agent|system",
             "text_body": str|null, "ai_intent_detected": str|null,
             "ai_confidence_score": float|null, "ai_tool_calls": list|null,
             "status": str|null, "error_code": str|null,
             "created_at": str, ...}
          ]
        }, ...
      ]
    }

Conversations are kept as plain dicts (the export is the source of truth);
this module only validates shape, orders messages chronologically, and
normalises the handful of fields the scorer depends on.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def load_export(path: str | Path) -> List[Dict[str, Any]]:
    """Load the conversation export and return normalised conversation dicts.

    Normalisations applied in place:
      - ``messages`` sorted by ``created_at``
      - ``_created_dt`` / ``_escalated_dt`` parsed datetime fields added
      - missing ``messages`` defaults to []
    """
    with open(path) as f:
        data = json.load(f)

    conversations = data.get("conversations")
    if conversations is None:
        # Also accept a bare list of conversations
        if isinstance(data, list):
            conversations = data
        else:
            raise ValueError(
                f"{path}: expected an export with a 'conversations' key "
                f"(found keys: {sorted(data.keys())[:10]})"
            )

    for conv in conversations:
        messages = conv.get("messages") or []
        messages.sort(key=lambda m: m.get("created_at") or "")
        conv["messages"] = messages
        conv["_created_dt"] = _parse_ts(conv.get("created_at"))
        conv["_escalated_dt"] = _parse_ts(conv.get("escalated_at"))

    return conversations
