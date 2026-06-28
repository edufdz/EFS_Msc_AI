"""Phase C: Execute Tests — API routes."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from web.api.config import PROJECT_ROOT
from web.api.models.requests import PhaseCRequest
from web.api.models.responses import PhaseStatusResponse
from web.api.services.progress_emitter import ProgressEmitter
from web.api.services.session_manager import session_manager
from web.api.ws import ws_manager

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

router = APIRouter(prefix="/api/phase-c", tags=["phase-c"])


async def _run_phase_c_async(req: PhaseCRequest, emitter: ProgressEmitter) -> dict:
    """Run Phase C asynchronously."""
    import random as _random

    from src.endpoints_config import apply_endpoints_to_agent_map
    from src.execution.agent_connector import APIAgentConnector, MockAgentConnector, VictoriaConnector
    from src.execution.aggregator import ResultsAggregator
    from src.execution.persona_context import analyze_persona_context
    from src.execution.runner import TestExecutionEngine

    session = session_manager.get_session(req.session_id)
    output_dir = Path(session.output_dir) / "results"
    output_dir.mkdir(parents=True, exist_ok=True)

    if req.seed is not None:
        _random.seed(req.seed)

    # Load test suite
    test_suite_path = session.artifacts.get("test-suite")
    if not test_suite_path:
        # Try finding it
        candidates = [
            Path(session.output_dir) / "generated" / "test_suite.json",
            Path(session.output_dir) / "test_suite.json",
        ]
        for c in candidates:
            if c.exists():
                test_suite_path = str(c)
                break
    if not test_suite_path or not Path(test_suite_path).exists():
        raise ValueError("Test suite not found. Run Phase B first.")

    with open(test_suite_path) as f:
        test_suite_full = json.load(f)

    # Load agent map
    agent_map_path = Path(session.output_dir) / "agent_map.json"
    if not agent_map_path.exists():
        raise ValueError("Agent map not found. Run Phase A first.")

    with open(agent_map_path) as f:
        agent_map = json.load(f)

    apply_endpoints_to_agent_map(agent_map, str(agent_map_path))

    # Override with user-provided endpoint from the UI
    if req.agent_endpoint:
        agent_map["api_endpoint"] = req.agent_endpoint.rstrip("/")

    # Language detection
    language = req.language or agent_map.get("metadata", {}).get("conversation_language", "English")
    if language.lower() in ("spanish", "español", "espanol", "es"):
        language = "Spanish"
    elif language.lower() in ("english", "en"):
        language = "English"

    # Limit test count
    test_suite = dict(test_suite_full)
    if req.count > 0:
        test_suite["test_cases"] = test_suite_full["test_cases"][:req.count]

    # Persona context analysis
    persona_context_analyzed = None
    if req.persona_context:
        sample_goal = None
        for tc in test_suite.get("test_cases", [])[:1]:
            sample_goal = tc.get("scenario", {}).get("user_goal")
            break
        try:
            persona_context_analyzed = analyze_persona_context(req.persona_context, user_goal=sample_goal)
        except Exception:
            pass

    emitter.emit("creating_connector", "Setting up connector...", 10)

    # Create connector
    if req.mock:
        connector = MockAgentConnector(
            agent_map,
            fail_rate=req.fail_rate,
            tool_call_rate=0.4,
            language=language,
        )
    else:
        framework = agent_map.get("metadata", {}).get("framework", "")
        api_endpoint = agent_map.get("api_endpoint") or agent_map.get("metadata", {}).get("api_endpoint", "")
        is_victoria = (
            "victoria" in api_endpoint.lower()
            or (framework == "custom" and agent_map.get("metadata", {}).get("type") == "sales")
        )
        connector = VictoriaConnector(agent_map) if is_victoria else APIAgentConnector(agent_map)

    # Traces
    traces_dir = str(output_dir / "traces") if req.traces else None

    # Conversation log
    conversation_log_file = str(output_dir / "conversations.log")
    Path(conversation_log_file).write_text("")

    emitter.emit("starting_engine", "Starting test execution engine...", 20)

    started_at = datetime.now(timezone.utc)

    # Build LLM config from request (None = use default Anthropic)
    llm_config = None
    if req.llm_provider:
        from src.execution.llm_config import LLMProviderConfig
        llm_config = LLMProviderConfig(
            provider=req.llm_provider,
            model=req.llm_model,
            base_url=req.llm_base_url,
        )

    engine = TestExecutionEngine(
        test_suite=test_suite,
        agent_connector=connector,
        max_workers=req.workers,
        use_ai_personas=req.ai_personas,
        traces_dir=traces_dir,
        language=language,
        conversation_log_file=conversation_log_file,
        agent_map=agent_map,
        persona_context=req.persona_context,
        persona_context_analyzed=persona_context_analyzed,
        persona_config=llm_config,
        critic_config=llm_config,
    )

    # Forward engine events to WS clients, enriching with running totals
    queue = ws_manager.get_queue(req.session_id)

    # Extract all tool names from agent_map for tool coverage tracking
    all_tools = [
        t["name"]
        for t in agent_map.get("components", {}).get("tools", [])
    ]
    # Fallback: try test_suite summary
    if not all_tools:
        all_tools = list(
            test_suite.get("summary", {}).get("tool_invocation_counts", {}).keys()
        )

    async def _forward_events():
        totals = {
            "passed": 0, "failed": 0, "errors": 0, "timeouts": 0,
            "completed": 0, "total_tests": len(engine.test_cases),
            "total_cost_usd": 0.0, "pass_rate": 0.0,
            "tools_covered": 0, "tools_total": len(all_tools),
        }
        tools_seen: set[str] = set()

        while True:
            try:
                event = await asyncio.wait_for(engine.event_queue.get(), timeout=0.3)
                etype = event.get("type")

                if etype == "run_started":
                    event["_totals"] = dict(totals)
                    event["tools_called"] = all_tools

                elif etype == "test_completed":
                    status = event.get("status", "")
                    totals["completed"] += 1
                    if status == "passed":
                        totals["passed"] += 1
                    elif status == "failed":
                        totals["failed"] += 1
                    elif status == "error":
                        totals["errors"] += 1
                    elif status == "timeout":
                        totals["timeouts"] += 1
                    totals["total_cost_usd"] += event.get("cost_usd", 0) or 0
                    if totals["completed"] > 0:
                        totals["pass_rate"] = round(
                            totals["passed"] / totals["completed"] * 100, 1
                        )
                    event["_totals"] = dict(totals)

                elif etype == "tool_called":
                    tool_name = event.get("tool_name", "")
                    if tool_name and tool_name not in tools_seen:
                        tools_seen.add(tool_name)
                        totals["tools_covered"] = len(tools_seen)

                elif etype == "run_completed":
                    if totals["completed"] > 0:
                        event["pass_rate"] = round(
                            totals["passed"] / totals["completed"] * 100, 1
                        )

                await ws_manager.broadcast(req.session_id, event)
                if etype == "run_completed":
                    return
            except asyncio.TimeoutError:
                continue

    forward_task = asyncio.create_task(_forward_events())

    # Execute
    results = await engine.run_all()

    # Wait for event forwarding to finish
    try:
        await asyncio.wait_for(forward_task, timeout=5.0)
    except asyncio.TimeoutError:
        forward_task.cancel()

    emitter.emit("generating_reports", "Generating reports...", 85)

    # Aggregate results
    aggregator = ResultsAggregator(test_suite, results)
    report = aggregator.save_report(output_dir / "test_run_report.json", started_at)

    # Register common artifacts
    session_manager.set_artifact(req.session_id, "test-report", str(output_dir / "test_run_report.json"))
    session_manager.set_artifact(req.session_id, "conversation-log", conversation_log_file)

    # Run AI-powered failure triage (or skip if validate=False)
    triage_summary = None
    if req.validate:
        emitter.emit("validating", "Triaging failures with AI...", 90)
        loop = asyncio.get_event_loop()
        validated_inbox, validation_report, validation = await loop.run_in_executor(
            None,
            aggregator.validate_and_save,
            output_dir,      # results_dir
            agent_map,        # agent_map
            True,             # use_ai (always AI)
            None,             # retry_config
            None,             # on_progress
            engine.event_queue,  # event_queue for validation_completed event
        )
        session_manager.set_artifact(
            req.session_id, "failure-inbox",
            str(output_dir / "validated_failure_inbox.json")
        )
        session_manager.set_artifact(
            req.session_id, "validation-report",
            str(output_dir / "validation_report.json")
        )
        triage_summary = {
            "genuine_failures": validation.summary.get("genuine_failures", 0),
            "persona_filtered": validation.summary.get("persona_incompetence_filtered", 0),
            "chaos_filtered": validation.summary.get("chaos_induced_filtered", 0),
            "false_successes": validation.summary.get("false_successes_caught", 0),
        }
    else:
        inbox = aggregator.save_failure_inbox(output_dir / "failure_inbox.json")
        session_manager.set_artifact(
            req.session_id, "failure-inbox",
            str(output_dir / "failure_inbox.json")
        )

    result = {
        "total_tests": report.total_tests,
        "passed": report.passed,
        "failed": report.failed,
        "errors": report.errors,
        "timeouts": report.timeouts,
        "pass_rate": report.pass_rate,
        "total_duration_sec": report.total_duration_sec,
        "total_cost_usd": report.total_cost_usd,
        "tool_coverage_pct": report.coverage_pct,
        "tools_not_covered": report.tools_not_covered,
        "by_difficulty": report.by_difficulty,
        "triage": triage_summary,
    }
    return result


@router.post("/run")
async def run_phase_c(req: PhaseCRequest):
    session = session_manager.get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.phase_status.get("c") == "running":
        raise HTTPException(status_code=409, detail="Phase C already running")

    if "b" not in session.phases_completed:
        raise HTTPException(status_code=400, detail="Phase B must be completed first")

    session_manager.set_phase_status(req.session_id, "c", "running")
    emitter = ProgressEmitter(req.session_id, "c")
    queue = ws_manager.get_queue(req.session_id)
    emitter.add_listener(queue)

    async def _run():
        try:
            result = await _run_phase_c_async(req, emitter)
            session_manager.set_phase_status(req.session_id, "c", "completed")
            session_manager.set_phase_result(req.session_id, "c", result)
            emitter.emit_complete(result)
        except Exception as e:
            session_manager.set_phase_status(req.session_id, "c", "error")
            emitter.emit_error(f"{type(e).__name__}: {e}")
            traceback.print_exc()
        finally:
            emitter.remove_listener(queue)

    asyncio.create_task(_run())
    return {"status": "started", "session_id": req.session_id}


@router.get("/traces/{session_id}")
async def get_phase_c_traces(session_id: str):
    """Return all saved trace files for a Phase C run."""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    output_dir = Path(session.output_dir) / "results" / "traces"
    if not output_dir.exists():
        # Also check without results/ prefix
        output_dir = Path(session.output_dir) / "traces"
    if not output_dir.exists():
        return {"traces": []}

    traces = []
    for trace_file in sorted(output_dir.glob("trace_*.json")):
        try:
            data = json.loads(trace_file.read_text())
            # Map to the shape expected by the frontend activeTests store
            tool_calls = []
            for tool_name in data.get("tools_called_sequence", []):
                tool_calls.append({"tool_name": tool_name, "status": "success"})
            # Also add from tool_results if available
            if not tool_calls and data.get("tool_results"):
                for tr in data["tool_results"]:
                    tool_calls.append({
                        "tool_name": tr.get("tool_name", tr.get("name", "unknown")),
                        "status": "success" if tr.get("success", True) else "error",
                    })

            turns = []
            for t in data.get("turns", []):
                turns.append({
                    "turn": t.get("turn_number", 0),
                    "role": t.get("role", ""),
                    "message": t.get("message", ""),
                    "duration_ms": t.get("duration_ms", 0),
                })

            traces.append({
                "test_id": data.get("test_id", ""),
                "test_number": data.get("test_number", 0),
                "scenario": data.get("scenario_title", ""),
                "persona": data.get("persona_name", ""),
                "difficulty": data.get("difficulty", "medium"),
                "status": data.get("status", "unknown"),
                "turns": turns,
                "tool_calls": tool_calls,
            })
        except Exception:
            continue

    return {"traces": traces}


@router.get("/status/{session_id}", response_model=PhaseStatusResponse)
async def get_phase_c_status(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    prog = session.phase_progress.get("c", {})
    return PhaseStatusResponse(
        session_id=session_id,
        phase="c",
        status=session.phase_status.get("c", "idle"),
        progress_pct=prog.get("pct", 0),
        message=prog.get("message", ""),
        result=session.phase_results.get("c"),
    )
