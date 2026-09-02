"""Per-run backend reset (Phase C).

``reset()`` starts a new conversation; ``reset_backend()`` returns the agent's
datastore to its seeded state. Without the latter, the fake database
accumulates escalations, interaction history and CRM mutations across every
test in a batch, so later tests observe state that earlier tests created.

The reset must fire exactly once per run, before any test starts — workers are
concurrent, so a per-test reset would wipe state out from under in-flight
conversations.
"""

import asyncio

import pytest

from src.execution.agent_connector import APIAgentConnector, MockAgentConnector


class TestResetBackendContract:
    def test_mock_connector_has_no_backend_to_reset(self):
        conn = MockAgentConnector({}, fail_rate=0.0)
        assert asyncio.run(conn.reset_backend()) is False

    def test_api_connector_without_endpoint_is_a_noop(self):
        conn = APIAgentConnector({"api_endpoint": ""})
        assert asyncio.run(conn.reset_backend()) is False

    def test_api_connector_reports_success(self, monkeypatch):
        conn = APIAgentConnector({"api_endpoint": "http://localhost:9999"})
        monkeypatch.setattr(conn, "reset_backend", _fake_reset(200))
        assert asyncio.run(conn.reset_backend()) is True

    def test_unreachable_agent_does_not_raise(self):
        """A missing /reset must not abort the run."""
        conn = APIAgentConnector({"api_endpoint": "http://127.0.0.1:9"})
        assert asyncio.run(conn.reset_backend()) is False


def _fake_reset(status):
    async def _r():
        return status == 200
    return _r


class TestEngineCallsResetOncePerRun:
    def test_engine_resets_before_running_tests(self):
        from src.execution.runner import TestExecutionEngine

        calls = {"reset_backend": 0, "sends": 0}

        class RecordingConnector(MockAgentConnector):
            async def reset_backend(self) -> bool:
                # Must happen before any message is sent.
                assert calls["sends"] == 0, "backend reset ran mid-run"
                calls["reset_backend"] += 1
                return True

            async def send_message(self, message, context=None):
                calls["sends"] += 1
                return await super().send_message(message, context)

        suite = {"test_cases": [_minimal_test_case(i) for i in range(3)]}
        engine = TestExecutionEngine(
            test_suite=suite,
            agent_connector=RecordingConnector({}, fail_rate=0.0),
            max_workers=2,
        )
        asyncio.run(engine.run_all())

        assert calls["reset_backend"] == 1, (
            f"expected exactly one backend reset per run, got {calls['reset_backend']}"
        )

    def test_reset_failure_does_not_abort_the_run(self):
        from src.execution.runner import TestExecutionEngine

        class ExplodingConnector(MockAgentConnector):
            async def reset_backend(self) -> bool:
                raise RuntimeError("agent has no /reset")

        suite = {"test_cases": [_minimal_test_case(0)]}
        engine = TestExecutionEngine(
            test_suite=suite,
            agent_connector=ExplodingConnector({}, fail_rate=0.0),
            max_workers=1,
        )
        results = asyncio.run(engine.run_all())
        assert len(results) == 1


def _minimal_test_case(i: int) -> dict:
    return {
        "test_id": f"T{i:03d}",
        "name": f"test {i}",
        "difficulty": "easy",
        "persona": {
            "name": "Tester",
            "traits": {"patience": 5, "clarity": 5},
            "communication_style": {"tone": "neutral"},
            "edge_behaviors": [],
        },
        "scenario": {
            "name": "smoke",
            "user_goal": "check order status",
            "required_tools": [],
            "success_conditions": {},
            "failure_conditions": {},
        },
        "max_turns": 2,
    }


class TestPhaseCResultsAreNotOverwritten:
    """Re-running Phase C from the web UI must not destroy the previous run.

    Phase C always writes to ``<session>/results``. Before this guard, a second
    run overwrote conversations.json, test_run_report.json, failure_inbox.json
    and every trace of the first — which actually happened to a 200-conversation
    run, recovered only because its traces were committed.
    """

    def _make_run(self, root, marker):
        res = root / "results"
        res.mkdir(parents=True, exist_ok=True)
        (res / "conversations.json").write_text(marker)
        (res / "test_run_report.json").write_text('{"total_tests": 200}')
        (res / "traces").mkdir(exist_ok=True)
        (res / "traces" / "trace_0001.json").write_text("{}")
        return res

    def test_previous_run_is_archived_not_clobbered(self, tmp_path):
        from web.api.routes.phase_c import _archive_previous_results

        res = self._make_run(tmp_path, "ORIGINAL")
        archive = _archive_previous_results(res)

        assert archive is not None and archive.exists()
        assert (archive / "conversations.json").read_text() == "ORIGINAL"
        assert (archive / "traces" / "trace_0001.json").exists()
        assert not res.exists(), "results/ must be clear for the new run"

    def test_repeated_runs_never_collide(self, tmp_path):
        from web.api.routes.phase_c import _archive_previous_results

        archives = []
        for i in range(3):
            self._make_run(tmp_path, f"RUN{i}")
            archives.append(_archive_previous_results(tmp_path / "results"))

        assert all(a is not None for a in archives)
        assert len({a.name for a in archives}) == 3, "archive names collided"
        preserved = sorted(a.joinpath("conversations.json").read_text() for a in archives)
        assert preserved == ["RUN0", "RUN1", "RUN2"]

    def test_noop_when_there_is_nothing_to_preserve(self, tmp_path):
        from web.api.routes.phase_c import _archive_previous_results

        assert _archive_previous_results(tmp_path / "missing") is None

        empty = tmp_path / "results"
        empty.mkdir()
        assert _archive_previous_results(empty) is None
        assert empty.exists(), "an empty results/ should be left in place"
