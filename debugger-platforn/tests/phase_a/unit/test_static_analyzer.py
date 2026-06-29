"""Unit tests for static_analyzer.py — Sprint 1 (tree-sitter TS/JS) enhancements."""

import os
import tempfile

import pytest

from src.analysis.static_analyzer import (
    parse_python_file,
    parse_typescript_file,
    parse_typescript_file_treesitter,
    parse_typescript_file_regex,
    analyze_files,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")


# ---------------------------------------------------------------------------
# Python parser (baseline — should still work)
# ---------------------------------------------------------------------------

class TestPythonParser:
    def test_extracts_functions(self):
        path = os.path.join(FIXTURES, "python_agent", "tools", "search.py")
        sym = parse_python_file(path)
        names = [f.name for f in sym.functions]
        assert "search_knowledge_base" in names

    def test_extracts_decorators(self):
        path = os.path.join(FIXTURES, "python_agent", "tools", "search.py")
        sym = parse_python_file(path)
        func = next(f for f in sym.functions if f.name == "search_knowledge_base")
        assert "tool" in func.decorators

    def test_extracts_params_with_types(self):
        path = os.path.join(FIXTURES, "python_agent", "tools", "refund.py")
        sym = parse_python_file(path)
        func = next(f for f in sym.functions if f.name == "process_refund")
        param_names = [p.name for p in func.params]
        assert "order_id" in param_names
        assert "amount" in param_names
        order_id_p = next(p for p in func.params if p.name == "order_id")
        assert order_id_p.type_annotation == "str"

    def test_extracts_docstring(self):
        path = os.path.join(FIXTURES, "python_agent", "tools", "refund.py")
        sym = parse_python_file(path)
        func = next(f for f in sym.functions if f.name == "process_refund")
        assert func.docstring is not None
        assert "refund" in func.docstring.lower()

    def test_extracts_function_calls(self):
        path = os.path.join(FIXTURES, "python_agent", "tools", "refund.py")
        sym = parse_python_file(path)
        func = next(f for f in sym.functions if f.name == "process_refund")
        assert len(func.calls) > 0

    def test_extracts_imports(self):
        path = os.path.join(FIXTURES, "python_agent", "tools", "search.py")
        sym = parse_python_file(path)
        modules = [i.module for i in sym.imports]
        assert "requests" in modules


# ---------------------------------------------------------------------------
# TS/JS tree-sitter parser (Sprint 1)
# ---------------------------------------------------------------------------

class TestTypeScriptTreeSitterParser:
    def test_extracts_functions_from_ts(self):
        path = os.path.join(FIXTURES, "typescript_agent", "tools", "booking.ts")
        sym = parse_typescript_file_treesitter(path)
        names = [f.name for f in sym.functions]
        assert "bookAppointment" in names

    def test_extracts_parameter_types(self):
        """Regression test: regex parser could NOT extract parameter types."""
        path = os.path.join(FIXTURES, "typescript_agent", "tools", "booking.ts")
        sym = parse_typescript_file_treesitter(path)
        func = next(f for f in sym.functions if f.name == "bookAppointment")
        param_names = [p.name for p in func.params]
        assert "date" in param_names
        assert "customerName" in param_names
        date_p = next(p for p in func.params if p.name == "date")
        assert date_p.type_annotation == "string"

    def test_extracts_default_values(self):
        path = os.path.join(FIXTURES, "typescript_agent", "tools", "booking.ts")
        sym = parse_typescript_file_treesitter(path)
        func = next(f for f in sym.functions if f.name == "bookAppointment")
        notes_p = next(p for p in func.params if p.name == "notes")
        assert notes_p.default == '""'

    def test_extracts_jsdoc(self):
        """Regression test: regex parser could NOT extract JSDoc."""
        path = os.path.join(FIXTURES, "typescript_agent", "tools", "booking.ts")
        sym = parse_typescript_file_treesitter(path)
        func = next(f for f in sym.functions if f.name == "bookAppointment")
        assert func.docstring is not None
        assert "appointment" in func.docstring.lower()

    def test_extracts_function_calls(self):
        """Regression test: regex parser returned empty calls list."""
        path = os.path.join(FIXTURES, "typescript_agent", "tools", "booking.ts")
        sym = parse_typescript_file_treesitter(path)
        func = next(f for f in sym.functions if f.name == "bookAppointment")
        assert len(func.calls) > 0
        call_names = func.calls
        assert any("db.execute" in c for c in call_names)

    def test_extracts_imports(self):
        path = os.path.join(FIXTURES, "typescript_agent", "index.ts")
        sym = parse_typescript_file_treesitter(path)
        modules = [i.module for i in sym.imports]
        assert "openai" in modules

    def test_extracts_import_names(self):
        """Regression test: regex parser extracted NO import names."""
        path = os.path.join(FIXTURES, "typescript_agent", "index.ts")
        sym = parse_typescript_file_treesitter(path)
        openai_imp = next(i for i in sym.imports if i.module == "openai")
        assert "OpenAI" in openai_imp.names

    def test_extracts_tool_array_variable(self):
        path = os.path.join(FIXTURES, "typescript_agent", "index.ts")
        sym = parse_typescript_file_treesitter(path)
        var_names = [v.name for v in sym.variables]
        assert "tools" in var_names
        tools_var = next(v for v in sym.variables if v.name == "tools")
        assert tools_var.value_text is not None
        assert "book_appointment" in tools_var.value_text

    def test_extracts_interfaces(self):
        path = os.path.join(FIXTURES, "typescript_agent", "tools", "booking.ts")
        sym = parse_typescript_file_treesitter(path)
        var_names = [v.name for v in sym.variables]
        assert "AppointmentResult" in var_names

    def test_async_flag(self):
        path = os.path.join(FIXTURES, "typescript_agent", "tools", "booking.ts")
        sym = parse_typescript_file_treesitter(path)
        func = next(f for f in sym.functions if f.name == "bookAppointment")
        assert func.is_async is True

    def test_language_set_correctly(self):
        ts_sym = parse_typescript_file_treesitter(
            os.path.join(FIXTURES, "typescript_agent", "tools", "booking.ts")
        )
        assert ts_sym.language == "typescript"


class TestTypeScriptFallback:
    def test_regex_fallback_runs(self):
        """If tree-sitter fails, regex parser still produces output."""
        path = os.path.join(FIXTURES, "typescript_agent", "tools", "booking.ts")
        sym = parse_typescript_file_regex(path)
        # Regex parser finds functions (though with less detail)
        assert len(sym.functions) >= 1

    def test_parse_typescript_file_uses_treesitter(self):
        """The main entrypoint should use tree-sitter by default."""
        path = os.path.join(FIXTURES, "typescript_agent", "tools", "booking.ts")
        sym = parse_typescript_file(path)
        # Tree-sitter extracts params; regex doesn't
        func = next(f for f in sym.functions if f.name == "bookAppointment")
        assert len(func.params) > 0, "Should use tree-sitter (not regex) — params are extracted"


class TestAnalyzeFiles:
    def test_routes_python_and_typescript(self):
        paths = [
            os.path.join(FIXTURES, "python_agent", "tools", "search.py"),
            os.path.join(FIXTURES, "typescript_agent", "tools", "booking.ts"),
        ]
        results = analyze_files(paths)
        assert len(results) == 2
        langs = {r.language for r in results}
        assert "python" in langs
        assert "typescript" in langs


class TestEdgeCases:
    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(suffix=".ts", mode="w", delete=False) as f:
            f.write("")
            path = f.name
        try:
            sym = parse_typescript_file(path)
            assert sym.parse_errors == []
            assert sym.functions == []
        finally:
            os.unlink(path)

    def test_syntax_error_file(self):
        with tempfile.NamedTemporaryFile(suffix=".ts", mode="w", delete=False) as f:
            f.write("function { broken syntax ??? }")
            path = f.name
        try:
            sym = parse_typescript_file(path)
            # Should not crash
            assert isinstance(sym.functions, list)
        finally:
            os.unlink(path)

    def test_nonexistent_file(self):
        sym = parse_typescript_file("/nonexistent/file.ts")
        assert len(sym.parse_errors) > 0
