"""
Sample customer support agent built with LangChain.
Used to test the agent code analyzer.
"""

from langchain.agents import AgentExecutor, create_react_agent
from langchain_openai import ChatOpenAI
from langchain.memory import ConversationBufferMemory
from langchain_core.prompts import ChatPromptTemplate

from tools import track_order, initiate_refund, search_knowledge_base, escalate_to_human

SYSTEM_PROMPT = """You are a helpful customer support agent for Acme Corp.
You help customers with order tracking, refunds, and general inquiries.
Never disclose customer payment details like credit card numbers.
Always verify the customer's identity before making changes.
If you cannot resolve an issue, escalate to a human agent.
"""

prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)  # Switched to gpt-4o-mini for cost savings
memory = ConversationBufferMemory(return_messages=True)

tools = [track_order, initiate_refund, search_knowledge_base, escalate_to_human]

agent = create_react_agent(llm, tools, prompt)
agent_executor = AgentExecutor(agent=agent, tools=tools, memory=memory, verbose=True)


def run_agent(user_input: str) -> str:
    """Run the support agent with a user message."""
    result = agent_executor.invoke({"input": user_input})
    return result["output"]


if __name__ == "__main__":
    while True:
        user_input = input("You: ")
        if user_input.lower() in ("quit", "exit"):
            break
        response = run_agent(user_input)
        print(f"Agent: {response}")
