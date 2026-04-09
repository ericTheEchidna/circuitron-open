"""Local MCP server for Circuitron.

Exposes the same three tools as the upstream ghcr.io/shaurya-sethi/circuitron-mcp
container over the standard MCP SSE transport, so the main Circuitron app
requires zero changes to connect to it.

Backends (implemented in subsequent tasks):
  - perform_rag_query      -> pgvector + Ollama embeddings
  - search_code_examples   -> pgvector + Ollama embeddings
  - query_knowledge_graph  -> static JSON index (no Neo4j)
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import (
    CallToolResult,
    ListToolsResult,
    TextContent,
    Tool,
)
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

from .tools.rag import perform_rag_query, search_code_examples
from .tools.kg import query_knowledge_graph

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool schemas — must match what the upstream server advertised so agent
# prompts that name these tools continue to work unchanged.
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    Tool(
        name="perform_rag_query",
        description=(
            "Search the SKiDL documentation corpus for relevant content. "
            "Returns ranked documentation chunks that match the query."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query about SKiDL APIs or usage.",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Maximum number of results to return.",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="search_code_examples",
        description=(
            "Search for working SKiDL code examples. "
            "Returns relevant code snippets with descriptions."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Description of the circuit or SKiDL pattern to find examples for.",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Maximum number of results to return.",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="query_knowledge_graph",
        description=(
            "Query the SKiDL API knowledge graph to look up class definitions, "
            "method signatures, attributes, and module structure."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Class name, method name, or API concept to look up.",
                },
            },
            "required": ["query"],
        },
    ),
]

# ---------------------------------------------------------------------------
# MCP server wiring
# ---------------------------------------------------------------------------

mcp = Server("skidl_docs")


@mcp.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@mcp.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    log.info("Tool call: %s args=%s", name, arguments)

    if name == "perform_rag_query":
        result = await perform_rag_query(
            query=arguments["query"],
            top_k=arguments.get("top_k", 5),
        )
    elif name == "search_code_examples":
        result = await search_code_examples(
            query=arguments["query"],
            top_k=arguments.get("top_k", 5),
        )
    elif name == "query_knowledge_graph":
        result = await query_knowledge_graph(query=arguments["query"])
    else:
        result = f"Unknown tool: {name}"

    return [TextContent(type="text", text=str(result))]


# ---------------------------------------------------------------------------
# Starlette app with SSE transport
# The MCP SDK's SseServerTransport handles the SSE + POST message endpoints.
# ---------------------------------------------------------------------------

transport = SseServerTransport("/messages/")


async def handle_sse(request: Request) -> Response:
    async with transport.connect_sse(
        request.scope, request.receive, request._send  # type: ignore[attr-defined]
    ) as (read_stream, write_stream):
        await mcp.run(
            read_stream,
            write_stream,
            mcp.create_initialization_options(),
        )
    return Response()


app = Starlette(
    routes=[
        Route("/sse", endpoint=handle_sse),
        Mount("/messages/", app=transport.handle_post_message),
    ],
)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8051"))
    log.info("Starting local Circuitron MCP server on %s:%s", host, port)
    uvicorn.run(app, host=host, port=port)
