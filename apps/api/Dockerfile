FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /workspace
ENV UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
RUN uv sync --frozen --package amarelo-api --no-dev

COPY apps/api apps/api

HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD [".venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]

CMD ["sh", "-c", ".venv/bin/alembic -c apps/api/alembic.ini upgrade head && .venv/bin/uvicorn api.main:app --app-dir apps/api/src --host 0.0.0.0 --port 8000"]

