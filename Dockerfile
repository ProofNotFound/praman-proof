# Praman: one container serving the API and the built web app (same origin, SSE works).
# Deploy on Render/Railway/Fly/a VPS; the app listens on $PORT (default 8000).

FROM node:22-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PRAMAN_LLM_MODE=replay \
    PRAMAN_PUBLIC_MODE=1 \
    MALLOC_ARENA_MAX=2

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY praman ./praman
COPY data ./data
COPY tests/fixtures/replay ./tests/fixtures/replay
COPY --from=web /app/frontend/dist ./frontend/dist
RUN uv sync --frozen --no-dev && mkdir -p data/cache

EXPOSE 8000
CMD ["sh", "-c", "uv run --no-dev uvicorn praman.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
