"""Manage lifecycle of MCP servers used in Circuitron."""

from __future__ import annotations
import asyncio
import logging

from typing import Any

from .providers import get_provider
from .config import settings


class MCPManager:
    """Central manager for MCP server connections.

    This class manages a single MCP server connection that is shared
    across all agents in the Circuitron pipeline. The single server
    provides both documentation and validation capabilities.
    """

    def __init__(self) -> None:
        self._server = get_provider(settings).make_mcp_server(
            url=f"{settings.mcp_url}/sse",
            timeout=settings.network_timeout,
        )

    async def _connect_server_with_timeout(self) -> None:
        """Attempt to connect to the MCP server with retries."""
        for attempt in range(3):
            try:
                await asyncio.wait_for(
                    self._server.connect(),  # type: ignore[no-untyped-call]
                    timeout=settings.network_timeout,
                )
                logging.info(
                    "Successfully connected to MCP server: %s", self._server.name
                )
                return
            except Exception as exc:  # pragma: no cover - network errors
                if attempt == 2:
                    logging.warning(
                        "Failed to connect MCP server %s: %s", self._server.name, exc
                    )
                else:
                    await asyncio.sleep(2**attempt)

    async def initialize(self) -> None:
        """Connect the managed MCP server."""
        await self._connect_server_with_timeout()

    async def cleanup(self) -> None:
        """Disconnect the managed MCP server."""
        try:
            await self._server.cleanup()  # type: ignore[no-untyped-call]
        except Exception as exc:  # pragma: no cover - cleanup errors
            logging.warning("Error cleaning MCP server %s: %s", self._server.name, exc)

    def get_server(self) -> Any:
        """Return the MCP server instance used by all agents."""
        return self._server


# Global manager instance used across the application
mcp_manager = MCPManager()

__all__ = ["MCPManager", "mcp_manager"]
