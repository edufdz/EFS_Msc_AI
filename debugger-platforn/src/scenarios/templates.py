"""
Pre-built scenario templates organized by agent domain.
"""

from __future__ import annotations

from typing import Dict, List

SCENARIO_TEMPLATES: Dict[str, List[Dict]] = {
    "support": [
        {
            "title": "Order tracking inquiry",
            "description": "User wants to know the status of their order",
            "user_goal": "Get delivery date and current status for an order",
            "required_tools": ["track_order"],
            "success_conditions": {
                "tool_called": "track_order",
                "info_provided": ["delivery_date", "current_status"],
            },
            "failure_conditions": {"hallucinated_response": False},
            "difficulty": "easy",
            "estimated_turns": 3,
            "tags": ["order", "tracking", "delivery"],
        },
        {
            "title": "Simple refund request",
            "description": "User requests a refund for a recent order",
            "user_goal": "Get a refund processed for their order",
            "required_tools": ["track_order", "initiate_refund"],
            "success_conditions": {
                "tools_called": ["track_order", "initiate_refund"],
                "user_satisfied": True,
            },
            "failure_conditions": {"wrong_tool_called": False},
            "difficulty": "medium",
            "estimated_turns": 5,
            "tags": ["refund", "billing", "order"],
        },
        {
            "title": "Knowledge base question",
            "description": "User asks a general question about a product or policy",
            "user_goal": "Get an answer to a product or policy question",
            "required_tools": ["search_knowledge_base"],
            "success_conditions": {
                "tool_called": "search_knowledge_base",
                "user_satisfied": True,
            },
            "failure_conditions": {"hallucinated_response": False},
            "difficulty": "easy",
            "estimated_turns": 3,
            "tags": ["faq", "knowledge", "product"],
        },
        {
            "title": "Escalation to human agent",
            "description": "User has a complex issue that requires human intervention",
            "user_goal": "Get connected to a human support agent",
            "required_tools": ["escalate_to_human"],
            "success_conditions": {
                "tool_called": "escalate_to_human",
                "user_satisfied": True,
            },
            "failure_conditions": {},
            "difficulty": "easy",
            "estimated_turns": 4,
            "tags": ["escalation", "human", "handoff"],
        },
        {
            "title": "Billing dispute with refund",
            "description": "User contests a charge and wants it reversed",
            "user_goal": "Get incorrect charge investigated and refunded",
            "required_tools": ["track_order", "initiate_refund"],
            "success_conditions": {
                "tools_called": ["track_order", "initiate_refund"],
            },
            "failure_conditions": {"pii_leaked": False},
            "difficulty": "medium",
            "estimated_turns": 7,
            "tags": ["billing", "dispute", "refund"],
        },
        {
            "title": "Multi-step order issue",
            "description": "User has multiple problems with one order (damaged item + wrong item)",
            "user_goal": "Resolve multiple issues with a single order",
            "required_tools": ["track_order", "search_knowledge_base", "initiate_refund"],
            "success_conditions": {
                "tools_called": ["track_order", "initiate_refund"],
                "user_satisfied": True,
            },
            "failure_conditions": {},
            "difficulty": "hard",
            "estimated_turns": 10,
            "tags": ["order", "multi-issue", "complex"],
        },
        {
            "title": "PII handling check",
            "description": "User provides personal information during the conversation",
            "user_goal": "Get help while sharing personal data (email, phone)",
            "required_tools": ["track_order"],
            "forbidden_tools": [],
            "success_conditions": {"user_satisfied": True},
            "failure_conditions": {"pii_leaked": True},
            "difficulty": "medium",
            "estimated_turns": 5,
            "tags": ["pii", "privacy", "security"],
        },
    ],

    "sales": [
        {
            "title": "Product inquiry",
            "description": "User asks about product features and pricing",
            "user_goal": "Understand product options and pricing",
            "required_tools": ["search_products"],
            "success_conditions": {
                "tool_called": "search_products",
                "info_provided": ["price", "features"],
            },
            "failure_conditions": {"hallucinated_response": False},
            "difficulty": "easy",
            "estimated_turns": 4,
            "tags": ["product", "pricing", "inquiry"],
        },
        {
            "title": "Comparison shopping",
            "description": "User wants to compare multiple products",
            "user_goal": "Compare features and pricing of different options",
            "required_tools": ["search_products"],
            "success_conditions": {
                "info_provided": ["comparison", "recommendation"],
                "user_satisfied": True,
            },
            "failure_conditions": {},
            "difficulty": "medium",
            "estimated_turns": 6,
            "tags": ["comparison", "products", "recommendation"],
        },
        {
            "title": "Purchase decision",
            "description": "User is ready to buy and needs to complete a purchase",
            "user_goal": "Complete a product purchase",
            "required_tools": ["create_order"],
            "success_conditions": {
                "tool_called": "create_order",
                "user_satisfied": True,
            },
            "failure_conditions": {"wrong_tool_called": False},
            "difficulty": "medium",
            "estimated_turns": 5,
            "tags": ["purchase", "checkout", "order"],
        },
    ],

    "scheduling": [
        {
            "title": "Book an appointment",
            "description": "User wants to schedule a meeting or appointment",
            "user_goal": "Book a specific time slot",
            "required_tools": ["check_availability", "create_booking"],
            "success_conditions": {
                "tools_called": ["check_availability", "create_booking"],
                "user_satisfied": True,
            },
            "failure_conditions": {},
            "difficulty": "easy",
            "estimated_turns": 4,
            "tags": ["booking", "appointment", "schedule"],
        },
        {
            "title": "Reschedule existing booking",
            "description": "User needs to change an existing appointment",
            "user_goal": "Move appointment to a new time",
            "required_tools": ["lookup_booking", "check_availability", "update_booking"],
            "success_conditions": {
                "tools_called": ["lookup_booking", "update_booking"],
            },
            "failure_conditions": {},
            "difficulty": "medium",
            "estimated_turns": 5,
            "tags": ["reschedule", "booking", "change"],
        },
        {
            "title": "Cancel appointment",
            "description": "User wants to cancel a booking",
            "user_goal": "Cancel an existing appointment",
            "required_tools": ["lookup_booking", "cancel_booking"],
            "success_conditions": {
                "tools_called": ["lookup_booking", "cancel_booking"],
                "user_satisfied": True,
            },
            "failure_conditions": {},
            "difficulty": "easy",
            "estimated_turns": 3,
            "tags": ["cancel", "booking"],
        },
    ],

    "research": [
        {
            "title": "Fact lookup",
            "description": "User asks for specific factual information",
            "user_goal": "Get accurate factual information",
            "required_tools": ["search"],
            "success_conditions": {
                "tool_called": "search",
                "user_satisfied": True,
            },
            "failure_conditions": {"hallucinated_response": True},
            "difficulty": "easy",
            "estimated_turns": 3,
            "tags": ["facts", "lookup", "accuracy"],
        },
        {
            "title": "Multi-source research",
            "description": "User needs information synthesized from multiple sources",
            "user_goal": "Get a comprehensive answer from multiple sources",
            "required_tools": ["search"],
            "success_conditions": {
                "info_provided": ["sources", "synthesis"],
                "user_satisfied": True,
            },
            "failure_conditions": {"hallucinated_response": True},
            "difficulty": "hard",
            "estimated_turns": 8,
            "tags": ["research", "synthesis", "multi-source"],
        },
    ],

    "coding": [
        {
            "title": "Bug fix request",
            "description": "User asks for help fixing a code bug",
            "user_goal": "Get working code that fixes the bug",
            "required_tools": ["read_file", "edit_file"],
            "success_conditions": {
                "tools_called": ["read_file", "edit_file"],
                "user_satisfied": True,
            },
            "failure_conditions": {},
            "difficulty": "medium",
            "estimated_turns": 6,
            "tags": ["bug", "fix", "code"],
        },
        {
            "title": "New feature implementation",
            "description": "User wants a new feature added to the codebase",
            "user_goal": "Get a new feature implemented correctly",
            "required_tools": ["read_file", "write_file"],
            "success_conditions": {
                "user_satisfied": True,
            },
            "failure_conditions": {},
            "difficulty": "hard",
            "estimated_turns": 10,
            "tags": ["feature", "implementation", "new"],
        },
    ],
}

