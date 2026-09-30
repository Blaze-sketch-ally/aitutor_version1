import os
from langsmith import Client
from langsmith.run_helpers import traceable

# Initialize LangSmith client (optional but useful)
client = Client(
    api_key=os.getenv("LANGCHAIN_API_KEY")
)


def trace(name: str):
    """
    Wrapper to simplify tracing across all agents
    """
    return traceable(name=name)