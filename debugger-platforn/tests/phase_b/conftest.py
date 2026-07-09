"""
Shared fixtures for the Phase B enhancement test-suite (Sprint E-T).

Provides a session-scoped, cached generator that drives the *real* Phase B
CLI (``generate_tests.main``) through Click's ``CliRunner`` in fully offline
mode (``--skip-ai --include-templates``). Because generation is deterministic
in structure (a fixed ``--seed`` is passed), the same configuration is only
run once and its loaded outputs are reused across tests.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

import pytest
from click.testing import CliRunner

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from generate_tests import main as gen_main  # noqa: E402
from src.generator.models import TestSuite  # noqa: E402

from .fixtures import helpers  # noqa: E402


class GeneratedSuite:
    """Loaded Phase B outputs for one generation run."""

    def __init__(self, out_dir: Path, cli_output: str, agent_map: Dict[str, Any]):
        self.out_dir = out_dir
        self.cli_output = cli_output
        self.agent_map = agent_map
        self.suite_raw: Dict[str, Any] = json.loads((out_dir / "test_suite.json").read_text())
        self.suite: TestSuite = TestSuite.model_validate(self.suite_raw)
        self.catalog: Dict[str, Any] = json.loads((out_dir / "scenario_catalog.json").read_text())
        self.library: Dict[str, Any] = json.loads((out_dir / "persona_library.json").read_text())
        self.config: Dict[str, Any] = json.loads((out_dir / "test_configuration.json").read_text())

    @property
    def scenario_sources(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for s in self.catalog["scenarios"]:
            counts[s["source"]] = counts.get(s["source"], 0) + 1
        return counts

    @property
    def persona_sources(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for p in self.library["personas"]:
            counts[p["source"]] = counts.get(p["source"], 0) + 1
        return counts

    def scenarios_with_source(self, source: str) -> list:
        return [s for s in self.catalog["scenarios"] if s["source"] == source]


@pytest.fixture(scope="session")
def phase_b():
    """Factory returning cached :class:`GeneratedSuite` objects.

    Signature: ``phase_b(map_name="tech_repair", use_traces=False, count=40,
    variants=2, seed=42, extra=None)``.
    """
    cache: Dict[tuple, GeneratedSuite] = {}
    tmp_root = Path(
        os.environ.get("PYTEST_PHASE_B_TMP", "")
    ) if os.environ.get("PYTEST_PHASE_B_TMP") else None

    import tempfile

    base_dir = Path(tempfile.mkdtemp(prefix="phase_b_et_")) if tmp_root is None else tmp_root

    def run(
        map_name: str = "tech_repair",
        use_traces: bool = False,
        count: int = 40,
        variants: int = 2,
        seed: int = 42,
        extra: Optional[Sequence[str]] = None,
    ) -> GeneratedSuite:
        key = (map_name, use_traces, count, variants, seed, tuple(extra or ()))
        if key in cache:
            return cache[key]

        out_dir = base_dir / ("_".join(str(k) for k in ("gen", map_name, use_traces, count, seed))
                              + f"_{len(cache)}")
        args = [
            str(helpers.agent_map_path(map_name)),
            "--output-dir", str(out_dir),
            "--skip-ai", "--include-templates",
            "--count", str(count), "--variants", str(variants), "--seed", str(seed),
        ]
        if use_traces:
            args += ["--use-traces", "--traces-file", str(helpers.traces_path())]
        if extra:
            args += list(extra)

        result = CliRunner().invoke(gen_main, args, env={"ANTHROPIC_API_KEY": ""})
        if result.exit_code != 0:
            raise AssertionError(
                f"Phase B generation failed (exit {result.exit_code}) for {key}:\n"
                f"{result.output}\n{result.exception!r}"
            )
        loaded = GeneratedSuite(out_dir, result.output, helpers.load_agent_map(map_name))
        cache[key] = loaded
        return loaded

    return run