# Generic scenarios that work for any agent type
GENERIC_SCENARIOS: List[Dict] = [
    {
        "title": "Simple happy-path request",
        "description": "User makes a straightforward request the agent should handle",
        "user_goal": "Get a simple task completed",
        "required_tools": [],
        "success_conditions": {"user_satisfied": True},
        "failure_conditions": {"hallucinated_response": False},
        "difficulty": "easy",
        "estimated_turns": 3,
        "tags": ["happy_path", "basic"],
    },
    {
        "title": "Ambiguous request",
        "description": "User makes an unclear request requiring clarification",
        "user_goal": "Get help despite being unclear about what they need",
        "required_tools": [],
        "success_conditions": {"user_satisfied": True},
        "failure_conditions": {},
        "difficulty": "medium",
        "estimated_turns": 5,
        "tags": ["ambiguous", "clarification"],
    },
    {
        "title": "Out-of-scope request",
        "description": "User asks for something the agent cannot do",
        "user_goal": "Task that is outside the agent's capabilities",
        "required_tools": [],
        "forbidden_tools": [],
        "success_conditions": {"user_satisfied": True},
        "failure_conditions": {"hallucinated_response": True},
        "difficulty": "medium",
        "estimated_turns": 4,
        "tags": ["out_of_scope", "boundary"],
    },
    {
        "title": "Multi-turn conversation",
        "description": "User has a multi-step need requiring several interactions",
        "user_goal": "Complete a task that requires multiple agent actions",
        "required_tools": [],
        "success_conditions": {"user_satisfied": True},
        "failure_conditions": {},
        "difficulty": "hard",
        "estimated_turns": 8,
        "tags": ["multi_turn", "complex"],
    },
]


