"""
Tool definitions for the customer support agent.
"""

import requests
from langchain.tools import tool, BaseTool
from pydantic import BaseModel, Field


@tool
def track_order(order_id: str) -> str:
    """Look up the current status of an order by its order ID (e.g. ORD-12345)."""
    # Simulated API call
    response = requests.get(f"https://api.acme.com/orders/{order_id}")
    return f"Order {order_id}: Shipped, arriving in 2 days"


@tool
def search_knowledge_base(query: str) -> str:
    """Search the internal knowledge base for answers to customer questions."""
    # Simulated vector search
    return f"Found 3 articles matching '{query}'"


@tool
def escalate_to_human(reason: str, customer_email: str) -> str:
    """Escalate the conversation to a human support agent.
    Use this when you cannot resolve the customer's issue.
    """
    # Send notification
    return f"Escalated to human agent. Reason: {reason}. Customer: {customer_email}"


class RefundInput(BaseModel):
    order_id: str = Field(description="The order ID to refund")
    amount: float = Field(description="Refund amount in USD")
    reason: str = Field(default="Customer request", description="Reason for refund")


class RefundTool(BaseTool):
    """Process a refund for a customer order. Requires manager approval for amounts over $100."""

    name: str = "initiate_refund"
    description: str = "Process a refund for an order. Use with caution - this charges the company."
    args_schema: type = RefundInput

    def _run(self, order_id: str, amount: float, reason: str = "Customer request") -> str:
        if amount > 100:
            return f"Refund of ${amount} for {order_id} requires manager approval."
        return f"Refund of ${amount} processed for order {order_id}. Reason: {reason}"


initiate_refund = RefundTool()
