"""Search tool - read only."""
import requests
from langchain.tools import tool


@tool
def search_knowledge_base(query: str) -> str:
    """Search the internal knowledge base for answers to customer questions."""
    response = requests.get(f"https://api.acme.com/kb/search?q={query}")
    return response.json()
