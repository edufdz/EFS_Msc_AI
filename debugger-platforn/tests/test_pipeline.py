"""
Pipeline integration tests.
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Offline tests that verify the unified Phase B generator, the C→D→E
chaining via --improve, and the master pipeline with --stop-after.

All tests use --skip-ai and --mock so they run without API keys.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

SAMPLE_AGENT_DIR = Path(__file__).parent / "sample_agent"


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------

def _make_agent_map(tmp_path: Path) -> Path:
    """Create a minimal agent_map.json and return its path."""
    agent_map = {
        "metadata": {
            "type": "support",
            "purpose": "Help users with account issues",
            "framework": "custom",
            "conversation_language": "English",
        },
        "components": {
            "tools": [
                {
                    "name": "lookup_account",
                    "description": "Look up a user account by ID",
                    "source": "code",
                    "risk_level": "low",
                    "parameters": [{"name": "account_id", "type": "string"}],
                },
                {
                    "name": "reset_password",
                    "description": "Reset a user password",
                    "source": "code",
                    "risk_level": "high",
                    "parameters": [{"name": "account_id", "type": "string"}],
                },
            ],
            "prompts": [],
        },
        "risk_flags": {"all_risks": []},
    }
    path = tmp_path / "agent_map.json"
    path.write_text(json.dumps(agent_map, indent=2))
    return path


# ---------------------------------------------------------------
# Test 1: Unified Phase B generator
# ---------------------------------------------------------------

def test_generate_tests_unified(tmp_path):
    """Run generate_tests.py with --skip-ai and verify test_suite.json is produced."""
    from generate_tests import main as gen_main

    agent_map_path = _make_agent_map(tmp_path)
    output_dir = tmp_path / "generated"

    runner = CliRunner()
    result = runner.invoke(gen_main, [
        str(agent_map_path),
        "--output-dir", str(output_dir),
        "--skip-ai",
        "--count", "15",
        "--seed", "42",
    ])

    assert result.exit_code == 0, f"CLI failed: {result.output}"

    # Verify all four Phase B outputs exist
    assert (output_dir / "test_configuration.json").exists(), "Missing test_configuration.json"
    assert (output_dir / "persona_library.json").exists(), "Missing persona_library.json"
    assert (output_dir / "scenario_catalog.json").exists(), "Missing scenario_catalog.json"
    assert (output_dir / "test_suite.json").exists(), "Missing test_suite.json"

    # Verify test_suite.json has test cases
    with open(output_dir / "test_suite.json") as f:
        suite = json.load(f)
    assert "test_cases" in suite
    assert len(suite["test_cases"]) > 0


# ---------------------------------------------------------------
# Test 2: execute_tests.py with --diagnose --improve
# ---------------------------------------------------------------

def test_execute_with_improve(tmp_path):
    """Run execute_tests.py with --diagnose --improve --skip-ai and verify improvement outputs."""
    from generate_tests import main as gen_main
    from execute_tests import main as exec_main

    agent_map_path = _make_agent_map(tmp_path)

    # Step 1: Generate a small test suite
    gen_dir = tmp_path / "generated"
    runner = CliRunner()
    result = runner.invoke(gen_main, [
        str(agent_map_path),
        "--output-dir", str(gen_dir),
        "--skip-ai",
        "--count", "10",
        "--seed", "42",
    ])
    assert result.exit_code == 0, f"generate_tests failed: {result.output}"

    suite_path = gen_dir / "test_suite.json"
    assert suite_path.exists()

    # Step 2: Execute with --diagnose --improve (high fail rate to guarantee failures)
    results_dir = tmp_path / "results"
    result = runner.invoke(exec_main, [
        str(suite_path),
        str(agent_map_path),
        "--output", str(results_dir),
        "--mock",
        "--fail-rate", "0.5",
        "--count", "10",
        "--no-monitor",
        "--diagnose",
        "--improve",
        "--skip-ai",
        "--seed", "1",
    ])

    assert result.exit_code == 0, f"execute_tests failed: {result.output}"

    # Verify Phase C outputs
    assert (results_dir / "test_run_report.json").exists(), "Missing test_run_report.json"
    assert (results_dir / "failure_inbox.json").exists(), "Missing failure_inbox.json"

    # Check if there were failures (with 50% fail rate there should be)
    with open(results_dir / "failure_inbox.json") as f:
        inbox = json.load(f)
    total_failures = inbox.get("total_failures", 0)

    if total_failures > 0:
        # Verify Phase D output
        assert (results_dir / "diagnosis_report.json").exists(), "Missing diagnosis_report.json"

        # Check if fix proposals were generated
        with open(results_dir / "diagnosis_report.json") as f:
            diag = json.load(f)
        n_fixes = len(diag.get("fix_proposals", []))

        if n_fixes > 0:
            # Verify Phase E outputs
            improvement_dir = results_dir / "improvement"
            assert improvement_dir.exists(), "Missing improvement directory"
            assert (improvement_dir / "applied_fixes.json").exists(), "Missing applied_fixes.json"
            assert (improvement_dir / "ab_test_results.json").exists(), "Missing ab_test_results.json"
            assert (improvement_dir / "improvement_report.json").exists(), "Missing improvement_report.json"


# ---------------------------------------------------------------
# Test 3: run_pipeline.py with --stop-after c
# ---------------------------------------------------------------

def test_pipeline_stop_after(tmp_path):
    """Run pipeline with --stop-after c and verify no diagnosis/improvement outputs."""
    from run_pipeline import main as pipeline_main

    output_dir = tmp_path / "pipeline_output"

    runner = CliRunner()
    result = runner.invoke(pipeline_main, [
        str(SAMPLE_AGENT_DIR),
        "--output-dir", str(output_dir),
        "--mock",
        "--skip-ai",
        "--test-count", "10",
        "--count", "5",
        "--stop-after", "c",
        "--seed", "42",
    ])

    assert result.exit_code == 0, f"run_pipeline failed: {result.output}"

    # Phase A output should exist
    assert (output_dir / "agent_map.json").exists(), "Missing agent_map.json"

    # Phase B outputs should exist
    gen_dir = output_dir / "generated"
    assert (gen_dir / "test_suite.json").exists(), "Missing test_suite.json"

    # Phase C outputs should exist
    results_dir = output_dir / "results"
    assert (results_dir / "test_run_report.json").exists(), "Missing test_run_report.json"

    # Phase D output should NOT exist (we stopped after C)
    assert not (results_dir / "diagnosis_report.json").exists(), "diagnosis_report.json should not exist with --stop-after c"

    # Phase E output should NOT exist
    assert not (output_dir / "improvement").exists(), "improvement/ should not exist with --stop-after c"
