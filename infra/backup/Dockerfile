FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

# Cliente oficial da mesma versão major do servidor, sem Docker socket no job.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
       -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
       > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update && apt-get install -y --no-install-recommends postgresql-client-16 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
ENV UV_LINK_MODE=copy PYTHONUNBUFFERED=1 PYTHONPATH=/workspace/apps/api/src
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
RUN uv sync --frozen --package amarelo-api --no-dev
COPY apps/api apps/api
CMD [".venv/bin/python", "-m", "api.backup", "watch"]
