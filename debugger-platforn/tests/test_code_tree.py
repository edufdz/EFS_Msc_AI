"""Tests for the hierarchical code tree (src/graph/code_tree.py)."""

from __future__ import annotations

from src.analysis.static_analyzer import (
    ClassInfo,
    FileSymbols,
    FunctionInfo,
    Location,
    ParamInfo,
)
from src.graph.code_tree import build_code_tree

ROOT = "/repo"


def _fn(name, file, line, params=(), is_async=False, docstring=None):
    return FunctionInfo(
        name=name,
        params=[ParamInfo(name=p) for p in params],
        docstring=docstring,
        decorators=[],
        body_text="",
        location=Location(file=file, line=line),
        is_async=is_async,
    )


def _symbols():
    agent = FileSymbols(
        file_path=f"{ROOT}/agent.py",
        language="python",
        functions=[_fn("main", f"{ROOT}/agent.py", 40)],
        classes=[ClassInfo(
            name="Agent",
            bases=["BaseAgent"],
            docstring="The agent.",
            methods=[
                _fn("chat", f"{ROOT}/agent.py", 12, params=("message",), is_async=True),
                _fn("reset", f"{ROOT}/agent.py", 30),
            ],
            decorators=[],
            location=Location(file=f"{ROOT}/agent.py", line=10),
            class_variables=[],
        )],
    )
    booking = FileSymbols(
        file_path=f"{ROOT}/tools/booking.py",
        language="python",
        functions=[_fn("create_booking", f"{ROOT}/tools/booking.py", 5, params=("slot",))],
    )
    return [agent, booking]


def _tools():
    return [{
        "name": "create_booking",
        "risk_level": "high",
        "location": {"file": f"{ROOT}/tools/booking.py", "line": 6},
    }]


def _risks():
    return [{
        "severity": "high",
        "risk_type": "critical_action",
        "description": "Booking modifies state",
        "location": {"file": f"{ROOT}/tools/booking.py", "line": 5},
    }]


def _prompts():
    return [{
        "name": "system_prompt",
        "location": {"file": f"{ROOT}/prompts/system.txt"},
    }]


class TestCodeTree:
    def _build(self):
        return build_code_tree(
            all_symbols=_symbols(),
            tools=_tools(),
            prompts=_prompts(),
            risks=_risks(),
            entry_points=[f"{ROOT}/agent.py"],
            root_path=ROOT,
        )

    def test_totals(self):
        ct = self._build()
        assert ct["total_files"] == 3  # agent.py, tools/booking.py, prompts/system.txt
        assert ct["total_classes"] == 1
        assert ct["total_functions"] == 4  # chat, reset, main, create_booking

    def test_nested_structure(self):
        tree = self._build()["tree"]
        names = {c["name"]: c for c in tree["children"]}
        # Directories sorted before files
        assert [c["type"] for c in tree["children"]] == ["directory", "directory", "file"]
        assert set(names) == {"prompts", "tools", "agent.py"}

        agent = names["agent.py"]
        assert agent["is_entry_point"]
        cls = next(c for c in agent["children"] if c["type"] == "class")
        assert cls["name"] == "Agent" and cls["bases"] == ["BaseAgent"]
        methods = [m["name"] for m in cls["children"]]
        assert methods == ["chat", "reset"]  # ordered by line
        chat = cls["children"][0]
        assert chat["is_async"] and chat["params"] == ["message"]

    def test_tool_and_risk_annotation(self):
        tree = self._build()["tree"]
        tools_dir = next(c for c in tree["children"] if c["name"] == "tools")
        booking = tools_dir["children"][0]
        assert booking["tools"] == [{"name": "create_booking", "risk_level": "high"}]
        assert booking["max_risk_severity"] == "high"
        fn = next(c for c in booking["children"] if c["type"] == "function")
        assert fn["implements_tool"] == "create_booking"

    def test_directory_rollups(self):
        tree = self._build()["tree"]
        assert tree["counts"]["tools"] == 1
        assert tree["counts"]["risks"] == 1
        assert tree["max_risk_severity"] == "high"
        prompts_dir = next(c for c in tree["children"] if c["name"] == "prompts")
        assert prompts_dir["counts"] == {
            "files": 1, "classes": 0, "functions": 0,
            "tools": 0, "prompts": 1, "risks": 0,
        }

    def test_prompt_only_file_gets_node(self):
        tree = self._build()["tree"]
        prompts_dir = next(c for c in tree["children"] if c["name"] == "prompts")
        assert prompts_dir["children"][0]["name"] == "system.txt"
        assert prompts_dir["children"][0]["prompts"] == ["system_prompt"]

    def test_empty_inputs(self):
        ct = build_code_tree([], [], [], [], [], ROOT)
        assert ct["total_files"] == 0
        assert ct["tree"]["children"] == []

    def test_accepts_dataclass_tools(self):
        from src.patterns.detector import ToolDefinition

        tool = ToolDefinition(
            id="t", name="create_booking", description=None, parameters=[],
            source="custom_heuristic",
            location={"file": f"{ROOT}/tools/booking.py", "line": 6},
        )
        ct = build_code_tree(_symbols(), [tool], [], [], [], ROOT)
        tools_dir = next(c for c in ct["tree"]["children"] if c["name"] == "tools")
        assert tools_dir["children"][0]["tools"][0]["name"] == "create_booking"