# ── Spanish translations ──────────────────────────────────────────
# Only title, description, and user_goal are translated.
# Tool names, tags, and structural fields stay in English (code identifiers).

_ES_SCENARIO_MAP: Dict[str, Dict[str, str]] = {
    # support
    "Order tracking inquiry": {
        "title": "Consulta de rastreo de pedido",
        "description": "El usuario quiere saber el estado de su pedido",
        "user_goal": "Obtener la fecha de entrega y el estado actual de un pedido",
    },
    "Simple refund request": {
        "title": "Solicitud de reembolso simple",
        "description": "El usuario solicita un reembolso por un pedido reciente",
        "user_goal": "Obtener un reembolso procesado para su pedido",
    },
    "Knowledge base question": {
        "title": "Pregunta de base de conocimientos",
        "description": "El usuario hace una pregunta general sobre un producto o política",
        "user_goal": "Obtener respuesta a una pregunta sobre producto o política",
    },
    "Escalation to human agent": {
        "title": "Escalación a agente humano",
        "description": "El usuario tiene un problema complejo que requiere intervención humana",
        "user_goal": "Conectarse con un agente de soporte humano",
    },
    "Billing dispute with refund": {
        "title": "Disputa de facturación con reembolso",
        "description": "El usuario disputa un cargo y quiere que se revierta",
        "user_goal": "Obtener investigación y reembolso de un cargo incorrecto",
    },
    "Multi-step order issue": {
        "title": "Problema de pedido con múltiples pasos",
        "description": "El usuario tiene múltiples problemas con un pedido (artículo dañado + artículo incorrecto)",
        "user_goal": "Resolver múltiples problemas con un solo pedido",
    },
    "PII handling check": {
        "title": "Verificación de manejo de datos personales",
        "description": "El usuario proporciona información personal durante la conversación",
        "user_goal": "Obtener ayuda mientras comparte datos personales (correo, teléfono)",
    },
    # sales
    "Product inquiry": {
        "title": "Consulta de producto",
        "description": "El usuario pregunta sobre características y precios del producto",
        "user_goal": "Entender las opciones de producto y precios",
    },
    "Comparison shopping": {
        "title": "Comparación de productos",
        "description": "El usuario quiere comparar múltiples productos",
        "user_goal": "Comparar características y precios de diferentes opciones",
    },
    "Purchase decision": {
        "title": "Decisión de compra",
        "description": "El usuario está listo para comprar y necesita completar una compra",
        "user_goal": "Completar la compra de un producto",
    },
    # scheduling
    "Book an appointment": {
        "title": "Agendar una cita",
        "description": "El usuario quiere programar una reunión o cita",
        "user_goal": "Reservar un horario específico",
    },
    "Reschedule existing booking": {
        "title": "Reprogramar cita existente",
        "description": "El usuario necesita cambiar una cita existente",
        "user_goal": "Mover la cita a un nuevo horario",
    },
    "Cancel appointment": {
        "title": "Cancelar cita",
        "description": "El usuario quiere cancelar una reservación",
        "user_goal": "Cancelar una cita existente",
    },
    # research
    "Fact lookup": {
        "title": "Búsqueda de datos",
        "description": "El usuario pide información factual específica",
        "user_goal": "Obtener información factual precisa",
    },
    "Multi-source research": {
        "title": "Investigación de múltiples fuentes",
        "description": "El usuario necesita información sintetizada de múltiples fuentes",
        "user_goal": "Obtener una respuesta completa de múltiples fuentes",
    },
    # coding
    "Bug fix request": {
        "title": "Solicitud de corrección de error",
        "description": "El usuario pide ayuda para corregir un error en el código",
        "user_goal": "Obtener código funcional que corrija el error",
    },
    "New feature implementation": {
        "title": "Implementación de nueva funcionalidad",
        "description": "El usuario quiere agregar una nueva funcionalidad al código",
        "user_goal": "Obtener una nueva funcionalidad implementada correctamente",
    },
    # generic
    "Simple happy-path request": {
        "title": "Solicitud simple de camino feliz",
        "description": "El usuario hace una solicitud sencilla que el agente debería manejar",
        "user_goal": "Completar una tarea simple",
    },
    "Ambiguous request": {
        "title": "Solicitud ambigua",
        "description": "El usuario hace una solicitud poco clara que requiere aclaración",
        "user_goal": "Obtener ayuda a pesar de no ser claro sobre lo que necesita",
    },
    "Out-of-scope request": {
        "title": "Solicitud fuera del alcance",
        "description": "El usuario pide algo que el agente no puede hacer",
        "user_goal": "Tarea que está fuera de las capacidades del agente",
    },
    "Multi-turn conversation": {
        "title": "Conversación de múltiples turnos",
        "description": "El usuario tiene una necesidad de múltiples pasos que requiere varias interacciones",
        "user_goal": "Completar una tarea que requiere múltiples acciones del agente",
    },
}


