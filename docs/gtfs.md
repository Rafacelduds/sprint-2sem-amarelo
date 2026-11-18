# Captura e versionamento GTFS — US02

O módulo `api.gtfs` consulta uma fonte HTTP(S), valida a estrutura básica do ZIP,
preserva os bytes originais em S3 e publica a captura no PostgreSQL. É um processo
separado do servidor FastAPI, sem nova rota HTTP ou mudança no cliente TypeScript.
A associação com posições usa as tabelas da US01; sua integração deve preceder a US02.

## Configuração e execução

Siga a instalação do [README](../README.md) e configure o `.env` privado a partir
de [.env.example](../.env.example). É necessário fornecer `GTFS_SOURCE_URL` com uma
URL autorizada que retorne o ZIP diretamente. Não se pressupõe um endpoint público
sem autenticação: a [área de desenvolvedores da SPTrans](https://www.sptrans.com.br/desenvolvedores)
é a referência para acesso. URL de login/HTML é rejeitada. Cookies ou fluxos de login
interativo não são implementados por este coletor.

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
Como alternativa dentro da imagem da API, depois de construí-la e aplicar as
migrações, execute um container independente (não inicia o servidor HTTP):

```bash
docker compose run --rm --no-deps --env-from-file .env -e PYTHONPATH=/workspace/apps/api/src api .venv/bin/python -m api.gtfs --once
```

Nesse container, mantenha `postgres`/`s3` como hosts. Não há serviço GTFS contínuo
adicionado ao Compose; o comando acima é uma execução pontual.

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
configure `TEST_DATABASE_URL` para PostgreSQL **exclusivo de testes** e
`TEST_S3_ENDPOINT_URL` para S3 local. Os testes criam/removem schemas e buckets com
nomes aleatórios; nunca aponte essas variáveis para produção. A CI fornece ambos.
Sem essas variáveis, os testes de integração são marcados como ignorados.

Para validar a reversibilidade da migração em banco descartável:

```bash
uv run --package amarelo-api alembic -c apps/api/alembic.ini upgrade head
uv run --package amarelo-api alembic -c apps/api/alembic.ini check
uv run --package amarelo-api alembic -c apps/api/alembic.ini downgrade -1
uv run --package amarelo-api alembic -c apps/api/alembic.ini upgrade head
```
