"""Unit tests for pattern detector — Sprint 2 (preconditions/side-effects) enhancements."""

import os

import pytest

from src.analysis.static_analyzer import (
    parse_python_file,
    FunctionInfo,
    ParamInfo,
    Location,
)
from src.patterns.detector import (
    detect_patterns,
    extract_all_tools,
    detect_framework,
    _extract_side_effects,
    _extract_preconditions_from_code,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")


# ---------------------------------------------------------------------------
# Side-effect extraction (Sprint 2)
# ---------------------------------------------------------------------------

class TestSideEffectExtraction:
    def _make_func(self, body: str) -> FunctionInfo:
        return FunctionInfo(
            name="test_fn", params=[], docstring=None, decorators=[],
            body_text=body, location=Location(file="t.py", line=1),
        )

    def test_db_write_detected(self):
        effects, mod = _extract_side_effects(self._make_func(
            "db.execute('UPDATE users SET name=?', name); db.commit()"
        ))
        assert mod is True
        assert any("database" in e.lower() for e in effects)

    def test_http_post_detected(self):
        effects, mod = _extract_side_effects(self._make_func(
            "requests.post('https://api.com/data', json=payload)"
        ))
        assert mod is True
        assert any("http" in e.lower() or "post" in e.lower() for e in effects)

    def test_file_write_detected(self):
        effects, mod = _extract_side_effects(self._make_func(
            "with open('out.csv', 'w') as f: f.write(data)"
        ))
        assert mod is True
        assert any("file" in e.lower() for e in effects)

    def test_email_send_detected(self):
        effects, mod = _extract_side_effects(self._make_func(
            "send_email(user.email, 'Subject', 'Body')"
        ))
        assert mod is True
        assert any("email" in e.lower() or "notification" in e.lower() for e in effects)

    def test_read_only_function(self):
        effects, mod = _extract_side_effects(self._make_func(
            "result = requests.get('/api/data'); return result.json()"
        ))
        assert mod is False
        assert effects == []

    def test_empty_body(self):
        effects, mod = _extract_side_effects(self._make_func(""))
        assert effects == []

    def test_session_state_detected(self):
        effects, mod = _extract_side_effects(self._make_func(
            "session['user_id'] = user_id"
        ))
        assert mod is True


# ---------------------------------------------------------------------------
# Precondition extraction (Sprint 2)
# ---------------------------------------------------------------------------

class TestPreconditionExtraction:
    def _make_func(self, body: str) -> FunctionInfo:
        return FunctionInfo(
            name="test_fn", params=[], docstring=None, decorators=[],
            body_text=body, location=Location(file="t.py", line=1),
        )

    def test_not_check(self):
        pre = _extract_preconditions_from_code(self._make_func(
            "if not order_id:\n    raise ValueError('required')"
        ))
        assert len(pre) >= 1
        assert any("order_id" in p for p in pre)

    def test_none_check(self):
        pre = _extract_preconditions_from_code(self._make_func(
            "if amount is None:\n    return None"
        ))
        assert any("amount" in p and "None" in p for p in pre)

    def test_isinstance_assert(self):
        pre = _extract_preconditions_from_code(self._make_func(
            "assert isinstance(order_id, str)"
        ))
        assert any("order_id" in p and "str" in p for p in pre)

    def test_validation_call(self):
        pre = _extract_preconditions_from_code(self._make_func(
            "validate_order(order_id)"
        ))
        assert any("order" in p and "validation" in p.lower() for p in pre)

    def test_not_in_check(self):
        pre = _extract_preconditions_from_code(self._make_func(
            "if user_id not in active_users:\n    raise ValueError('invalid')"
        ))
        assert any("user_id" in p for p in pre)

    def test_limit_to_ten(self):
        body = "\n".join(f"if not var{i}: raise ValueError()" for i in range(20))
        pre = _extract_preconditions_from_code(self._make_func(body))
        assert len(pre) <= 10

    def test_empty_body(self):
        pre = _extract_preconditions_from_code(self._make_func(""))
        assert pre == []


# ---------------------------------------------------------------------------
# Tool extraction with new fields
# ---------------------------------------------------------------------------

class TestToolDefinitionNewFields:
    def test_tool_has_preconditions_field(self):
        path = os.path.join(FIXTURES, "python_agent", "tools", "refund.py")
        sym = parse_python_file(path)
        all_symbols = [sym]
        tools = extract_all_tools(all_symbols, "langchain")
        refund = next((t for t in tools if t.name == "process_refund"), None)
        assert refund is not None
        assert hasattr(refund, "preconditions")
        assert isinstance(refund.preconditions, list)
        assert len(refund.preconditions) > 0

    def test_tool_has_side_effects_field(self):
        path = os.path.join(FIXTURES, "python_agent", "tools", "refund.py")
        sym = parse_python_file(path)
        tools = extract_all_tools([sym], "langchain")
        refund = next((t for t in tools if t.name == "process_refund"), None)
        assert refund is not None
        assert hasattr(refund, "side_effects")
        assert isinstance(refund.side_effects, list)
        assert len(refund.side_effects) > 0

    def test_state_modifying_true_for_write_tool(self):
        path = os.path.join(FIXTURES, "python_agent", "tools", "refund.py")
        sym = parse_python_file(path)
        tools = extract_all_tools([sym], "langchain")
        refund = next((t for t in tools if t.name == "process_refund"), None)
        assert refund is not None
        assert refund.state_modifying is True

    def test_state_modifying_false_for_readonly_tool(self):
        path = os.path.join(FIXTURES, "python_agent", "tools", "search.py")
        sym = parse_python_file(path)
        tools = extract_all_tools([sym], "langchain")
        search = next((t for t in tools if t.name == "search_knowledge_base"), None)
        assert search is not None
        assert search.state_modifying is False


# ---------------------------------------------------------------------------
# Framework detection
# ---------------------------------------------------------------------------

class TestFrameworkDetection:
    def test_langchain_detected(self):
        paths = [
            os.path.join(FIXTURES, "python_agent", "main.py"),
            os.path.join(FIXTURES, "python_agent", "tools", "search.py"),
        ]
        from src.analysis.static_analyzer import analyze_files
        symbols = analyze_files(paths)
        fw, conf = detect_framework(symbols)
        assert fw == "langchain"
        assert conf > 0.0