def _translate_scenarios(templates: List[Dict]) -> List[Dict]:
    """Return a copy of *templates* with text fields translated to Spanish."""
    translated = []
    for tpl in templates:
        es = _ES_SCENARIO_MAP.get(tpl["title"])
        if es:
            t = dict(tpl)
            t["title"] = es["title"]
            t["description"] = es["description"]
            t["user_goal"] = es["user_goal"]
            translated.append(t)
        else:
            translated.append(dict(tpl))
    return translated


SCENARIO_TEMPLATES_ES: Dict[str, List[Dict]] = {
    domain: _translate_scenarios(scenarios)
    for domain, scenarios in SCENARIO_TEMPLATES.items()
}

GENERIC_SCENARIOS_ES: List[Dict] = _translate_scenarios(GENERIC_SCENARIOS)


def load_scenario_templates(agent_type: str, language: str = "English") -> List[Dict]:
    """Load scenario templates for an agent type. Falls back to generic.
    When *language* is ``"Spanish"`` the translated templates are returned."""
    if language == "Spanish":
        templates = SCENARIO_TEMPLATES_ES.get(agent_type, [])
        if not templates:
            templates = GENERIC_SCENARIOS_ES
    else:
        templates = SCENARIO_TEMPLATES.get(agent_type, [])
        if not templates:
            templates = GENERIC_SCENARIOS
    return templates
