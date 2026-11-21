# Captura e versionamento GTFS — US02

O módulo `api.gtfs` consulta uma fonte HTTP(S), valida a estrutura básica do ZIP,
preserva os bytes originais em S3 e publica a captura no PostgreSQL. É um processo
separado do servidor FastAPI, sem nova rota HTTP ou mudança no cliente TypeScript.
A associação com posições usa as tabelas da US01 e preserva a resiliência da US29,
ambas já integradas à `main`. A revisão `20261118_0003` une os dois históricos
publicados de migração; bancos que já aplicaram uma das linhas podem avançar para
o mesmo `head`, sem reescrever versões nem remover posições existentes.

A revisão `20261118_0004` concilia esse histórico com a US12 já integrada,
preservando as revisões publicadas e as tabelas de brutos.

## Configuração e execução

Siga a instalação do [README](../README.md) e configure `.env` a partir
de [.env.example](../.env.example). Para a captura automática, `GTFS_SOURCE_URL`
recebe o link direto do ZIP, não uma página de login nem o caminho do arquivo local:

```dotenv
GTFS_SOURCE_URL=https://www.sptrans.com.br/umbraco/Surface/PerfilDesenvolvedor/BaixarGTFS
```

O endpoint do domínio oficial retornou assinatura ZIP sem autenticação na consulta
de 18/11/2026. A [área de desenvolvedores da SPTrans](https://www.sptrans.com.br/desenvolvedores)
continua sendo a referência para acesso; mudanças na fonte podem exigir nova
configuração. URLs de login/HTML são rejeitadas. Cookies ou fluxos de login interativo
não são implementados por este coletor.

Configure `DATABASE_URL` e as variáveis `S3_*` para serviços acessíveis pelo processo.
Ao executar pelo host, use `localhost` em vez dos nomes Docker `postgres` e `s3`.
O bucket precisa existir; o setup LocalStack do projeto o inicializa.

Na raiz do repositório:

```bash
uv run --package amarelo-api alembic -c apps/api/alembic.ini upgrade head
uv run --package amarelo-api python -m api.gtfs --once
```

`--once` retorna código 0 após preservar e catalogar a captura, ou 1 em caso de
falha. Para execução contínua, remova `--once`; o primeiro ciclo é imediato.
O processo precisa permanecer ativo e deve ser supervisionado na hospedagem.

### ZIP já baixado

Para uma carga inicial ou material recebido, sem precisar de URL nem fazer download:

```bash
uv run --package amarelo-api python -m api.gtfs --file "caminho/arquivo.zip" --source-id acervo-recebido
```

O comando importa uma única vez, mesmo sem `--once`, usando os mesmos limites,
validação, hash, S3 e catálogo da captura HTTP. Trabalha sobre uma cópia temporária;
o original permanece intacto. `--source-id` substitui `GTFS_SOURCE_ID` só nessa execução.
Use um identificador coerente com a procedência; o exemplo não mistura automaticamente
o arquivo recebido com a fonte `sptrans` usada pelas posições.

No catálogo, a origem local aparece como `file://imported/<nome-do-zip>`, sem diretórios
pessoais. `captured_at` é o instante de importação, não a data desconhecida em que o
arquivo foi originalmente baixado ou publicado. A importação não substitui a
verificação periódica da fonte para detectar novas versões.

### Execução em container

Como alternativa dentro da imagem da API, depois de construí-la e aplicar as
migrações, execute um container independente (não inicia o servidor HTTP):

```bash
docker compose run --rm --no-deps -e PYTHONPATH=/workspace/apps/api/src api .venv/bin/python -m api.gtfs --once
```

O Compose já fornece os hosts internos `postgres`/`s3`; o comando acima é pontual.
Para captura contínua separada da API, o profile `gtfs` faz a primeira captura
imediatamente e repete a cada `GTFS_INTERVAL_SECONDS` (padrão diário), com
retentativa após falha. Depois de configurar o `.env` da raiz:

```bash
docker compose --profile gtfs up --build -d gtfs
```

O profile é opcional; iniciar somente API/web não ativa coleta GTFS. Para uma
captura pontual com a mesma configuração: substitua `up --build -d gtfs` por
`run --rm gtfs .venv/bin/python -m api.gtfs --once`. O serviço usa o mesmo bucket,
banco e fonte das posições. Não confundir `localhost` do host com os nomes
`postgres`/`s3` dentro dos containers. No frontend Docker, prefira `VITE_API_URL=/api`.
Não é necessário sobrescrever URLs ao trocar entre host e Docker: o Compose
usa seus destinos internos. Sobrescritas opcionais `COMPOSE_*` estão no README.
Os scripts `.sh` precisam de LF,
definido em `.gitattributes`: CRLF impede `init-s3.sh` de criar o bucket no Linux.
Se o LocalStack já iniciou com esse erro, normalize o arquivo para LF e execute
`docker compose exec s3 bash /etc/localstack/init/ready.d/init-s3.sh`, sem remover
volumes nem objetos existentes.
O serviço `collector` (Olho Vivo) recebe `GTFS_SOURCE_ID` pelo ambiente do Compose,
com padrão `sptrans`. Ao adotar outra fonte como referência para posições, use o
mesmo identificador na captura GTFS e nesse serviço para que o vínculo seja encontrado.

## Referência visível no produto

Continuação [US02 — GTFS persistido no produto](https://trello.com/c/8vTAQRoY).
O mapa deve ler a referência persistida após reinício e mostrar, em **Legenda e
fontes**, URL/procedência, instante de captura em `America/Sao_Paulo` e SHA-256
completo. Captura não comprova vigência histórica. As associações continuam
exigindo letreiro e destino conforme o [contrato de rede](integracoes/rede-us02.md).
Sem GTFS ou após falha de consulta do catálogo, a tela retira as associações
anteriores e informa indisponibilidade, preservando posições disponíveis. A
legenda permite rolagem em telas pequenas. Pintura/filtros dos percursos seguem
na task US22 vinculada; não são ampliados por esta continuação.

| Variável | Padrão e comportamento |
| --- | --- |
| `GTFS_SOURCE_ID` | `sptrans`; identificador estável da fonte, também usado pela coleta Olho Vivo |
| `GTFS_INTERVAL_SECONDS` | `86400`; entre inícios dos ciclos; intervalo de 60 s a sete dias |
| `GTFS_FAILURE_INTERVAL_SECONDS` | `300`; próxima execução após falha, limitada também pelo intervalo principal |
| `GTFS_TIMEOUT_SECONDS` | `60`; timeout de operações HTTP, até 120 s |
| `GTFS_ATTEMPTS` | `3`; tentativas para erros de transporte, HTTP 429 e 5xx; espera de 1, 2, 4… segundos |
| `GTFS_MAX_BYTES` | `268435456`; limite do download, processado em blocos para arquivo temporário |
| `GTFS_MAX_EXPANDED_BYTES` | `4294967296`; limite da soma dos tamanhos declarados dos membros ZIP |

Os critérios originais da [história](https://trello.com/c/ueJSVg9W) continuam diários
e com captura em até 24 h; a opção semanal está disponível tecnicamente, mas depende
de decisão do PO. Um processo parado ou uma fonte indisponível não assegura esse
prazo. A execução local dos testes não comprova disponibilidade contínua em produção.
URLs completas e exceções das bibliotecas não aparecem nos logs; no catálogo a URL
é registrada sem usuário, senha, query string ou fragmento.

## Preservação e catálogo

- Objeto S3: `gtfs/<source_id>/<sha256>.zip`. SHA-256 é calculado sobre o ZIP recebido,
  incluindo seus metadados internos; recompacotar o mesmo conteúdo gera outra versão.
- A gravação usa `If-None-Match: *`. Se o objeto já existir, verifica tamanho e hash
  no metadata. Conflitos são erros; o coletor não apaga nem sobrescreve o objeto.
  Permissões de bucket/Object Lock e backups continuam sendo configuração operacional.
- `gtfs_versions`: hash, tamanho, bucket/chave, cobertura e versão declarada pelo
  publicador, quando disponível. A identidade da versão é o hash, não `feed_version`.
- `gtfs_captures`: fonte, URL sanitizada, captura em UTC e hash da versão. Verificações
  repetidas registram novas capturas sem duplicar a versão. Uma sequência A → B → A
  mantém sua ordem temporal.
- O objeto é salvo antes da transação do catálogo. Falha no S3 não publica captura;
  falha no PostgreSQL pode deixar um objeto sem catálogo. Reexecutar reaproveita esse
  objeto; ele nunca é apagado automaticamente como compensação.

Não são extraídos nem regravados os arquivos originais. A validação confere arquivos
e colunas essenciais, presença de calendário, datas de cobertura e CRC. Rejeita ZIP
inválido, arquivos criptografados, nomes duplicados e caminhos internos. Não é um
validador semântico completo de GTFS: por exemplo, referências entre viagens e
paradas precisam de validação própria antes de indicadores. Limites de CPU/disco
do processo continuam necessários para fontes não confiáveis.

## Vínculo das posições à referência GTFS

`vehicle_positions.gtfs_version_sha256` é uma FK para o catálogo. O coletor Olho Vivo
resolve a referência por dia civil do horário GPS em `America/Sao_Paulo`, escolhendo
a captura mais recente da fonte configurada, já conhecida no horário de coleta,
cuja cobertura inclui esse dia. A resolução ocorre uma vez por dia distinto em
cada resposta; não há consulta por veículo. Os dados e o vínculo são gravados na
mesma transação. A deduplicação existente preserva o vínculo da primeira gravação.

A cobertura é inclusiva: usa `feed_start_date`/`feed_end_date` quando ambos existem
em `feed_info.txt` (`coverage_basis=feed_info`); caso contrário, usa a extensão de
datas de `calendar.txt` e das inclusões de `calendar_dates.txt`
(`coverage_basis=calendar_extent`). A regra segue a [referência GTFS Schedule](https://gtfs.org/documentation/schedule/reference/)
para identificar esses campos. A extensão dos calendários é uma inferência de
cobertura; não comprova vigência oficial, nem que uma linha opere em cada data.

`gtfs_link_status` distingue:

| Estado | Significado |
| --- | --- |
| `matched` | Referência selecionada segundo a política acima |
| `missing_gps_time` | Horário GPS ausente; hash nulo |
| `no_gtfs_for_date` | Sem captura anterior compatível com o dia; hash nulo |
| `not_evaluated` | Posição já existente antes da migração; hash nulo |

Não há preenchimento retroativo por suposição. A política temporal é uma proposta
para revisão: não reconstrói o instante de publicação da fonte, não certifica o
GTFS histórico de maio e não define o corte de dia operacional para viagens após
meia-noite. A aprovação dessa política e a validação da fonte real continuam necessárias
antes de declarar todas as observações vinculadas à programação efetivamente vigente.

## Verificação reproduzível

Os testes usam um GTFS pequeno e sintético criado em Python, sem dados recebidos do
cliente. O teste integrado sobe uma fonte HTTP local que responde 503 uma vez e
depois serve o ZIP; executa o coletor real e verifica os bytes no S3 e as capturas
no PostgreSQL. A fonte sintética testa recuperação e persistência, não autenticação
nem comportamento da SPTrans. Não há dependência de workspace ou mock publicado
do Postman; o cenário local está em `test_gtfs_integration.py`.

Além dos comandos de qualidade do README, para executar os testes de integração,
configure `TEST_DATABASE_URL` para PostgreSQL **exclusivo de testes**, com permissão
de criar databases descartáveis para os testes de migração, e
`TEST_S3_ENDPOINT_URL` para S3 local. Os testes criam/removem schemas e buckets com
nomes aleatórios; nunca aponte essas variáveis para produção. A CI fornece ambos.
Sem essas variáveis, os testes de integração são marcados como ignorados.

Os testes de migração partem tanto de `7ad978e014e5` (US29) quanto de
`20261118_0002` (US02), avançam para o head único `20261118_0003` e verificam que
posições existentes continuam preservadas. Outro teste combina retentativa de
garagem, persistência real, deduplicação e vínculo GTFS na mesma execução.

Em 18/11/2026, o CLI foi executado contra o download real da SPTrans e contra um
ZIP baixado por Pedro, usando somente PostgreSQL e S3 descartáveis. Ambos retornaram
código 0; os objetos preservados tinham 14.326.297 bytes e SHA-256
`3141809bcbb8c1677244bd3e4499faa612857d9685d056317b137dc1d0195655`, igual ao arquivo
local, que permaneceu intacto. As duas capturas foram catalogadas; isso valida
captura e preservação naquela execução, não disponibilidade contínua nem vigência
oficial de cada linha/data. O arquivo informa extensão de calendários de
01/10/2023 a 01/06/2027, marcada como `calendar_extent`, sem `feed_version` declarado.

Para validar a reversibilidade da migração em banco descartável:

```bash
uv run --package amarelo-api alembic -c apps/api/alembic.ini upgrade head
uv run --package amarelo-api alembic -c apps/api/alembic.ini check
uv run --package amarelo-api alembic -c apps/api/alembic.ini downgrade 34bf95c97f11
uv run --package amarelo-api alembic -c apps/api/alembic.ini upgrade head
```

Essa reversão remove as extensões GTFS e de alerta da US29 no banco descartável,
mantendo a base operacional da US01. A revisão de merge em si não altera tabelas;
recuar apenas uma revisão a partir dela não testa a remoção das extensões.
