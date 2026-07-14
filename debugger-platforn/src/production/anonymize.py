"""
Anonymisation adapter for production data flowing into generated artefacts.

The full anonymisation platform lives in the sibling ``anonymization/``
directory (three passes: regex PII -> Spanish NER -> brand scrub).  Whenever
its backend is importable, production text entering seeds/scenarios goes
through it; otherwise we fall back to the built-in regex redactor from the
seed corpus (emails, phone numbers, long IDs).

The fallback is deliberately conservative-but-weaker: it never blocks the
research pipeline, but the returned anonymiser reports which level is active
so runs can record it.  For the dissertation's ethics chapter, run with the
full pipeline installed (``pip install -r anonymization/backend/requirements.txt``).
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Callable, Tuple

from src.scenarios.seed_corpus import _anonymise as _regex_fallback

# anonymization/ sits next to the debugger-platforn directory
_ANONYMIZATION_ROOT = Path(__file__).resolve().parents[3] / "anonymization"


@lru_cache(maxsize=1)
def get_anonymiser() -> Tuple[Callable[[str], str], str]:
    """Return ``(anonymise_fn, level)``.

    level is ``"full"`` (regex + NER + brand pipeline) or ``"regex_fallback"``.
    The function is cached: the NER model load is expensive and must happen
    at most once per process.
    """
    backend_dir = _ANONYMIZATION_ROOT / "backend"
    if backend_dir.exists():
        # The anonymisation backend uses flat intra-package imports
        # (``from brand_scrub import ...``), so its directory itself must be
        # on sys.path.
        path = str(backend_dir)
        if path not in sys.path:
            sys.path.insert(0, path)
        try:
            from pipeline import anonymize_text  # type: ignore

            # Probe once so a missing spaCy model fails here, not mid-run.
            anonymize_text("probe: juan.perez@example.com 5512345678")
            return anonymize_text, "full"
        except Exception:
            pass
    return _regex_fallback, "regex_fallback"


def anonymise(text: str) -> str:
    """Anonymise *text* with the strongest available pipeline."""
    fn, _ = get_anonymiser()
    return fn(text)
