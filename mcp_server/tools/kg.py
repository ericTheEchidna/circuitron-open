"""Knowledge graph tool: query_knowledge_graph.

Stub that returns an empty result until the static JSON index is built
(CIRCUITRON-012).
"""

from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)


async def query_knowledge_graph(query: str) -> str:
    """Look up SKiDL API structure (classes, methods, signatures) from the index.

    Returns a JSON string with matching entries:
      {"matches": [{"name": "...", "type": "class|method", "signature": "...", "doc": "..."}, ...]}
    """
    log.info("query_knowledge_graph: %r [stub]", query)
    # TODO (CIRCUITRON-012): load skidl_kg.json, fuzzy-search, return matches
    return json.dumps({"matches": []})
