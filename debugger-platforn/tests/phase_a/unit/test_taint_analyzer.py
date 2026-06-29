"""
Sprint T — T.2.5 Taint Analyzer Tests
Validates Sprint 4 (intra-procedural taint/data-flow analysis).
"""

import pytest

from src.analysis.taint_analyzer import (
    TaintFlow,
    TaintSink,
    TaintSource,
    analyze_function_taint,
    analyze_taint,
    detect_pii_in_flow,
    identify_sinks,
    identify_sources,
    trace_flows,
)
from src.analysis.static_analyzer import (
    FileSymbols,
    FunctionInfo,
    Location,
    ParamInfo,
)
from src.risk.analyzer import analyze_risks, detect_taint_risks


# ── Helpers ──

def _func(
    name: str = "test_func",
    params: list[str] | None = None,
    body: str = "pass",
    file: str = "test.py",
    line: int = 1,
) -> FunctionInfo:
    return FunctionInfo(
        name=name,
        params=[ParamInfo(p, None, None) for p in (params or [])],
        docstring=None,
        decorators=[],
        body_text=body,
        location=Location(file=file, line=line),
        calls=[],
    )


def _sym(functions: list[FunctionInfo] | None = None) -> FileSymbols:
    return FileSymbols(
        file_path="test.py",
        language="python",
        functions=functions or [],
        classes=[],
        imports=[],
        variables=[],
        parse_errors=[],
    )


# ── T.2.5: Source identification ──

class TestIdentifySources:
    def test_user_input_parameter(self):
        """Parameter named 'user_input' -> TaintSource."""
        func = _func(params=["user_input", "config"])
        sources = identify_sources(func)
        assert len(sources) == 1
        assert sources[0].variable == "user_input"
        assert sources[0].source_type == "user_input"

    def test_message_parameter(self):
        func = _func(params=["message"])
        sources = identify_sources(func)
        assert len(sources) == 1
        assert sources[0].source_type == "user_input"

    def test_query_parameter(self):
        func = _func(params=["query"])
        sources = identify_sources(func)
        assert len(sources) == 1

    def test_non_sensitive_param_not_source(self):
        func = _func(params=["config", "timeout", "retries"])
        sources = identify_sources(func)
        assert len(sources) == 0

    def test_env_var_source(self):
        func = _func(body='api_key = os.environ["SECRET_KEY"]')
        sources = identify_sources(func)
        assert any(s.source_type == "env_var" for s in sources)

    def test_getenv_source(self):
        func = _func(body='token = os.getenv("TOKEN")')
        sources = identify_sources(func)
        assert any(s.source_type == "env_var" for s in sources)

    def test_retrieved_doc_source(self):
        func = _func(body='docs = vector_store.query(q)')
        sources = identify_sources(func)
        assert any(s.source_type == "retrieved_doc" for s in sources)


# ── T.2.5: Sink identification ──

class TestIdentifySinks:
    def test_requests_post_sink(self):
        """requests.post() call -> TaintSink."""
        func = _func(body='requests.post(url, data=payload)')
        sinks = identify_sinks(func)
        assert len(sinks) >= 1
        assert sinks[0].sink_type == "external_api"

    def test_eval_sink(self):
        func = _func(body='result = eval(expression)')
        sinks = identify_sinks(func)
        assert any(s.sink_type == "code_execution" for s in sinks)

    def test_exec_sink(self):
        func = _func(body='exec(code_str)')
        sinks = identify_sinks(func)
        assert any(s.sink_type == "code_execution" for s in sinks)

    def test_subprocess_sink(self):
        func = _func(body='subprocess.run(cmd)')
        sinks = identify_sinks(func)
        assert any(s.sink_type == "code_execution" for s in sinks)

    def test_print_sink(self):
        func = _func(body='print(data)')
        sinks = identify_sinks(func)
        assert any(s.sink_type == "logging" for s in sinks)

    def test_send_email_sink(self):
        func = _func(body='send_email(user_email, body)')
        sinks = identify_sinks(func)
        assert any(s.sink_type == "outbound_message" for s in sinks)

    def test_file_write_sink(self):
        func = _func(body='json.dump(data, f)')
        sinks = identify_sinks(func)
        assert any(s.sink_type == "file_write" for s in sinks)

    def test_no_sinks_in_safe_function(self):
        func = _func(body='x = 1 + 2\nreturn x')
        sinks = identify_sinks(func)
        assert len(sinks) == 0


# ── T.2.5: Flow tracing ──

class TestTraceFlows:
    def test_direct_flow_source_to_sink(self):
        """user_input passed to requests.post() -> TaintFlow."""
        func = _func(
            params=["user_input"],
            body="email = user_input\nrequests.post(url, data=email)",
        )
        sources = identify_sources(func)
        sinks = identify_sinks(func)
        flows = trace_flows(func, sources, sinks)
        assert len(flows) >= 1
        assert flows[0].source.variable == "user_input"

    def test_assignment_propagation(self):
        """user_input assigned to variable, variable reaches sink."""
        func = _func(
            params=["user_input"],
            body="email = user_input\npayload = email\nrequests.post(url, data=payload)",
        )
        sources = identify_sources(func)
        sinks = identify_sinks(func)
        flows = trace_flows(func, sources, sinks)
        assert len(flows) >= 1
        # Path should include intermediate variables
        path = flows[0].path
        assert "user_input" in path

    def test_no_flow_when_unconnected(self):
        """Internal variable not connected to sink -> no TaintFlow."""
        func = _func(
            params=["config"],  # not a source
            body="x = config\nrequests.post(url, data=x)",
        )
        sources = identify_sources(func)
        sinks = identify_sinks(func)
        flows = trace_flows(func, sources, sinks)
        assert len(flows) == 0

    def test_no_flow_without_sinks(self):
        """Read-only function (no sinks) -> no flows."""
        func = _func(params=["user_input"], body="result = user_input.upper()\nreturn result")
        sources = identify_sources(func)
        sinks = identify_sinks(func)
        assert len(sinks) == 0
        flows = trace_flows(func, sources, sinks)
        assert len(flows) == 0

    def test_no_flow_without_sources(self):
        func = _func(params=["config"], body="requests.post(url)")
        sources = identify_sources(func)
        sinks = identify_sinks(func)
        flows = trace_flows(func, sources, sinks)
        assert len(flows) == 0

    def test_string_format_propagation(self):
        """f-string with tainted var taints the result."""
        func = _func(
            params=["user_input"],
            body='msg = f"Hello {user_input}"\nprint(msg)',
        )
        sources = identify_sources(func)
        sinks = identify_sinks(func)
        flows = trace_flows(func, sources, sinks)
        assert len(flows) >= 1


