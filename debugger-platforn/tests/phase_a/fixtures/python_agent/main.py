"""Sample customer support agent for testing."""
from langchain.agents import AgentExecutor, create_react_agent
from langchain_openai import ChatOpenAI
from langchain.memory import ConversationBufferMemory

from tools.search import search_knowledge_base
from tools.refund import process_refund
from tools.send_email import send_notification_email

SYSTEM_PROMPT = """You are a customer support agent for Acme Corp.

1. Never disclose customer payment details like credit card numbers.
2. Always verify the customer's identity before making account changes.
3. If the customer requests a refund for an order older than 30 days, escalate to a supervisor.
4. Do not process refunds exceeding $500 without manager approval.
5. When in doubt about a customer's request, ask clarifying questions before taking action.
"""

tools = [search_knowledge_base, process_refund, send_notification_email]
