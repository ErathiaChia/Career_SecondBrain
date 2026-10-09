"""The agent's tool layer. Importing this package registers every tool."""
from era_mcp.agent_tools import registry  # noqa: F401
from era_mcp.agent_tools import career, document, investigation, knowledge, structural  # noqa: F401

__all__ = ["registry"]
