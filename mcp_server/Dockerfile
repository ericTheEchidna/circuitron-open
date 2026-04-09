FROM python:3.12-slim

# /app is the repo root so `python -m mcp_server.main` resolves correctly
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the mcp_server package (build context is the repo root)
COPY mcp_server/ mcp_server/

ENV HOST=0.0.0.0
ENV PORT=8051

EXPOSE 8051

CMD ["python", "-m", "mcp_server.main"]
