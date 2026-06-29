"""OpenAI-style tool configuration."""

tools = [
    {
        "type": "function",
        "function": {
            "name": "check_order_status",
            "description": "Check the current status of an order",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "The order ID"}
                }
            }
        }
    }
]
