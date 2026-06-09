# SchedulerRX Constraint Debugger — ADK agent on Cloud Run (Gemini + real CP-SAT solver).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080 \
    GOOGLE_GENAI_USE_VERTEXAI=FALSE

WORKDIR /app

# Dependencies first for layer caching (frozen to the tested venv).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code:
#  - agent/      : MCP server (mcp_server) + realsolver + the kept diagnostic proto-scan
#  - adk_app/    : ADK agent package (root_agent) discovered by get_fast_api_app
#  - vendor/     : pinned, gitignored snapshot of the proprietary SchedulerRX solver
#  - server.py   : FastAPI/ADK entrypoint
COPY agent/ ./agent/
COPY adk_app/ ./adk_app/
COPY vendor/ ./vendor/
COPY server.py ./

EXPOSE 8080

# ADK FastAPI app (agent + dev Web UI) under uvicorn. The agent's McpToolset spawns
# `python -m agent.mcp_server` (cwd=/app) in-container; the real model is built there
# against vendor/. Cloud Run injects $PORT.
CMD ["sh", "-c", "exec uvicorn server:app --host 0.0.0.0 --port ${PORT:-8080}"]
