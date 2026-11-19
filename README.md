# Sprint Amarelo

Contexto compartilhado, arquitetura, dados e fluxo de contribuição estão no
[índice da documentação](docs/README.md). Para começar a desenvolver, siga o setup abaixo.

API FastAPI e aplicação React/Vite com mapa público de posições dos ônibus (US22)
e consulta de documentos oficiais (US05).

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
- acervo documental: http://localhost:5173/#acervo
- API: http://localhost:8000
- Swagger: http://localhost:8000/docs
- health: http://localhost:8000/health
- endpoint S3 local: http://localhost:4566

O Vite encaminha `/api/*` para a API e remove o prefixo `/api`. A tela inicial
consulta `/api/vehicles/positions` e mostra as posições e a idade da coleta.

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

Relatório público de lacunas, versões GTFS e referências de programação:
[execução e contrato da US13](docs/confiabilidade.md). O processo separado
`python -m api.reliability --watch` atualiza ontem e hoje; a API publica o resultado
em `GET /reports/reliability/{day}`. Profile Docker opcional: `relatorios`.

Programação oficial por linha e dia, alternativa GTFS e conferência de totais:
[execução e contrato da US04](docs/programacao.md).

O coletor Olho Vivo roda em processo separado, com intervalo configurável,
posições em operação e garagens e persistência no PostgreSQL. Configure
`CHAVE_API_OLHO_VIVO` (ou `OLHOVIVO_TOKEN`) em `apps/api/.env` e consulte
[execução e contrato da coleta](docs/coleta.md).
O serviço Docker é opcional, ativado pelo profile `coleta`.

O coletor GTFS também roda em processo separado: configure `GTFS_SOURCE_URL`, aplique
as migrações e execute `uv run --package amarelo-api python -m api.gtfs --once`.
Sem `--once`, verifica a fonte diariamente e tenta novamente em até cinco minutos
após falhas. Consulte [GTFS: configuração, armazenamento e associação temporal](docs/gtfs.md).
Para um ZIP já baixado, use `uv run --package amarelo-api python -m api.gtfs --file
"caminho/arquivo.zip" --source-id acervo-recebido`; a importação é única e preserva
o original. Identifique a procedência antes de usar esse acervo como programação oficial.
O arquivador da US12 preserva as respostas da inbox no S3 em JSON.gz imutável,
sem bloquear a coleta quando o S3 fica indisponível. Comandos de arquivamento,
importação histórica e proveniência estão no contrato de armazenamento acima.

## Mapa ao vivo (US22)

Configure `OLHO_VIVO_TOKEN` em `apps/api/.env` (modelo em `apps/api/.env.example`). O token nunca vai ao frontend. A API carrega `apps/api/.env` independentemente do diretório de execução; variáveis do processo têm precedência. O Compose injeta esse arquivo opcional e mantém os endereços internos de PostgreSQL/S3. Sem token, a tela informa indisponibilidade, sem dados fictícios.

Execute API e frontend pelos comandos de desenvolvimento acima. O Vite usa a API local na porta 8000; no Compose, `API_PROXY_TARGET` aponta para `http://api:8000`. O mapa não precisa de banco/S3 para esta consulta.

