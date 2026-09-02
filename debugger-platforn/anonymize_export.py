#!/usr/bin/env python3
"""
Batch-anonymise a production conversation export.

This is step one of the offline research workflow:

    extract conversations  ->  ANONYMISE (this tool)  ->  ground truth /
    seeds / experiments all run on the anonymised corpus only.

Free-text fields pass through the strongest available anonymisation pipeline
(regex PII -> Spanish NER -> brand scrub when the anonymization/ backend is
installed; regex fallback otherwise).  Direct-identifier fields (phone
number, WhatsApp ID, customer name/ID) are dropped outright, and opaque
blobs that can smuggle PII (media URLs, location payloads, free-form
metadata) are removed.  Structural and statistical fields — statuses,
timestamps, intents, confidence scores, tool calls, error codes — are
preserved untouched because the ground-truth scorer depends on them.

Usage:
    python3 anonymize_export.py \
        --input ../docs/tech_repair-conversations-export.json \
        --output ../docs/tech_repair-conversations-anonymized.json
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel

from src.production.anonymize import get_anonymiser

console = Console()

# Conversation-level fields that are direct identifiers: always removed.
_DROP_CONV_FIELDS = (
    "phone_number", "wa_id", "customer_name", "customer_id",
    "escalated_to", "taken_over_by_user_id",
)
# Conversation-level free-text fields: anonymised.
_TEXT_CONV_FIELDS = ("escalation_reason", "conversation_summary")
# Opaque conversation-level blobs that can carry PII: removed.
_BLOB_CONV_FIELDS = ("metadata",)

# Message-level identifier/blob fields: removed.
_DROP_MSG_FIELDS = (
    "wamid", "media_url", "media_storage_path", "location_data",
    "template_parameters", "interactive_payload", "metadata",
)
# Message-level free-text fields: anonymised.
_TEXT_MSG_FIELDS = ("text_body", "media_caption", "media_transcript", "error_message")


@click.command()
@click.option("--input", "input_path", required=True, type=click.Path(exists=True),
              help="Raw conversation export JSON")
@click.option("--output", "output_path", required=True, type=click.Path(),
              help="Anonymised export destination")
@click.option("--limit", default=None, type=int,
              help="Only process the first N conversations (for testing)")
@click.option("--allow-fallback", is_flag=True, default=False,
              help="Permit regex-only redaction when the full NER+brand pipeline "
                   "is unavailable. Unsafe for research output; off by default.")
def main(input_path: str, output_path: str, limit: int | None, allow_fallback: bool):
    """Anonymise every free-text field of a conversation export."""
    anonymise_fn, level = get_anonymiser()
    if level != "full" and not allow_fallback:
        # Fail closed. This script is the project's ethical gate: silently
        # emitting weaker redaction is the one failure mode that must not be
        # possible by accident.
        raise click.ClickException(
            "Full anonymisation pipeline unavailable — refusing to run.\n"
            "Regex-only fallback would leave person names, locations and brand "
            "terms in the output.\n"
            "Fix with:\n"
            "    pip install -r ../anonymization/backend/requirements.txt\n"
            "    python -m spacy download es_core_news_lg\n"
            "Or pass --allow-fallback if you explicitly accept weaker redaction "
            "(never for research output)."
        )
    if level != "full":
        console.print(
            "[yellow]WARNING: full anonymisation pipeline unavailable — "
            "falling back to regex-only redaction (emails/phones/long IDs). "
            "Install anonymization/backend requirements for NER + brand scrub "
            "before using the output for research.[/yellow]"
        )

    # Support-agent conversations repeat templates heavily; caching turns the
    # NER pass from minutes into seconds for the repeated bulk.
    @lru_cache(maxsize=200_000)
    def anonymise(text: str) -> str:
        return anonymise_fn(text)

    console.print(Panel(
        f"[bold]Batch anonymisation[/bold]\npipeline: {level}", style="blue",
    ))

    with open(input_path) as f:
        data = json.load(f)
    conversations = data.get("conversations", [])
    if limit:
        conversations = conversations[:limit]

    n_msgs = 0
    with console.status("[bold green]Anonymising...") as status:
        for i, conv in enumerate(conversations, 1):
            for field_name in _DROP_CONV_FIELDS + _BLOB_CONV_FIELDS:
                conv.pop(field_name, None)
            for field_name in _TEXT_CONV_FIELDS:
                if conv.get(field_name):
                    conv[field_name] = anonymise(conv[field_name])

            for msg in conv.get("messages") or []:
                for field_name in _DROP_MSG_FIELDS:
                    msg.pop(field_name, None)
                for field_name in _TEXT_MSG_FIELDS:
                    if msg.get(field_name):
                        msg[field_name] = anonymise(msg[field_name])
                n_msgs += 1

            if i % 50 == 0:
                status.update(
                    f"[bold green]Anonymising... {i}/{len(conversations)} "
                    f"conversations ({n_msgs} messages)"
                )

    data["conversations"] = conversations
    data["total_conversations"] = len(conversations)
    data["anonymisation"] = {"pipeline": level, "tool": "anonymize_export.py"}

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(data, f, ensure_ascii=False)

    console.print(
        f"[green]Done[/green] — {len(conversations)} conversations, "
        f"{n_msgs} messages anonymised → [cyan]{output_path}[/cyan]"
    )


if __name__ == "__main__":
    main()
