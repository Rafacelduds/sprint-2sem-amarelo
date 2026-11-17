FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /workspace
ENV UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace/apps/collector/src

COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/collector/pyproject.toml apps/collector/pyproject.toml
RUN uv sync --frozen --package amarelo-collector --no-dev

COPY apps/collector apps/collector

CMD [".venv/bin/python", "-m", "collector.main"]

