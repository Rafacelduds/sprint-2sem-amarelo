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
| [apps/api/src/api/exports](../apps/api/src/api/exports) | Publicação diária dos brutos e HTTP de download; geração em processo separado |
| [apps/api/migrations](../apps/api/migrations) | Migrações Alembic |
| [apps/api/tests](../apps/api/tests) | Testes da API |
| [apps/web/src](../apps/web/src) | Interface React/TypeScript e seus testes |
| [packages/api-client](../packages/api-client) | Cliente TypeScript gerado do contrato OpenAPI |
| [infra/localstack](../infra/localstack) | Inicialização do bucket S3 local |
| [compose.yaml](../compose.yaml) | Serviços e volumes de desenvolvimento |
| [.github/workflows/ci.yml](../.github/workflows/ci.yml) | Verificações de backend e frontend na CI |

## Contratos e configuração

O contrato HTTP parte dos modelos e rotas da API. Ao alterá-lo, exporte o OpenAPI e regenere o cliente conforme o [README](../README.md#openapi-e-cliente-typescript); não edite manualmente os arquivos gerados. O `openapi.json` é um artefato local ignorado pelo Git.

A configuração única fica no `.env` da raiz, com exemplo em
[`.env.example`](../.env.example). API, coletores, Compose e Vite usam essa fonte;
apenas variáveis `VITE_*` são públicas. Em AWS, o armazenamento aceita a identidade IAM do processo.
Comandos de instalação, migrações e testes ficam centralizados no README.

## Mapa ao vivo — US22

O endpoint público `/vehicles/positions` adapta a resposta do Olho Vivo para um snapshot com `collected_at`, `served_at`, linhas, veículos e horário GPS. O cache de 15 segundos é por processo e não persiste histórico; a integração futura com US01 deve preservar esse contrato. O token fica no backend. Sem resposta inicial há 503; falhas posteriores não renovam artificialmente a data da coleta. Configuração, execução e limites estão no [README](../README.md#mapa-ao-vivo-us22).

O catálogo público `/network/catalog` e a geometria `/network/routes/{line_id}` consomem o GTFS versionado capturado pela US02 no PostgreSQL/S3, com cache derivado de geometrias em SQLite e correspondência explícita por letreiro e destino. Contrato, limitações e fixture em [rede-us02.md](integracoes/rede-us02.md). Uma exportação JSON via `NETWORK_CATALOG_PATH` continua disponível como substituição explícita para testes e integrações específicas.

O mapa usa Supercluster sobre as posições já filtradas, com histogramas de cores em `map/reduce`. Os histogramas são copiados antes da redução para preservar os agregados dos níveis filhos. Anéis representam a proporção de posições ou a presença de cada cor, com centro neutro para a contagem; cores desconhecidas permanecem em cinza. Pan/zoom consultam o mesmo índice; dados, filtros ou catálogo de cores o reconstroem. Preferências de tamanho/composição não alteram o índice. Marcadores e ícones são reutilizados enquanto sua aparência continua igual.

A camada Canvas Leaflet.heat 1.0.1 recebe as mesmas posições filtradas (peso 1), incluindo horários antigos/desconhecidos. Usa raio 25 px, blur 15 px, máximo de intensidade 4 e zoom de referência 15; o controle visual de 25–200% divide esse máximo pelo ganho escolhido, sem mudar as posições nem seus pesos; a legenda informa concentração relativa e dependência do zoom. Panes separam base, densidade (z=340, opacidade inicial 70% ou 48% no Misto, ajustada pela raiz do ganho e limitada a 90%), percursos (350), veículos (450), grupos (460) e destaque selecionado (470). Densidade e destaque não interceptam cliques. Os traçados continuam não interativos no Leaflet; um listener no mapa identifica os percursos próximos ao clique. A integração adapta apenas a tipagem da classe Layer do plugin, cujos tipos distribuídos visam Leaflet 2; o runtime continua no Leaflet 1.9 do projeto.

A seleção de veículo é mantida por ID no React, com informações derivadas do snapshot filtrado atual; posição ausente/expirada recebe aviso. Detalhes e páginas coincidentes usam o painel existente em desktop/celular. No modo Densidade, só o veículo selecionado ganha destaque, e a lista permanece disponível. Não há popup de ônibus sobre o mapa.

Preferências visuais tipadas ficam em localStorage (`observaonibus.map.visual.v1`), sem armazenar filtros, seleção ou coordenadas. Valores inválidos, dados corrompidos ou armazenamento bloqueado mantêm os padrões e o mapa funcionando. A API e seus contratos públicos não mudam nesta evolução.

## Evolução

A US05 acrescenta `python -m api.documents register` e a tabela
`official_documents`, ligada ao catálogo técnico `raw_objects` da US12. Cadastro
controlado preserva o PDF no S3 e metadados documentais no PostgreSQL, com
deduplicação por conteúdo. Oferece listagem paginada em
`/documents`, detalhes em `/documents/{identity}` e original verificado em
`/documents/{identity}/pdf`. A página React `#acervo` usa esse contrato pelo
cliente gerado, com filtros, paginação e procedência; o mapa permanece em
`MapPage.tsx`, acessível por `#mapa`. Não há escrita HTTP. Contrato e limites
em [acervo documental](acervo-documental.md).

A US13 acrescenta `python -m api.reliability`, separado da API, para consolidar
metadados de coleta/GTFS e manifestos de programação em relatórios diários no
PostgreSQL. A rota pública `/reports/reliability/{day}` só lê o derivado publicado.
Regras, configuração e limites em [confiabilidade](confiabilidade.md).

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


### Controles simplificados da visualização

Grupos, Calor e Misto ficam sempre visíveis. Controles contextuais mostram intensidade somente com calor e tamanho por quantidade/uniforme somente com grupos; escala geral, tamanho dos ônibus e composição das cores ficam em Mais opções. O diâmetro proporcional é `clamp(24 * sqrt(contagem / 10), 24, 64)` px, antes da escala visual de 100–150%; dez posições têm 24 px e cem têm 64 px. No modo uniforme, todos têm 28 px antes da escala. O limite evita crescimento ilimitado; tamanhos não devem ser lidos como comparação quantitativa exata fora desse intervalo. Ambos os modos preservam contagens, anéis e agrupamento espacial.

As preferências anteriores são migradas de forma aditiva na mesma chave local: valores existentes são preservados; campos novos ausentes recebem intensidade 100% e tamanho por quantidade. Intensidade e estilo de tamanho também são salvos e restaurados com os padrões.


### Foco dos percursos — US22

A linha completa, com os sentidos filtrados, pode ser focada pelo número no painel ou pelo traçado. Adicionar uma linha escolhe seu foco assim que há geometria; enquanto indisponível, a última seleção com geometria permanece em foco. Remover a linha focada escolhe a última seleção disponível. Destacar todas permanece ativo até uma nova adição ou escolha explícita. Esse estado não é persistido e não muda filtros, câmera, contratos ou pedidos de geometria.

O traçado focado usa 5 px/85%, os demais 3 px/35%, e todos destacados usam 4 px/75%. O halo adiciona somente 1 px por lado, branco para cores escuras e escuro para cores de luminância relativa acima de 0,55; segue o mesmo tracejado do sentido. Percursos sem foco são desenhados primeiro. A geometria GTFS não recebe offsets ou conexões artificiais.

Com qualquer percurso disponível, as opacidades dos panes de base/veículos/grupos ficam em 72%/60%/55%; a opacidade do calor é multiplicada por 0,5, preservando a preferência de intensidade e os pesos observados. O pane do veículo selecionado mantém a aparência normal. Ao retirar todos os percursos disponíveis, as camadas voltam ao padrão.

Segmentos são projetados em pixels e os que estão fora da área visível são descartados; a projeção é atualizada em navegação/zoom/redimensionamento ou mudança dos percursos. O clique testa uma tolerância de 8 px, com descarte por limites antes da distância ao segmento. Sentidos e variantes são deduplicados por linha; percursos encobertos por outro traçado também entram na escolha. Nenhum trecho é criado entre segmentos GTFS separados. Cliques fora da tolerância não mudam o foco. Ônibus e grupos não propagam o clique ao mapa, preservando detalhes e expansão.

Um único candidato recebe foco direto; vários abrem Linhas neste trecho no painel existente. O painel rola e recebe foco de teclado, sem mover a câmera. A seleção de percurso fecha detalhes anteriores de ônibus/grupo; a escolha é descartada ao mudar filtros ou versão do catálogo. Linhas sem geometria não entram nas opções. Geometria ausente mantém os avisos existentes e não aciona suavização das outras camadas.


### Percursos automáticos por área — US22

Se o catálogo GTFS falhar ou informar indisponibilidade, somente o filtro por
área fica suspenso: GPS recente e filtros de linha/sentido continuam funcionando,
sem cores ou percursos não comprovados. A seleção de áreas permanece como
intenção, com aviso, e é retomada quando houver referência disponível; limpar
filtros também remove essa intenção. Sem referência, a opção Área não identificada
fica desabilitada. Falhas não transformam o recorte em zero ônibus.

A tela do mapa ocupa a altura restante de um contêiner flex de `100dvh`, após
a navegação, inclusive quando o menu quebra linhas. O limite de rolagem do
explorador e da legenda é relativo ao mapa; em celular o explorador usa até 44%
da altura disponível. Outras páginas continuam com rolagem normal do documento.

Com áreas selecionadas e sem filtro explícito de linhas, a lista de IDs para percursos vem das associações do catálogo atual nessas áreas. Não depende de haver veículo daquele sentido no recorte visível do mapa. Com linhas/sentidos selecionados, mantém-se a interseção dos filtros; sem área nem linha, não se carrega a rede inteira. A cobertura continua limitada ao catálogo publicado pelo adaptador US02/Olho Vivo, e não deve ser descrita como a totalidade da programação oficial. A categoria Área não identificada não inventa associações; só consulta entradas existentes no catálogo com área desconhecida.

`useNetworkRoutes` limita a quatro requisições simultâneas nos endpoints existentes, publica resultados em lotes de até 100 ms e expõe progresso/falhas. Cache em memória por versão GTFS tem até 512 entradas, com descarte das mais antigas; mudança de versão descarta o cache anterior. Mudanças de filtros abortam consultas antigas e impedem publicação/cache de respostas obsoletas. Retry invalida somente falhas; respostas de outra versão são tratadas como indisponíveis. Resultados mantêm referência estável nas atualizações do relógio para não reconstruir os traçados a cada segundo. A versão e IDs atuais filtram o que pode permanecer desenhado durante uma transição.

A visão inicial da área usa 2,5 px/45%, sem halo. O foco por clique continua sem filtrar veículos/linhas; a linha focada usa 5 px/85% e as demais, nesse contexto, 2,5 px/20%. Destacar todas oferece a apresentação comparativa anterior (4 px/75%). Mudança de áreas sem filtro explícito retorna à visão de conjunto. O foco passa a aceitar todas as linhas com geometria carregada naquele recorte, mesmo sem seleção individual. Destinos dos sentidos focados aparecem no painel, quando disponíveis.

Para a seleção no mapa, a projeção dos traçados utiliza simplificação visual do Leaflet de 1,5 px antes dos testes de proximidade (tolerância 8 px). O GTFS e as geometrias recebidas não são modificados. Não há novo endpoint, nova coleta ou migração nesta evolução.
