"""
Sprint T — T.2.4 Risk Analyzer Tests
Validates Sprint 3 (OWASP/MITRE taxonomy mapping) implementation.
"""

import pytest

from src.risk.analyzer import (
    RiskFlag,
    analyze_risks,
    detect_critical_actions,
    detect_excessive_agency,
    detect_pii_in_tools,
    detect_unsafe_operations,
)
from src.patterns.detector import ToolDefinition, PromptDefinition


def _make_tool(
    name: str = "test_tool",
    description: str = "",
    parameters: list | None = None,
    code_snippet: str = "",
    risk_level: str = "low",
    location: dict | None = None,
) -> ToolDefinition:
    return ToolDefinition(
        id=name.lower().replace(" ", "_"),
        name=name,
        description=description,
        parameters=parameters or [],
        source="test",
        location=location or {"file": "test.py", "line": 1},
        confidence=0.9,
        risk_level=risk_level,
        sandbox_safe=True,
        code_snippet=code_snippet,
    )


def _make_prompt(
    name: str = "system_prompt",
    content: str = "",
    prompt_type: str = "system",
) -> PromptDefinition:
    return PromptDefinition(
        name=name,
        type=prompt_type,
        content=content,
        variables=[],
        location={"file": "prompts.py", "line": 1},
    )


# ── T.2.4: PII regex detection ──

class TestPIIDetection:
    def test_email_in_tool_description(self):
        """PII regex: email pattern in tool description -> RiskFlag(pii_type='email')"""
        tool = _make_tool(
            name="send_email",
            description="Sends email to user@example.com",
            code_snippet="send(user@example.com)",
        )
        risks = detect_pii_in_tools([tool])
        email_risks = [r for r in risks if r.pii_type == "email"]
        assert len(email_risks) >= 1
        assert email_risks[0].risk_type == "pii"

    def test_email_in_param_name(self):
        """PII via parameter name containing 'email'."""
        tool = _make_tool(
            name="notify_user",
            parameters=[{"name": "user_email", "type": "str"}],
        )
        risks = detect_pii_in_tools([tool])
        email_risks = [r for r in risks if r.pii_type == "email"]
        assert len(email_risks) >= 1

    def test_phone_in_param_name(self):
        tool = _make_tool(
            name="call_user",
            parameters=[{"name": "phone_number", "type": "str"}],
        )
        risks = detect_pii_in_tools([tool])
        phone_risks = [r for r in risks if r.pii_type == "phone"]
        assert len(phone_risks) >= 1

    def test_address_keyword_in_param(self):
        tool = _make_tool(
            name="ship_order",
            parameters=[{"name": "shipping_address", "type": "str"}],
        )
        risks = detect_pii_in_tools([tool])
        addr_risks = [r for r in risks if r.pii_type == "address"]
        assert len(addr_risks) >= 1


# ── T.2.4: Critical action detection ──

class TestCriticalActionDetection:
    def test_payment_in_tool_name(self):
        """Critical action: 'payment' in tool name -> RiskFlag(severity='critical')"""
        tool = _make_tool(name="process_payment", description="Charges user card")
        risks = detect_critical_actions([tool])
        assert len(risks) >= 1
        assert risks[0].severity == "critical"
        assert risks[0].risk_type == "critical_action"

    def test_refund_in_tool_code(self):
        tool = _make_tool(name="handle_return", code_snippet="issue_refund(order)")
        risks = detect_critical_actions([tool])
        assert len(risks) >= 1

    def test_delete_in_tool_name(self):
        tool = _make_tool(name="delete_record", description="Removes a DB record")
        risks = detect_critical_actions([tool])
        assert len(risks) >= 1
        assert risks[0].severity == "high"


# ── T.2.4: Taxonomy mapping (Sprint 3) ──

