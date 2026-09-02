"""
Persona context: prompt user for optional context (inline text or file path),
analyze it once so personas can use it appropriately in any conversation.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any


def analyze_persona_context(
    raw_context: str,
    user_goal: str | None = None,
) -> dict[str, Any] | None:
    """
    Analyze the context once with an LLM so personas understand what's in it
    and how to use it in conversation. Works for any domain (vehicles, orders,
    accounts, etc.). Returns None if no API key or on error.
    """
    if not raw_context or not raw_context.strip():
        return None
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        from anthropic import Anthropic
    except ImportError:
        return None

    goal = user_goal or "get help from the agent"
    prompt = f"""You are analyzing context that a simulated user will have in a conversation with an agent. The user's goal in the conversation is: {goal}.

Here is the context (raw data the user has access to):

---
{raw_context.strip()[:8000]}
---

Analyze it and output exactly two parts in this format (use the exact labels):

ANALYSIS: [1-3 sentences describing what information is in this context and when it would be relevant to mention in the conversation. Be generic: e.g. "vehicle identifiers", "customer details the agent may ask for", "key facts about the order".]

WHEN_AGENT_ASKS: [Write what a REAL PERSON would say conversationally to provide the key info. Use actual values from the context but phrase them NATURALLY, as if speaking to someone — NOT as raw data or JSON. For example, instead of 'vin: "ABC123", license_plate: "XY-456"' write 'My VIN is ABC123 and the plate number is XY-456'. Pick only the 2-4 most important pieces of info the agent would likely need. One or two natural sentences max.]
"""

    try:
        client = Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=400,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        analysis, when_agent_asks = _parse_analysis_response(text)
        if analysis and when_agent_asks:
            return {"analysis": analysis, "when_agent_asks": when_agent_asks}
        # Parsing failed — print debug info
        import sys
        print(f"[persona_context] WARNING: Could not parse LLM response:\n{text[:300]}", file=sys.stderr)
    except Exception as e:
        import sys
        print(f"[persona_context] ERROR analyzing context: {e}", file=sys.stderr)
    return None


def _parse_analysis_response(text: str) -> tuple[str | None, str | None]:
    """Extract ANALYSIS and WHEN_AGENT_ASKS from the LLM response."""
    analysis = None
    when_agent_asks = None
    # Match ANALYSIS: ... (until next label or end)
    m = re.search(r"ANALYSIS:\s*(.+?)(?=WHEN_AGENT_ASKS:|$)", text, re.DOTALL | re.IGNORECASE)
    if m:
        analysis = m.group(1).strip()
    m = re.search(r"WHEN_AGENT_ASKS:\s*(.+?)$", text, re.DOTALL | re.IGNORECASE)
    if m:
        when_agent_asks = m.group(1).strip()
    return analysis or None, when_agent_asks or None


DEFAULT_CONTEXT_FILE = Path(__file__).resolve().parents[2] / "config" / "persona_context_default.txt"


def load_default_persona_context() -> str | None:
    """Return the pre-made persona context (config/persona_context_default.txt),
    or None if the file doesn't exist / is empty."""
    try:
        if DEFAULT_CONTEXT_FILE.is_file():
            text = DEFAULT_CONTEXT_FILE.read_text(encoding="utf-8", errors="replace").strip()
            return text or None
    except Exception:
        pass
    return None


class PersonaContextError(Exception):
    """Raised when the persona-context choice is unusable or unstated."""


def resolve_persona_context(
    use_default: bool = False,
    context_file: str | Path | None = None,
    no_context: bool = False,
) -> str | None:
    """Resolve the persona context for a run, or raise.

    Whether context is loaded materially changes conversation shape, so a
    non-interactive run must state the choice rather than inherit one: on a
    non-TTY the interactive prompt hits EOF and silently yields "no context",
    which is not a choice anyone made.

    Every execution entry point should call this rather than reaching for
    ``prompt_for_persona_context`` directly, so the precedence rules and the
    non-TTY behaviour stay in one place.
    """
    chosen = [
        name
        for name, given in (
            ("--persona-context", use_default),
            ("--persona-context-file", context_file is not None),
            ("--no-persona-context", no_context),
        )
        if given
    ]
    if len(chosen) > 1:
        # Silently letting one win by branch order would reintroduce the exact
        # unannounced default this function exists to prevent.
        raise PersonaContextError(
            f"Conflicting persona-context options: {', '.join(chosen)}. Pass exactly one."
        )

    if no_context:
        return None

    if context_file is not None:
        path = Path(context_file)
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError as exc:
            raise PersonaContextError(f"Could not read persona context file {path}: {exc}") from exc
        if not text:
            raise PersonaContextError(f"Persona context file {path} is empty.")
        return text

    if use_default:
        text = load_default_persona_context()
        if not text:
            raise PersonaContextError(
                f"--persona-context requested but no usable default context was found at "
                f"{DEFAULT_CONTEXT_FILE}. Pass --persona-context-file PATH instead."
            )
        return text

    stdin = getattr(sys, "stdin", None)
    if stdin is None or not hasattr(stdin, "isatty") or not stdin.isatty():
        raise PersonaContextError(
            "Persona context is unset and stdin is not a terminal, so the "
            "interactive prompt cannot run.\n"
            "Choose explicitly:\n"
            "  --persona-context             use the default fake-customer context\n"
            "  --persona-context-file PATH   use your own context file\n"
            "  --no-persona-context          run without any persona context"
        )
    return prompt_for_persona_context()


def prompt_for_persona_context() -> str | None:
    """
    Ask in the terminal whether to add context for the personas.
    If a pre-made context exists (config/persona_context_default.txt) it is
    offered as the default. Otherwise accept either a file path or multiline
    inline text (end with . or blank line).
    Returns the context string, or None if skipped / invalid.
    """
    default_context = load_default_persona_context()
    if default_context:
        try:
            answer = input(
                f"Pre-made persona context found ({DEFAULT_CONTEXT_FILE.name} — fake customer data). "
                "Use it? (Y=use / n=none / c=custom) [Y]: "
            ).strip().lower() or "y"
        except (EOFError, KeyboardInterrupt):
            return None
        if answer in ("y", "yes"):
            return default_context
        if answer not in ("c", "custom"):
            return None
    else:
        try:
            answer = input("Do you want to add context for the personas to use? (y/n) [n]: ").strip().lower() or "n"
        except (EOFError, KeyboardInterrupt):
            return None
        if answer not in ("y", "yes"):
            return None

    print(
        "Enter a file path (e.g. ./context.txt), or paste your context and end with a line containing only '.'"
    )
    try:
        first_line = input("Path or first line: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not first_line:
        return None

    # Treat as file path if it looks like one and exists
    path = Path(first_line)
    if "/" in first_line or "\\" in first_line or path.suffix.lower() in (".txt", ".md", ".json", ".yaml", ".yml"):
        if not path.is_absolute():
            path = Path.cwd() / path
        if path.exists() and path.is_file():
            try:
                return path.read_text(encoding="utf-8", errors="replace").strip()
            except Exception:
                return None

    # Multiline inline: first line is start of content, read until "." or blank line
    lines = [first_line]
    while True:
        try:
            line = input()
        except (EOFError, KeyboardInterrupt):
            break
        if line.strip() in (".", "END", "end"):
            break
        lines.append(line)
        # Allow single line without terminator (user pressed Enter once after paste)
        if not line.strip():
            break
    return "\n".join(lines).strip() or None
