"""
Framework signature definitions for agent pattern detection.
Each framework has import patterns, decorators, class names, and function patterns
that help identify which agent framework a codebase uses.
"""

FRAMEWORK_SIGNATURES = {
    "langchain": {
        "imports": [
            "from langchain import",
            "from langchain.agents import",
            "from langchain.chains import",
            "from langchain.tools import",
            "from langchain_community import",
            "from langchain_core import",
            "from langchain_openai import",
            "from langchain_anthropic import",
        ],
        "decorators": ["tool", "chain"],
        "classes": [
            "BaseTool", "StructuredTool", "Tool",
            "BaseAgent", "AgentExecutor",
            "BaseChain", "LLMChain", "SequentialChain",
        ],
        "functions": [
            "initialize_agent", "create_react_agent",
            "create_openai_functions_agent", "create_tool_calling_agent",
        ],
    },

    "langgraph": {
        "imports": [
            "from langgraph.graph import",
            "from langgraph.prebuilt import",
            "from langgraph.checkpoint import",
        ],
        "decorators": [],
        "classes": ["StateGraph", "MessageGraph", "Graph"],
        "functions": ["add_node", "add_edge", "add_conditional_edges", "compile"],
    },

    "openai_native": {
        "imports": [
            "from openai import",
            "import openai",
        ],
        "decorators": [],
        "classes": ["OpenAI", "AsyncOpenAI"],
        "functions": ["chat.completions.create"],
        "config_keys": ["tools", "functions", "function_call"],
    },

    "anthropic_native": {
        "imports": [
            "from anthropic import",
            "import anthropic",
            "anthropic",  # matches TS/JS: @anthropic-ai/sdk, from 'anthropic', etc.
        ],
        "decorators": [],
        "classes": ["Anthropic", "AsyncAnthropic"],
        "functions": ["messages.create"],
        "config_keys": ["tools", "tool_choice"],
    },

    "crewai": {
        "imports": [
            "from crewai import",
        ],
        "decorators": ["task", "agent"],
        "classes": ["Agent", "Task", "Crew", "Process"],
        "functions": ["kickoff"],
    },

    "autogpt": {
        "imports": [
            "from autogpt import",
        ],
        "decorators": [],
        "classes": ["Agent", "AutoGPT"],
        "functions": [],
        "config_files": ["ai_settings.yaml"],
    },
}

# PII detection patterns
PII_PATTERNS = {
    "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    "phone": r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "credit_card": r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b",
    "address_keywords": [
        "address", "street", "city", "state", "zip", "postal",
    ],
}

# Critical action keywords for risk detection
CRITICAL_ACTION_KEYWORDS = {
    "financial": [
        "payment", "charge", "refund", "purchase", "transaction",
        "billing", "invoice", "transfer", "withdraw",
    ],
    "data_modification": [
        "delete", "remove", "update", "modify", "drop", "truncate",
    ],
    "user_management": [
        "create_user", "delete_user", "change_password",
        "grant_access", "revoke_access",
    ],
    "communication": [
        "send_email", "send_sms", "notify", "alert", "post_message",
    ],
}
