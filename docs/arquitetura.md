# Arquitetura atual

Retrato do setup inspecionado em 18/11/2026. Descreve o código existente; não é uma arquitetura aprovada para todo o produto.

```text
Navegador → web (React/Vite) → /api/* → API (FastAPI)
                                      GET /health
                                      GET /vehicles/positions → Olho Vivo
Serviços de desenvolvimento: PostgreSQL e S3 via LocalStack
```

O Vite encaminha `/api/*` para a API, removendo `/api`. A tela inicial exibe posições com Leaflet, filtro de linha/sentido e expiração de coleta em 60 segundos. Os coletores Olho Vivo e GTFS rodam em processos próprios; a coleta operacional US01/US29 persiste no PostgreSQL, conforme o contrato abaixo. O mapa ainda consulta diretamente o Olho Vivo; processamento analítico e cálculo de indicadores continuam dependentes das respectivas US.

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

## Mapa ao vivo — US22

O endpoint público `/vehicles/positions` adapta a resposta do Olho Vivo para um snapshot com `collected_at`, `served_at`, linhas, veículos e horário GPS. O cache de 15 segundos é por processo e não persiste histórico; a integração futura com US01 deve preservar esse contrato. O token fica no backend. Sem resposta inicial há 503; falhas posteriores não renovam artificialmente a data da coleta. Configuração, execução e limites estão no [README](../README.md#mapa-ao-vivo-us22).

O catálogo público `/network/catalog` e a geometria `/network/routes/{line_id}` usam um adaptador de exportação versionada da US02. Contrato, limitações e fixture em [rede-us02.md](integracoes/rede-us02.md). O coletor GTFS da US02 já está no checkout; a exportação com geometrias e correspondências validada para o mapa ainda depende de integração.

O mapa usa Supercluster sobre as posições já filtradas. Grupos neutros representam proximidade, sem atribuir uma cor única a áreas misturadas; as posições individuais mantêm as cores confirmadas. Panes Leaflet separam mapa-base, percursos (z=350), veículos (z=450) e grupos (z=460). Percursos usam 40% de opacidade e não recebem eventos de ponteiro. O índice é reutilizado durante a navegação e reconstruído quando o conjunto de posições muda.

## Evolução

A US04 acrescenta o processo `python -m api.schedules`, que preserva programação
oficial em JSON/S3 e gera partidas em Parquet com relatório de proveniência.
Pode consumir o catálogo PostgreSQL/S3 da US02 como alternativa GTFS, sem repetir
a captura do ZIP na origem. Contrato e limites em [programacao.md](programacao.md).

A US02 acrescenta `python -m api.gtfs`: o ZIP original vai para uma chave S3 por
SHA-256; versões e capturas ficam no PostgreSQL. A coleta de posições grava a
referência GTFS ou o motivo de ausência na mesma transação da posição. A integração
depende da implementação de US01. Regras e limites em [gtfs.md](gtfs.md).
O arquivador da US12 consome a inbox em processo separado e grava JSON.gz imutável,
catálogo de objetos e manifestos de proveniência; consulte
[armazenamento](armazenamento-e-proveniencia.md).

A coleta Olho Vivo está em `apps/api/src/api/collection`, executada em processo separado. Persiste ciclos, uma inbox de respostas e posições deduplicadas no PostgreSQL; veja o [contrato da coleta](coleta.md). O acervo bruto imutável S3 continua sob responsabilidade da US12. Processamento analítico e publicação de indicadores ainda dependem das respectivas US. Escolhas com impacto em várias US precisam de justificativa em [decisoes.md](decisoes.md).
