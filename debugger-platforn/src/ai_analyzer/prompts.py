"""
Prompt templates for AI-powered semantic analysis.
"""

GOAL_UNDERSTANDING_PROMPT = """\
You are analyzing an agent codebase to understand its purpose and behavior.

Based on the following code artifacts, determine:
1. What is the agent's primary job/purpose?
2. What domain does it operate in? (support, sales, scheduling, research, ops, etc.)
3. What are the agent's main capabilities?
4. What are likely success criteria for this agent?

Code artifacts:
{context}

Respond with ONLY valid JSON (no markdown fences):
{{
  "purpose": "brief description of what the agent does",
  "domain": "support|sales|scheduling|ops|research|coding|data|custom",
  "capabilities": ["capability 1", "capability 2"],
  "success_criteria": ["criterion 1", "criterion 2"],
  "confidence": 0.8
}}
"""

TOOL_ANALYSIS_PROMPT = """\
You are analyzing tool definitions from an agent codebase.

For each tool below, determine:
1. What does this tool actually do?
2. What are its required inputs (human-readable)?
3. What does it return/produce?
4. Is this tool read-only or does it modify state?
5. Does it handle sensitive data (PII, financial, etc.)?
6. What other tools does it logically depend on?
7. What is its risk level?

Tools:
{tools}

Codebase context:
{codebase_context}

Respond with ONLY valid JSON (no markdown fences):
{{
  "tools": [
    {{
      "name": "tool_name",
      "purpose": "what it does in plain english",
      "required_inputs": ["input1", "input2"],
      "output": "what it returns",
      "read_only": true,
      "handles_sensitive_data": false,
      "sensitive_data_types": [],
      "dependencies": ["other_tool_name"],
      "risk_level": "low"
    }}
  ]
}}
"""

WORKFLOW_ANALYSIS_PROMPT = """\
You are analyzing agent code to understand its conversation flow and decision-making.

Based on the main loop code, tool definitions, and prompts, determine:
1. How does the agent decide which tool to call?
2. What is the typical conversation flow?
3. What error handling strategies are in place?
4. Are there any safety guardrails or validation checks?
5. How does the agent handle ambiguous user requests?

Agent main entry point code:
{entry_point_code}

Available tools:
{tool_names}

System prompts:
{prompts}

Framework: {framework}

Respond with ONLY valid JSON (no markdown fences):
{{
  "decision_strategy": "react|plan-and-execute|function-calling|state-machine|custom",
  "typical_flow": ["step 1", "step 2"],
  "error_handling": {{
    "timeout": "strategy or none",
    "malformed_response": "strategy or none",
    "tool_failure": "strategy or none"
  }},
  "guardrails": ["guardrail 1"],
  "ambiguity_handling": "how agent handles unclear requests"
}}
"""

DEPENDENCY_ANALYSIS_PROMPT = """\
You are analyzing tool dependencies in an agent system.

Given these tools and their implementations, determine:
1. Which tools must be called before other tools?
2. Which tools are mutually exclusive?
3. Which tool combinations are common/expected?
4. Are there any circular dependency risks?

Tools with code:
{tools_with_code}

Respond with ONLY valid JSON (no markdown fences):
{{
  "dependencies": [
    {{
      "tool": "tool_name",
      "requires": ["required_tool"],
      "reason": "why this dependency exists"
    }}
  ],
  "mutually_exclusive": [],
  "common_sequences": [
    ["tool_1", "tool_2"]
  ],
  "circular_dependency_risks": []
}}
"""
