"""
Framework signature definitions for agent pattern detection.
Each framework has import patterns, decorators, class names, and function patterns
that help identify which agent framework a codebase uses.
"""

import re
import unicodedata


def _fold(s: str) -> str:
    """Lowercase and strip diacritics."""
    return "".join(
        c for c in unicodedata.normalize("NFD", s.lower())
        if unicodedata.category(c) != "Mn"
    )


def score_language(
    text: str,
    words: list[str],
    extra_chars: str | list[str] | None = None,
    fold_accents: bool = True,
) -> int:
    """Count indicator words and characters appearing in *text*.

    Word matching is anchored on word boundaries. Substring matching is not an
    option here: "con" occurs inside "conversation" and "los" inside
    "disclose", so an unanchored scorer reports English rule text as Spanish.

    ``fold_accents`` strips diacritics from both sides before matching, so
    "informacion" still scores against "información". Typed Spanish drops
    accents constantly; without folding, the word lists carry no weight on
    unaccented text and the verdict falls back to whatever ``extra_chars``
    contributes — which for unaccented text is nothing.

    ``extra_chars`` is always counted against the original text, so accented
    orthography remains available as a positive signal.

    This is the single language scorer for the project. Phase A previously had
    two — a bulk one over concatenated guardrail text and a per-rule one — and
    they disagreed, writing contradictory verdicts into the same agent map.
    """
    haystack = _fold(text) if fold_accents else text.lower()
    score = 0
    for word in words:
        needle = _fold(word) if fold_accents else word.lower()
        score += len(re.findall(r"\b" + re.escape(needle) + r"\b", haystack))
    for char in (extra_chars or []):
        score += text.count(char)
    return score


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
            "@langchain/core",
            "@langchain/openai",
            "@langchain/anthropic",
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
            # JS/TS. Without these a TypeScript LangGraph agent is invisible to
            # detection and loses to whichever provider SDK it happens to import.
            "@langchain/langgraph",
            "@langchain/langgraph-checkpoint",
        ],
        "decorators": [],
        # LangGraph apps import @langchain/core and a provider adapter too, so
        # on raw score they look like LangChain. LangGraph is the more specific
        # and more useful answer: it is what determines the architecture.
        "specialises": "langchain",
        "classes": ["StateGraph", "MessageGraph", "Graph"],
        "functions": [
            "add_node", "add_edge", "add_conditional_edges", "compile",
            "addNode", "addEdge", "addConditionalEdges",
        ],
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

# ── Language Detection Indicators ──

SPANISH_INDICATORS = [
    "bienvenido", "hola", "servicio", "cliente", "cita", "reserva",
    "consulta", "agente", "disponible", "horario", "gracias", "ayuda",
    "problema", "solución", "pedido", "factura", "devolución", "garantía",
    "reparación", "técnico", "soporte", "atención", "información",
    "confirmar", "cancelar", "modificar", "estado", "seguimiento", "envío", "pago",
]

ENGLISH_INDICATORS = [
    "welcome", "hello", "service", "customer", "appointment", "booking",
    "support", "help", "problem", "solution", "order", "invoice",
    "warranty", "repair", "information", "confirm", "cancel", "status",
    "shipping", "payment", "please", "thank", "sorry", "available",
]

PORTUGUESE_INDICATORS = [
    "obrigado", "bom dia", "serviço", "cliente", "atendimento",
    "consulta", "agendamento", "disponível", "horário", "ajuda",
    "problema", "solução", "pedido", "fatura", "devolução", "garantia",
]

PORTUGUESE_CHARS = ["ã", "õ"]  # chars distinctive to Portuguese (ç shared with others)

SPANISH_FORMALITY_USTED = ["usted", "estimado", "le informamos", "sírvase"]
SPANISH_FORMALITY_TU = ["tú", "te ", "quieres", "puedes"]

# ── Domain & Channel Detection Indicators ──

DOMAIN_INDICATORS = {
    "customer_support": ["support", "ticket", "complaint", "helpdesk", "soporte", "queja", "atención"],
    "sales": ["order", "purchase", "price", "product", "pedido", "compra", "precio"],
    "scheduling": ["appointment", "booking", "schedule", "calendar", "cita", "reserva", "agenda"],
}

INDUSTRY_INDICATORS = {
    "consumer_electronics": ["device", "phone", "laptop", "warranty", "dispositivo", "garantía", "tech_repair", "apple"],
    "healthcare": ["patient", "doctor", "appointment", "diagnosis", "paciente", "médico", "cita médica"],
    "finance": ["account", "balance", "transfer", "loan", "cuenta", "saldo", "préstamo"],
    "retail": ["cart", "checkout", "shipping", "return", "carrito", "envío", "devolución"],
}

CHANNEL_INDICATORS = {
    "whatsapp": ["whatsapp", "wa_", "wamid"],
    "web_chat": ["webchat", "livechat", "chat_widget"],
    "email": ["email", "inbox", "smtp"],
    "sms": ["sms", "twilio", "text_message"],
}

# ── OWASP / MITRE Taxonomy Constants ──

OWASP_LLM_2025 = {
    "LLM01": "Prompt Injection",
    "LLM02": "Sensitive Information Disclosure",
    "LLM03": "Supply Chain Vulnerabilities",
    "LLM04": "Data and Model Poisoning",
    "LLM05": "Improper Output Handling",
    "LLM06": "Excessive Agency",
    "LLM07": "System Prompt Leakage",
    "LLM08": "Vector and Embedding Weaknesses",
    "LLM09": "Misinformation",
    "LLM10": "Unbounded Consumption",
}

OWASP_AGENTIC_2026 = {
    "ASI01": "Agent Goal Hijack",
    "ASI02": "Tool Misuse and Exploitation",
    "ASI03": "Identity and Privilege Abuse",
    "ASI04": "Agentic Supply Chain Vulnerabilities",
    "ASI05": "Unexpected Code Execution",
    "ASI06": "Memory and Context Poisoning",
    "ASI07": "Insecure Inter-Agent Communication",
    "ASI08": "Cascading Failures",
    "ASI09": "Human-Agent Trust Exploitation",
    "ASI10": "Rogue Agents",
}

# Maps (risk_type, sub_type) → list of taxonomy IDs
RISK_TO_TAXONOMY = {
    # PII risks
    ("pii", "email"): ["LLM02", "ASI03"],
    ("pii", "phone"): ["LLM02", "ASI03"],
    ("pii", "ssn"): ["LLM02", "ASI03"],
    ("pii", "credit_card"): ["LLM02", "ASI03"],
    ("pii", "address"): ["LLM02", "ASI03"],
    # Critical action risks
    ("critical_action", "financial"): ["LLM06", "ASI02"],
    ("critical_action", "data_modification"): ["LLM06", "ASI02"],
    ("critical_action", "user_management"): ["LLM06", "ASI03"],
    ("critical_action", "communication"): ["LLM06", "ASI02"],
    # Code execution risks
    ("unsafe_operation", "eval"): ["ASI05", "LLM01"],
    ("unsafe_operation", "exec"): ["ASI05", "LLM01"],
    ("unsafe_operation", "subprocess"): ["ASI05"],
    # Excessive agency
    ("excessive_agency", "excessive_agency"): ["LLM06"],
}
