"""Email notification tool - handles PII (email address)."""
import requests
from langchain.tools import tool


@tool
def send_notification_email(customer_email: str, subject: str, body: str) -> str:
    """Send an email notification to the customer."""
    if not customer_email:
        raise ValueError("customer_email is required")

    payload = {"to": customer_email, "subject": subject, "body": body}
    requests.post("https://mail.api/send", json=payload)
    send_email(customer_email, subject, body)
    return f"Email sent to {customer_email}"
