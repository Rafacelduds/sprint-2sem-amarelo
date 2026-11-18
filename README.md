# Sprint Amarelo

Contexto compartilhado, arquitetura, dados e fluxo de contribuição estão no
[índice da documentação](docs/README.md). Para começar a desenvolver, siga o setup abaixo.

Setup mínimo com uma API FastAPI e uma aplicação React/Vite que exibe o resultado
de `GET /health`.

## Stack

- FastAPI, Pydantic, SQLAlchemy, Alembic e Pyright;
- React, TypeScript e Vite;
- cliente TypeScript gerado do OpenAPI com Hey API;
- PostgreSQL;
- S3 compatível via LocalStack no desenvolvimento;
- uv, pytest, Ruff, Vitest, ESLint e Docker Compose.

## Subir tudo com Docker

Na raiz do repositório:

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

Para encerrar os serviços, preservando os volumes:

```bash
docker compose down
```

## Desenvolvimento sem Docker para API e frontend

Pré-requisitos: Python 3.13, uv, Node.js 22 e PostgreSQL. Os comandos abaixo partem
da raiz do repositório.

Instale as dependências conforme os arquivos de lock:

```bash
uv sync --all-packages --all-groups --frozen
npm ci
```

Configure `DATABASE_URL` para o PostgreSQL local. Se usar `.env.example` como base,
troque o host `postgres` por `localhost`; para acessar o LocalStack pelo host,
troque `http://s3:4566` por `http://localhost:4566` em `S3_ENDPOINT_URL`.

Execute API e frontend em terminais separados:

```bash
uv run --package amarelo-api uvicorn api.main:app --app-dir apps/api/src --reload
```

```bash
npm run dev
```

## Banco e migrações

Com o PostgreSQL disponível e `DATABASE_URL` configurada:

```bash
uv run --package amarelo-api alembic -c apps/api/alembic.ini upgrade head
uv run --package amarelo-api alembic -c apps/api/alembic.ini revision --autogenerate -m "descricao"
```

## OpenAPI e cliente TypeScript

Exporte o contrato diretamente da aplicação FastAPI, sem precisar manter o
servidor ligado:

```bash
uv run --package amarelo-api python apps/api/scripts/export_openapi.py
```

Depois, gere o cliente TypeScript:

```bash
npm run generate:api
```

Isso atualiza `openapi.json` e os arquivos em `packages/api-client/src/generated`.
O frontend pode importar o pacote `@amarelo/api-client`. `openapi.json` é um
artefato local ignorado pelo Git; gere-o antes de atualizar o cliente.

## Qualidade

```bash
uv run pytest
uv run ruff check .
uv run pyright
npm test
npm run lint --workspace @amarelo/web
npm run build
```

A CI executa essas verificações de backend e frontend. Para conferir a
configuração dos serviços sem iniciá-los:

```bash
docker compose config --quiet
```

## Estrutura

```text
apps/
  api/        FastAPI, SQLAlchemy e Alembic
  web/        React, TypeScript e Vite
packages/
  api-client/ cliente gerado do OpenAPI
infra/
  localstack/ inicialização do bucket S3 de desenvolvimento
```

## Coleta de dados

O coletor Olho Vivo roda em processo separado, com intervalo configurável,
posições em operação e garagens e persistência no PostgreSQL. Configure
`OLHOVIVO_TOKEN` no `.env` privado e consulte [execução e contrato da coleta](docs/coleta.md).
O serviço Docker é opcional, ativado pelo profile `coleta`.

O coletor GTFS também roda em processo separado: configure `GTFS_SOURCE_URL`, aplique
as migrações e execute `uv run --package amarelo-api python -m api.gtfs --once`.
Sem `--once`, verifica a fonte diariamente e tenta novamente em até cinco minutos
após falhas. Consulte [GTFS: configuração, armazenamento e associação temporal](docs/gtfs.md).
