# Patched Circuitron MCP server that supports local pgvector (no Supabase needed).
#
# Adds psycopg2-binary and replaces src/utils.py with a version that accepts
# DATABASE_URL=postgresql://... in addition to the cloud SUPABASE_URL path.
#
# Build:
#   docker build -t circuitron-mcp-local ./mcp
#
# Run (local Postgres path):
#   docker run --env-file mcp.env -p 8051:8051 circuitron-mcp-local
#
# The container exposes port 8051 (SSE transport) — same as the upstream image.

FROM ghcr.io/shaurya-sethi/circuitron-mcp:latest

# Install psycopg2 (binary wheel — no libpq-dev needed)
RUN pip install --no-cache-dir psycopg2-binary

# Patch: replace utils.py with the provider-agnostic version.
# The upstream repo layout is src/utils.py; the Docker WORKDIR is /app.
COPY utils_local.py /app/src/utils.py
