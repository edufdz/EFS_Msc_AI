"""Configuration settings for the web API."""

from __future__ import annotations

import os
from pathlib import Path

# Project root (debugger-platforn/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Default output directory for pipeline runs
OUTPUT_BASE_DIR = PROJECT_ROOT / "pipeline_output"

# Ensure output dir exists
OUTPUT_BASE_DIR.mkdir(parents=True, exist_ok=True)

# CORS origins allowed (dev + prod)
CORS_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
]

# Default phase parameters
PHASE_A_DEFAULTS = {
    "skip_ai": False,
    "language": None,
    "prompt_encoding": "utf-8",
}

PHASE_B_DEFAULTS = {
    "skip_ai": False,
    "count": 150,
    "persona_count": 8,
    "scenario_count": 10,
    "variants": 3,
    "seed": None,
    "language": None,
    "use_tlahuac": False,
    "tlahuac_dir": None,
    "include_templates": False,
}

PHASE_C_DEFAULTS = {
    "mock": False,
    "workers": 10,
    "count": 10,
    "ai_personas": True,
    "traces": True,
    "fail_rate": 0.05,
    "seed": None,
    "language": None,
    "persona_context": None,
}