# ── T.2.5: PII detection in flows ──

class TestPIIDetection:
    def test_email_in_variable_name(self):
        """Variable named 'email' in flow -> data_types=['email']."""
        flow = TaintFlow(
            source=TaintSource("user_email", "user_input", {}, "input"),
            sink=TaintSink("payload", "external_api", {}, "api call"),
            path=["user_email", "email_body", "payload"],
            data_types=[],
            risk_level="high",
        )
        detect_pii_in_flow(flow)
        assert "email" in flow.data_types

    def test_phone_in_variable_name(self):
        flow = TaintFlow(
            source=TaintSource("phone_number", "user_input", {}, "input"),
            sink=TaintSink("data", "external_api", {}, "api"),
            path=["phone_number", "data"],
            data_types=[],
            risk_level="high",
        )
        detect_pii_in_flow(flow)
        assert "phone" in flow.data_types

    def test_no_pii_in_safe_variable_names(self):
        flow = TaintFlow(
            source=TaintSource("query", "user_input", {}, "input"),
            sink=TaintSink("result", "logging", {}, "log"),
            path=["query", "processed", "result"],
            data_types=[],
            risk_level="low",
        )
        detect_pii_in_flow(flow)
        assert len(flow.data_types) == 0

    def test_multiple_pii_types(self):
        flow = TaintFlow(
            source=TaintSource("form", "user_input", {}, "input"),
            sink=TaintSink("data", "external_api", {}, "api"),
            path=["form", "email_field", "phone_field", "data"],
            data_types=[],
            risk_level="high",
        )
        detect_pii_in_flow(flow)
        assert "email" in flow.data_types
        assert "phone" in flow.data_types


# ── T.2.5: Full pipeline integration ──

class TestAnalyzeFunctionTaint:
    def test_full_analysis(self):
        """End-to-end: user_input -> assignment -> requests.post()."""
        func = _func(
            params=["user_input"],
            body="email = user_input\nrequests.post(url, data=email)",
        )
        flows = analyze_function_taint(func)
        assert len(flows) >= 1
        assert flows[0].risk_level == "high"
        assert len(flows[0].taxonomy_ids) > 0

    def test_code_execution_flow(self):
        """user_input -> eval() -> critical risk."""
        func = _func(
            params=["user_input"],
            body="expr = user_input\nresult = eval(expr)",
        )
        flows = analyze_function_taint(func)
        assert len(flows) >= 1
        assert flows[0].risk_level == "critical"
        assert "ASI05" in flows[0].taxonomy_ids
        assert "LLM01" in flows[0].taxonomy_ids


class TestAnalyzeTaintAcrossFiles:
    def test_analyzes_all_functions(self):
        f1 = _func("handler", params=["user_input"], body="requests.post(url, data=user_input)")
        f2 = _func("safe_func", params=["x"], body="return x + 1")
        sym = _sym(functions=[f1, f2])
        flows = analyze_taint([sym])
        assert len(flows) >= 1  # at least the handler flow
        # safe_func should produce no flows
        safe_flows = [f for f in flows if f.source.variable == "x"]
        assert len(safe_flows) == 0


class TestDetectTaintRisks:
    def test_taint_flow_becomes_risk_flag(self):
        func = _func(
            params=["user_input"],
            body="email = user_input\nrequests.post(url, data=email)",
        )
        sym = _sym(functions=[func])
        risks, flows = detect_taint_risks([sym])
        assert len(risks) >= 1
        assert risks[0].risk_type == "taint_flow"
        assert len(flows) >= 1

    def test_taint_risks_in_analyze_risks(self):
        """Taint risks appear in analyze_risks() output when all_symbols provided."""
        from src.patterns.detector import ToolDefinition
        func = _func(
            params=["user_input"],
            body="email = user_input\nrequests.post(url, data=email)",
        )
        sym = _sym(functions=[func])
        risks, flows = analyze_risks([], [], all_symbols=[sym])
        taint_risks = [r for r in risks if r.risk_type == "taint_flow"]
        assert len(taint_risks) >= 1
        assert len(flows) >= 1

    def test_regex_pii_still_works_as_fallback(self):
        """Existing regex PII detection still produces risks alongside taint."""
        from src.patterns.detector import ToolDefinition
        tool = ToolDefinition(
            id="t", name="send_email", description="Sends to user@example.com",
            parameters=[{"name": "email", "type": "str"}],
            source="test", location={"file": "t.py", "line": 1},
            confidence=0.9, risk_level="low", sandbox_safe=True, code_snippet="",
        )
        risks, _ = analyze_risks([tool], [])
        pii_risks = [r for r in risks if r.risk_type == "pii"]
        assert len(pii_risks) >= 1  # regex still finds it
