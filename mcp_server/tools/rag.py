"""RAG tools: perform_rag_query and search_code_examples.

Stubs that return empty results until the pgvector + Ollama backends
are wired in (CIRCUITRON-00F, CIRCUITRON-010, CIRCUITRON-011).
"""

from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)


async def perform_rag_query(query: str, top_k: int = 5) -> str:
    """Search SKiDL documentation chunks via pgvector similarity search.

    Returns a JSON string matching the shape the Circuitron agents expect:
      [{"content": "...", "url": "...", "similarity": 0.0}, ...]
    """
    log.info("perform_rag_query: %r (top_k=%s) [stub]", query, top_k)
    # TODO (CIRCUITRON-011): embed query with Ollama, search pgvector crawled_pages
    return json.dumps([])


async def search_code_examples(query: str, top_k: int = 5) -> str:
    """Search SKiDL code examples via pgvector similarity search.

    Returns a JSON string matching the shape the Circuitron agents expect:
      [{"code": "...", "description": "...", "similarity": 0.0}, ...]
    """
    log.info("search_code_examples: %r (top_k=%s) [stub]", query, top_k)
    # TODO (CIRCUITRON-011): embed query with Ollama, search pgvector code_examples
    return json.dumps([])
