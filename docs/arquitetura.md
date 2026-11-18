# Arquitetura atual

Retrato do setup inspecionado em 18/11/2026. Descreve o código existente; não é uma arquitetura aprovada para todo o produto.

```text
Navegador → web (React/Vite) → /api/* → API (FastAPI)
                                      GET /health
Serviços de desenvolvimento: PostgreSQL e S3 via LocalStack
```

O Vite encaminha `/api/*` para a API, removendo `/api`. A tela inicial consulta o health. A presença de PostgreSQL e S3 no ambiente não significa que já exista um pipeline de coleta, persistência operacional ou cálculo de indicadores.

| Local | Responsabilidade existente |
| --- | --- |
| [apps/api/src/api](../apps/api/src/api) | Aplicação FastAPI, configurações e base de acesso ao banco |
| [apps/api/migrations](../apps/api/migrations) | Migrações Alembic |
| [apps/api/tests](../apps/api/tests) | Testes da API |
| [apps/web/src](../apps/web/src) | Interface React/TypeScript e seus testes |
| [packages/api-client](../packages/api-client) | Cliente TypeScript gerado do contrato OpenAPI |
| [infra/localstack](../infra/localstack) | Inicialização do bucket S3 local |
| [compose.yaml](../compose.yaml) | Serviços e volumes de desenvolvimento |
| [.github/workflows/ci.yml](../.github/workflows/ci.yml) | Verificações de backend e frontend na CI |

## Contratos e configuração

O contrato HTTP parte dos modelos e rotas da API. Ao alterá-lo, exporte o OpenAPI e regenere o cliente conforme o [README](../README.md#openapi-e-cliente-typescript); não edite manualmente os arquivos gerados. O `openapi.json` é um artefato local ignorado pelo Git.

As configurações da API estão em [config.py](../apps/api/src/api/config.py); as variáveis de exemplo, em [.env.example](../.env.example). Valores locais de desenvolvimento não são credenciais de produção. Comandos de instalação, migrações e testes ficam centralizados no README.

## Evolução

Coleta, processamento e publicação de indicadores ainda precisam ser definidos pelas US e suas dependências. Ao implementar, atualize este mapa com os componentes e fluxos que realmente existirem. Escolhas de armazenamento, contratos entre componentes ou regras com impacto em várias US precisam de justificativa em [decisoes.md](decisoes.md).