class TestTaxonomyMapping:
    def test_pii_risk_maps_to_llm02_asi03(self):
        """PII risk -> taxonomy_ids=['LLM02', 'ASI03']"""
        tool = _make_tool(
            name="get_user",
            parameters=[{"name": "user_email", "type": "str"}],
        )
        risks, _ = analyze_risks([tool], [])
        pii_risks = [r for r in risks if r.risk_type == "pii" and r.pii_type == "email"]
        assert len(pii_risks) >= 1
        assert "LLM02" in pii_risks[0].taxonomy_ids
        assert "ASI03" in pii_risks[0].taxonomy_ids
        assert "Sensitive Information Disclosure" in pii_risks[0].taxonomy_names

    def test_critical_action_maps_to_llm06_asi02(self):
        """Financial critical action -> taxonomy_ids=['LLM06', 'ASI02']"""
        tool = _make_tool(name="process_payment")
        risks, _ = analyze_risks([tool], [])
        crit_risks = [r for r in risks if r.risk_type == "critical_action"]
        assert len(crit_risks) >= 1
        assert "LLM06" in crit_risks[0].taxonomy_ids
        assert "ASI02" in crit_risks[0].taxonomy_ids
        assert "Excessive Agency" in crit_risks[0].taxonomy_names

    def test_user_management_maps_to_asi03(self):
        """User management critical action -> taxonomy includes ASI03"""
        tool = _make_tool(name="create_user", description="Creates a new user account")
        risks, _ = analyze_risks([tool], [])
        crit_risks = [r for r in risks if r.risk_type == "critical_action"]
        assert len(crit_risks) >= 1
        assert "ASI03" in crit_risks[0].taxonomy_ids

    def test_address_pii_maps_to_taxonomy(self):
        tool = _make_tool(
            name="ship_order",
            parameters=[{"name": "address", "type": "str"}],
        )
        risks, _ = analyze_risks([tool], [])
        addr_risks = [r for r in risks if r.pii_type == "address"]
        assert len(addr_risks) >= 1
        assert "LLM02" in addr_risks[0].taxonomy_ids

    def test_taxonomy_names_populated(self):
        """taxonomy_names should contain human-readable names for each taxonomy_id."""
        tool = _make_tool(
            name="send_email",
            parameters=[{"name": "user_email", "type": "str"}],
        )
        risks, _ = analyze_risks([tool], [])
        pii_risks = [r for r in risks if r.pii_type == "email"]
        assert len(pii_risks) >= 1
        assert len(pii_risks[0].taxonomy_names) == len(pii_risks[0].taxonomy_ids)
        for name in pii_risks[0].taxonomy_names:
            assert isinstance(name, str)
            assert len(name) > 0


# ── T.2.4: Unsafe operations (Sprint 3) ──

class TestUnsafeOperations:
    def test_eval_detected(self):
        """eval( in code -> taxonomy_ids=['ASI05', 'LLM01']"""
        tool = _make_tool(
            name="dynamic_exec",
            code_snippet="result = eval(user_input)",
        )
        risks = detect_unsafe_operations([tool])
        assert len(risks) == 1
        assert risks[0].severity == "critical"
        assert risks[0].risk_type == "unsafe_operation"

    def test_eval_taxonomy_via_analyze(self):
        """Full pipeline: eval -> ASI05 + LLM01 taxonomy IDs."""
        tool = _make_tool(
            name="run_code",
            code_snippet="eval(expression)",
        )
        risks, _ = analyze_risks([tool], [])
        unsafe = [r for r in risks if r.risk_type == "unsafe_operation"]
        assert len(unsafe) >= 1
        assert "ASI05" in unsafe[0].taxonomy_ids
        assert "LLM01" in unsafe[0].taxonomy_ids
        assert "Unexpected Code Execution" in unsafe[0].taxonomy_names

    def test_exec_detected(self):
        tool = _make_tool(name="executor", code_snippet="exec(code_str)")
        risks = detect_unsafe_operations([tool])
        assert len(risks) == 1

    def test_subprocess_detected(self):
        tool = _make_tool(name="shell_runner", code_snippet="subprocess.run(cmd)")
        risks = detect_unsafe_operations([tool])
        assert len(risks) == 1

    def test_os_system_detected(self):
        tool = _make_tool(name="sys_call", code_snippet="os.system('ls')")
        risks = detect_unsafe_operations([tool])
        assert len(risks) == 1

    def test_safe_tool_no_unsafe_risk(self):
        tool = _make_tool(name="search", code_snippet="return db.query(term)")
        risks = detect_unsafe_operations([tool])
        assert len(risks) == 0


# ── T.2.4: Excessive agency (Sprint 3) ──

