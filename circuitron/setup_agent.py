"""Setup Agent definition for knowledge base initialization.

Creates an isolated agent that connects to its own MCP server instance and
invokes MCP tools to populate Supabase (docs) and Neo4j (knowledge graph).
"""

from __future__ import annotations

from typing import Any

from .providers import get_provider
from .provider import AgentHandle, ModelConfig
from .config import settings
from .prompts import SETUP_AGENT_PROMPT
from .models import SetupOutput

_provider = get_provider(settings)


def _tool_choice_for_mcp(model: str) -> str:
    """Return appropriate tool_choice for MCP tools based on the model.

    Mirrors the behavior used elsewhere: allow 'auto' for o4-mini, otherwise
    require explicit tool usage for determinism.
    """

    return "auto" if model == "o4-mini" else "required"


def create_setup_agent() -> tuple[AgentHandle, Any]:
    """Create and configure the Setup Agent and its dedicated MCP server.

    Returns:
        (agent, server): The configured agent handle and a fresh MCP server
        instance.

    Notes:
        The caller is responsible for connecting and cleaning up the server.
    """

    model_settings = ModelConfig(tool_choice=_tool_choice_for_mcp(settings.documentation_model))

    # Use a dedicated MCP server for the setup flow to keep it isolated
    server = _provider.make_mcp_server(
        url=f"{settings.mcp_url}/sse",
        timeout=settings.network_timeout,
    )
    agent = _provider.create_agent(
        name="Circuitron-Setup",
        instructions=SETUP_AGENT_PROMPT,
        model=settings.documentation_model,
        output_type=SetupOutput,
        mcp_servers=[server],
        model_settings=model_settings,
    )
    return agent, server


def get_setup_agent() -> tuple[AgentHandle, Any]:
    """Return a new Setup Agent and its MCP server instance."""

    return create_setup_agent()


__all__ = ["create_setup_agent", "get_setup_agent"]

