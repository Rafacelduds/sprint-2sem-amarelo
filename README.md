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
cp apps/api/.env.example apps/api/.env
cp apps/web/.env.example apps/web/.env
docker compose --env-file apps/api/.env --env-file apps/web/.env up --build
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
docker compose --env-file apps/api/.env --env-file apps/web/.env down
```

## Desenvolvimento sem Docker para API e frontend

Pré-requisitos: Python 3.13, uv, Node.js 22 e PostgreSQL. Os comandos abaixo partem
da raiz do repositório.

Instale as dependências conforme os arquivos de lock:

```bash
uv sync --all-packages --all-groups --frozen
npm ci
```

Os arquivos de ambiente ficam em cada aplicação: `apps/api/.env` contém as
configurações do backend e dos serviços; `apps/web/.env` contém as variáveis
`VITE_*` do frontend. Copie os respectivos `.env.example` se ainda não tiver esses
arquivos. Os `.env` locais são ignorados pelo Git e pelo contexto de build Docker.

A API lê `apps/api/.env` independentemente da pasta de onde for iniciada; o Vite
lê `apps/web/.env`. Variáveis de ambiente do processo têm precedência sobre os
arquivos. Os comandos Compose deste README usam ambos os arquivos explicitamente
para interpolar as configurações dos serviços.

Em `apps/api/.env`, configure `DATABASE_URL` para o PostgreSQL local: troque o host
`postgres` por `localhost`. Para acessar o LocalStack pelo host, troque
`http://s3:4566` por `http://localhost:4566` em `S3_ENDPOINT_URL`. Ao voltar ao setup
inteiramente em Docker, use os hosts `postgres` e `s3` da rede do Compose.

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
docker compose --env-file apps/api/.env --env-file apps/web/.env config --quiet
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

O contrato de separação entre dados brutos e derivados, escrita imutável e
proveniência está em
[`docs/armazenamento-e-proveniencia.md`](docs/armazenamento-e-proveniencia.md).

## Coleta de dados

O coletor Olho Vivo roda em processo separado, com intervalo configurável,
posições em operação e garagens e persistência no PostgreSQL. Configure
`CHAVE_API_OLHO_VIVO` (ou `OLHOVIVO_TOKEN`) em `apps/api/.env` e consulte
[execução e contrato da coleta](docs/coleta.md).
O serviço Docker é opcional, ativado pelo profile `coleta`.

O arquivador da US12 preserva as respostas da inbox no S3 em JSON.gz imutável,
sem bloquear a coleta quando o S3 fica indisponível. Comandos de arquivamento,
importação histórica e proveniência estão no contrato de armazenamento acima.

Backup diário, retenção dos sete dumps mais recentes, limpeza segura da inbox e
recuperação em destinos vazios: [backup e restauração](docs/backup-e-restauracao.md).
