# Arquitetura atual

Retrato do setup inspecionado em 18/11/2026. Descreve o código existente; não é uma arquitetura aprovada para todo o produto.

```text
Navegador → web (React/Vite) → /api/* → API (FastAPI)
                                      GET /health
Serviços de desenvolvimento: PostgreSQL e S3 via LocalStack
```

O Vite encaminha `/api/*` para a API, removendo `/api`. A tela inicial consulta o health. Os coletores Olho Vivo e GTFS rodam em processos próprios; processamento de indicadores ainda depende das respectivas US.

| Local | Responsabilidade existente |
| --- | --- |
| [apps/api/src/api](../apps/api/src/api) | Aplicação FastAPI, configurações e base de acesso ao banco |
| [apps/api/src/api/gtfs](../apps/api/src/api/gtfs) | Download GTFS, preservação S3, catálogo e seleção temporal |
| [apps/api/migrations](../apps/api/migrations) | Migrações Alembic |
| [apps/api/tests](../apps/api/tests) | Testes da API |
| [apps/web/src](../apps/web/src) | Interface React/TypeScript e seus testes |
| [packages/api-client](../packages/api-client) | Cliente TypeScript gerado do contrato OpenAPI |
| [infra/localstack](../infra/localstack) | Inicialização do bucket S3 local |
| [compose.yaml](../compose.yaml) | Serviços e volumes de desenvolvimento |
| [.github/workflows/ci.yml](../.github/workflows/ci.yml) | Verificações de backend e frontend na CI |

## Contratos e configuração

O contrato HTTP parte dos modelos e rotas da API. Ao alterá-lo, exporte o OpenAPI e regenere o cliente conforme o [README](../README.md#openapi-e-cliente-typescript); não edite manualmente os arquivos gerados. O `openapi.json` é um artefato local ignorado pelo Git.

As configurações privadas ficam em `apps/api/.env`, com exemplo em
[`apps/api/.env.example`](../apps/api/.env.example); as públicas do Vite ficam em
`apps/web/.env`. Em AWS, o armazenamento aceita a identidade IAM do processo.
Comandos de instalação, migrações e testes ficam centralizados no README.

## Evolução

A US02 acrescenta `python -m api.gtfs`: o ZIP original vai para uma chave S3 por
SHA-256; versões e capturas ficam no PostgreSQL. A coleta de posições grava a
referência GTFS ou o motivo de ausência na mesma transação da posição. A integração
depende da implementação de US01. Regras e limites em [gtfs.md](gtfs.md).
O arquivador da US12 consome a inbox em processo separado e grava JSON.gz imutável,
catálogo de objetos e manifestos de proveniência; consulte
[armazenamento](armazenamento-e-proveniencia.md).

A coleta Olho Vivo está em `apps/api/src/api/collection`, executada em processo separado. Persiste ciclos, uma inbox de respostas e posições deduplicadas no PostgreSQL; veja o [contrato da coleta](coleta.md). O acervo bruto imutável S3 continua sob responsabilidade da US12. Processamento analítico e publicação de indicadores ainda dependem das respectivas US. Escolhas com impacto em várias US precisam de justificativa em [decisoes.md](decisoes.md).
