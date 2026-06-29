"""Refund tool - state modifying with guard clauses."""
import requests
from langchain.tools import tool


@tool
def process_refund(order_id: str, amount: float, reason: str = "customer request") -> str:
    """Process a refund for a customer order. Use with caution."""
    if not order_id:
        raise ValueError("order_id is required")
    if amount is None:
        raise ValueError("amount is required")
    assert isinstance(order_id, str)
    validate_order(order_id)

    db.execute("UPDATE orders SET status='refunded' WHERE id=?", order_id)
    db.commit()
    requests.post("https://payment.api/refund", json={"order_id": order_id, "amount": amount})
    return f"Refund of ${amount} processed for {order_id}"
