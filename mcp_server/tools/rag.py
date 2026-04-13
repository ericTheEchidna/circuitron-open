"""RAG tools: perform_rag_query and search_code_examples.

Both tools follow the same pattern:
  1. Embed the query via Ollama (embeddings.embed)
  2. Call the corresponding pgvector stored function
  3. Return ranked results as a JSON string

Database connection is managed as a module-level ThreadedConnectionPool
so that one pool is shared across all concurrent MCP calls. psycopg2 is
sync; calls are dispatched to a thread-pool executor so they don't block
the event loop.

Environment variables:
  POSTGRES_URL  - Full DSN (default: postgresql://captain:memex2026@pgvector:5432/circuitron)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import psycopg2
import psycopg2.extras
import psycopg2.pool

from ..embeddings import embed

log = logging.getLogger(__name__)

_POSTGRES_URL: str = os.getenv(
    "POSTGRES_URL",
    "postgresql://captain:memex2026@pgvector:5432/circuitron",
)

# Thread-safe connection pool; initialised once on first use.
# min=1, max=5 is plenty for a single-node MCP server.
_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(1, 5, _POSTGRES_URL)
        log.info("pgvector connection pool created (%s)", _POSTGRES_URL)
    return _pool


# ---------------------------------------------------------------------------
# Synchronous DB helpers — run inside run_in_executor
# ---------------------------------------------------------------------------

def _query_crawled_pages(vector_str: str, top_k: int) -> list[dict[str, Any]]:
    """Call match_crawled_pages and return a list of dicts."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Pass the embedding as a text literal cast to vector — avoids
            # needing the pgvector Python codec.
            cur.execute(
                "SELECT url, chunk_number, content, metadata, source_id, similarity"
                " FROM match_crawled_pages(%s::vector, %s)",
                (vector_str, top_k),
            )
            rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        pool.putconn(conn)


def _query_code_examples(vector_str: str, top_k: int) -> list[dict[str, Any]]:
    """Call match_code_examples and return a list of dicts."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT url, chunk_number, content, summary, metadata, source_id, similarity"
                " FROM match_code_examples(%s::vector, %s)",
                (vector_str, top_k),
            )
            rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        pool.putconn(conn)


def _vec_to_pg(vector: list[float]) -> str:
    """Format a float list as the pgvector text literal '[x,y,...]'."""
    return "[" + ",".join(str(v) for v in vector) + "]"


# ---------------------------------------------------------------------------
# Public async tool handlers
# ---------------------------------------------------------------------------


async def perform_rag_query(query: str, top_k: int = 5) -> str:
    """Search SKiDL documentation chunks via pgvector similarity search.

    Returns a JSON string:
      [{"content": "...", "url": "...", "similarity": 0.0}, ...]
    """
    log.info("perform_rag_query: %r (top_k=%s)", query, top_k)

    vector = await embed(query)
    vector_str = _vec_to_pg(vector)

    loop = asyncio.get_running_loop()
    try:
        rows = await loop.run_in_executor(None, _query_crawled_pages, vector_str, top_k)
    except Exception as exc:
        log.error("perform_rag_query DB error: %s", exc)
        return json.dumps({"error": str(exc), "results": []})

    # Return only the fields agents need; drop chunk_number / source_id / metadata
    results = [
        {"content": r["content"], "url": r["url"], "similarity": r["similarity"]}
        for r in rows
    ]
    return json.dumps(results)


async def search_code_examples(query: str, top_k: int = 5) -> str:
    """Search SKiDL code examples via pgvector similarity search.

    Returns a JSON string:
      [{"code": "...", "description": "...", "similarity": 0.0}, ...]
    """
    log.info("search_code_examples: %r (top_k=%s)", query, top_k)

    vector = await embed(query)
    vector_str = _vec_to_pg(vector)

    loop = asyncio.get_running_loop()
    try:
        rows = await loop.run_in_executor(None, _query_code_examples, vector_str, top_k)
    except Exception as exc:
        log.error("search_code_examples DB error: %s", exc)
        return json.dumps({"error": str(exc), "results": []})

    # Map content→code and summary→description to match agent expectations
    results = [
        {"code": r["content"], "description": r["summary"], "similarity": r["similarity"]}
        for r in rows
    ]
    return json.dumps(results)
