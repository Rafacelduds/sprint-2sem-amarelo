# Sprint Amarelo

Setup mínimo para validar a stack do time. O monorepo contém uma API FastAPI, um
coletor Python separado e uma aplicação React/Vite que exibe o resultado de
`GET /health`.

## Stack

- FastAPI, Pydantic, SQLAlchemy, Alembic e Pyright;
- React, TypeScript e Vite;
- cliente TypeScript gerado do OpenAPI com Hey API;
- PostgreSQL;
- S3 compatível via LocalStack no desenvolvimento;
- DuckDB e Parquet no coletor;
- pytest, Vitest e Docker Compose;
- estrutura inicial do Spec-Kit em `.specify/` e `specs/`.

## Subir tudo com Docker

```bash
cp .env.example .env
docker compose up --build
```

Acesse:

- frontend: http://localhost:5173
- API: http://localhost:8000
- Swagger: http://localhost:8000/docs
- health: http://localhost:8000/health
- endpoint S3 local: http://localhost:4566

O Vite encaminha `/api/*` para a API e remove o prefixo `/api`. A tela inicial
consulta `/api/health` e mostra o estado retornado.

## Desenvolvimento sem Docker

Pré-requisitos: Python 3.13, uv, Node.js 22 e PostgreSQL.

```bash
uv sync --all-packages --all-groups
npm install
uv run --package amarelo-api uvicorn api.main:app --app-dir apps/api/src --reload
npm run dev
```

## Banco e migrações

```bash
uv run --package amarelo-api alembic -c apps/api/alembic.ini upgrade head
uv run --package amarelo-api alembic -c apps/api/alembic.ini revision --autogenerate -m "descricao"
```

## OpenAPI e cliente TypeScript

O contrato é exportado diretamente da aplicação FastAPI, sem precisar manter o
servidor ligado:

```bash
make api-client
```

Isso atualiza `openapi.json` e os arquivos em `packages/api-client/src/generated`.
O frontend pode importar o pacote `@amarelo/api-client`.

## Qualidade

```bash
uv run pytest
uv run ruff check .
uv run pyright
npm test
npm run lint --workspace @amarelo/web
npm run build
```

## Estrutura

```text
apps/
  api/        FastAPI, SQLAlchemy e Alembic
  collector/  processo separado com DuckDB, Parquet e S3
  web/        React, TypeScript e Vite
packages/
  api-client/ cliente gerado do OpenAPI
specs/        especificações por funcionalidade
```

O setup não inclui fila. API e coletor são processos independentes e podem ser
separados por uma fila quando o volume ou a necessidade de retentativas justificar.

