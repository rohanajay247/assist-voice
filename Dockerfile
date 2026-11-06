# The public demo (PUBLIC_DEMO=true) as one container, for Google Cloud Run.
#
#   docker build -t assist-voice .
#   docker run -p 8080:8080 -e GEMINI_API_KEY=... -e GROQ_API_KEY=... assist-voice
#
# Stage 1 builds the web app (web/dist); stage 2 runs the API, which serves it.
# Secrets come from the environment (Cloud Run: Secret Manager), never the image.

FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.15 /uv /usr/local/bin/uv
WORKDIR /app

# Dependencies first (cached until pyproject.toml / uv.lock change)
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/ backend/
COPY mcp_servers/ mcp_servers/
COPY --from=web /web/dist web/dist

# The tool servers start with "uv run": use the environment built above, as is
ENV PATH="/app/.venv/bin:$PATH" UV_NO_SYNC=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1 \
    PUBLIC_DEMO=true TOOLBUILDER_ENABLED=false PORT=8080

# One worker: sandboxes and limits live in this process's memory.
# --proxy-headers: Cloud Run's proxy passes the visitor's IP (per-IP limit) and https.
CMD ["sh", "-c", "uvicorn backend.assist.api:app --host 0.0.0.0 --port ${PORT} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