class TestExcessiveAgency:
    def test_high_risk_tool_no_confirmation(self):
        """High-risk tool without confirmation gate -> taxonomy_ids=['LLM06']"""
        tool = _make_tool(
            name="delete_all",
            risk_level="high",
            code_snippet="db.delete_all()",
        )
        risks = detect_excessive_agency([tool], [])
        assert len(risks) >= 1
        assert risks[0].risk_type == "excessive_agency"
        assert risks[0].severity == "high"

    def test_high_risk_tool_with_confirmation_ok(self):
        """High-risk tool WITH confirmation gate -> no excessive agency risk."""
        tool = _make_tool(
            name="delete_all",
            risk_level="high",
            code_snippet="if confirm(action): db.delete_all()",
        )
        risks = detect_excessive_agency([tool], [])
        tool_risks = [r for r in risks if r.tool == "delete_all"]
        assert len(tool_risks) == 0

    def test_many_tools_no_scoping(self):
        """15 tools with no permission scoping in prompts -> excessive agency flagged."""
        tools = [_make_tool(name=f"tool_{i}") for i in range(15)]
        prompts = [_make_prompt(content="You are a helpful assistant.")]
        risks = detect_excessive_agency(tools, prompts)
        scope_risks = [r for r in risks if r.tool is None]
        assert len(scope_risks) >= 1
        assert "15 tools" in scope_risks[0].description

    def test_many_tools_with_scoping_ok(self):
        """15 tools WITH permission scoping -> no excessive agency for count."""
        tools = [_make_tool(name=f"tool_{i}") for i in range(15)]
        prompts = [_make_prompt(content="You are restricted to only use tools the user has authorized.")]
        risks = detect_excessive_agency(tools, prompts)
        scope_risks = [r for r in risks if r.tool is None]
        assert len(scope_risks) == 0

    def test_excessive_agency_taxonomy_via_analyze(self):
        """Full pipeline: excessive agency -> LLM06 taxonomy."""
        tool = _make_tool(name="danger", risk_level="high", code_snippet="do_thing()")
        risks, _ = analyze_risks([tool], [])
        ea_risks = [r for r in risks if r.risk_type == "excessive_agency"]
        assert len(ea_risks) >= 1
        assert "LLM06" in ea_risks[0].taxonomy_ids
        assert "Excessive Agency" in ea_risks[0].taxonomy_names


# ── T.2.4: Deduplication ──

class TestDeduplication:
    def test_same_tool_risk_type_pii_type_deduped(self):
        """Same tool + risk_type + pii_type -> single RiskFlag."""
        tool = _make_tool(
            name="send_email",
            parameters=[{"name": "email", "type": "str"}],
            description="Sends to user@example.com",
            code_snippet="send(user@test.com)",
        )
        risks, _ = analyze_risks([tool], [])
        email_risks = [r for r in risks if r.pii_type == "email" and r.tool == "send_email"]
        assert len(email_risks) == 1, f"Expected 1 deduplicated email risk, got {len(email_risks)}"

    def test_different_pii_types_not_deduped(self):
        """Different pii_types on same tool -> separate RiskFlags."""
        tool = _make_tool(
            name="user_form",
            parameters=[
                {"name": "email", "type": "str"},
                {"name": "phone", "type": "str"},
            ],
        )
        risks, _ = analyze_risks([tool], [])
        pii_risks = [r for r in risks if r.risk_type == "pii" and r.tool == "user_form"]
        pii_types = {r.pii_type for r in pii_risks}
        assert len(pii_types) >= 2


# ── T.2.4: RiskFlag dataclass shape ──

class TestRiskFlagShape:
    def test_new_fields_exist(self):
        """RiskFlag has taxonomy_ids and taxonomy_names fields."""
        r = RiskFlag(
            location={}, tool="t", risk_type="pii", pii_type="email",
            severity="high", description="test",
        )
        assert r.taxonomy_ids == []
        assert r.taxonomy_names == []

    def test_new_fields_serializable(self):
        """taxonomy fields are plain lists (JSON-serializable)."""
        from dataclasses import asdict
        r = RiskFlag(
            location={}, tool="t", risk_type="pii", pii_type="email",
            severity="high", description="test",
            taxonomy_ids=["LLM02"], taxonomy_names=["Sensitive Information Disclosure"],
        )
        d = asdict(r)
        assert d["taxonomy_ids"] == ["LLM02"]
        assert d["taxonomy_names"] == ["Sensitive Information Disclosure"]