- `GET /vehicles/positions` é público. `line_id` opcional filtra um sentido pelo código interno SPTrans. `lines` mantém o catálogo disponível no snapshot.
- A tela consulta a cada 15 segundos, mostra coleta e GPS separadamente e oculta veículos após 60 segundos sem coleta recente. GPS antigo ou sem horário usa ponto vazado e menor opacidade; não significa viagem cancelada.
- O backend compartilha um snapshot em memória por processo, coalescendo chamadas concorrentes e esperando 15 segundos entre tentativas. Em falha mantém a data original; sem snapshot retorna 503.
- Esta consulta direta é um adaptador para a US22; não implementa histórico, redundância ou persistência da US01. O coletor US01/US29 já existe em processo separado; conectá-lo a este endpoint é uma etapa posterior que deve preservar o contrato. Múltiplos workers exigem cache compartilhado antes de escalar.
- A tela abre na visão geral da rede, com grupos proporcionais de 24–64 px, anéis das cores oficiais presentes e contagem central de posições. Os agrupamentos espaciais (Supercluster) respeitam os filtros e se dividem conforme o zoom; clicar amplia a região. No zoom máximo, veículos coincidentes abrem uma lista paginada de dez itens no painel. Selecionar um ônibus pelo mapa ou pela lista exibe detalhes acima dos filtros, sem popup, com atualização pelo snapshot e aviso se a posição deixar de estar disponível. Filtros por área e seleção acumulativa de linhas permitem comparar ambos os sentidos ou restringir cada linha. O resumo considera os filtros dentro da área visível, enquanto o total da rede fica como referência. A câmera só é enquadrada a pedido do usuário.
- Em **Visualização**, os botões Grupos, Calor e Misto ficam sempre visíveis. No Calor/Misto aparece Intensidade do calor (25–200%, padrão 100%). Em Grupos/Misto, escolha Por quantidade (área proporcional, limitada a 24–64 px) ou Mesmo tamanho (28 px). Em Mais opções ficam a escala geral dos grupos (100–150%, até 96 px), o tamanho dos ônibus (9–18 px) e as fatias por quantidade ou iguais por cor. O padrão dos ônibus é 9 px com e sem filtros. As preferências ficam neste navegador; Restaurar padrões não limpa os filtros. O tamanho visual não altera o agrupamento.
- A densidade usa todas as posições filtradas com peso igual, incluindo GPS antigo ou sem horário. A escala roxa representa concentração relativa, varia com o zoom e a intensidade escolhida e não mede cobertura, demanda ou qualidade. No Misto, a camada tem menor opacidade; percursos permanecem acima dela. O mapa de calor não captura cliques.
- Ao selecionar áreas, os percursos associados no catálogo atual aparecem automaticamente, sem adicionar linhas uma a uma. A visão da área usa traços discretos; clicar num percurso destaca essa linha mantendo o recorte e mostra seus destinos no painel. Selecionar explicitamente linhas/sentidos continua refinando a interseção com as áreas. Sem área ou linha escolhida, a visão geral mantém apenas posições. O catálogo ainda parte de linhas/sentidos observados pelo adaptador Olho Vivo: isso não certifica todas as linhas oficiais ou sua operação atual.
- Percursos carregam progressivamente, com até quatro consultas simultâneas e cache em memória por versão GTFS (até 512 sentidos). Mudar área cancela consultas obsoletas e reutiliza respostas disponíveis; Tentar carregar percursos repete apenas as falhas. Geometria ausente é informada sem impedir o restante do mapa. Enquadrar seleção considera também os percursos disponíveis, mesmo sem posições ou com a coleta expirada/indisponível; sem posições nem geometria, permanece desabilitado.
- Cores vêm do `route_color` do GTFS oficial; a área é identificada apenas quando sua cor tem correspondência comprovada. O mapa lê automaticamente o GTFS já capturado pela US02 no PostgreSQL/S3 e associa os percursos por letreiro completo e destino. A última linha adicionada ganha foco: 5 px e 85% de opacidade, com halo de contraste de 1 px por lado; as demais ficam com 3 px/35%. Destacar todas usa 4 px/75%. Sentido 1 continua contínuo e sentido 2 tracejado. Troque o foco pelo número da linha no painel ou pelo percurso no mapa; trechos compartilhados abrem escolha no painel, sem popup. Foco não altera filtros, câmera nem faz nova consulta de geometria. Sem captura GTFS acessível ou correspondência inequívoca de sentido, as posições continuam funcionando e a tela informa a indisponibilidade. Veja o [contrato de integração](docs/integracoes/rede-us02.md).
- Com percursos disponíveis, o mapa-base usa 72% de opacidade, veículos 60%, grupos 55% e o heatmap metade da opacidade escolhida. As preferências não são regravadas; sem percursos, a aparência normal volta. O veículo individual selecionado permanece destacado.
- GPS recente significa até 60 segundos no relógio de referência da fonte; horário inválido, ausente ou futuro é desconhecido. O percentual usa todos os veículos do recorte como denominador. O índice espacial é reconstruído apenas quando as posições ou os filtros mudam; movimentos e zoom consultam o mesmo índice. Marcadores são reutilizados; detalhes ficam no painel e a lista só é montada quando aberta, em páginas de 100 veículos.
- Leaflet usa os tiles padrão do OpenStreetMap com atribuição visível. O mapa de ruas depende de rede; a lista de posições permanece disponível. Antes de publicar em escala, definir provedor compatível com a política de uso de tiles.

Contrato gerado em OpenAPI e cliente TypeScript conforme os comandos acima. Origem do formato: [documentação SPTrans v2.1](https://www.sptrans.com.br/desenvolvedores/api-do-olho-vivo-guia-de-referencia/documentacao-api/), consultada em 18/11/2026.

### Simulação local da fonte

A fixture em `postman/mocks/olho-vivo` usa dois veículos sintéticos e valida o cookie entre login e posições. Não deve ser apresentada como operação real.

```bash
postman simulation run postman/simulations/live-map.sim.yaml --port 4010 --no-history
```

Para executar a API contra ela, defina no processo `OLHO_VIVO_BASE_URL=http://127.0.0.1:4010/olho-vivo/v2.1` e `OLHO_VIVO_TOKEN=synthetic`. Não use o token real na simulação.

Backup diário, retenção dos sete dumps mais recentes, limpeza segura da inbox e
recuperação em destinos vazios: [backup e restauração](docs/backup-e-restauracao.md).

Download público diário dos brutos em Parquet, dicionário, licença e operação do
publicador: [publicação dos brutos](docs/publicacao-brutos.md).
