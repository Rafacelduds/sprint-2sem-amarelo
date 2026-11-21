# Partidas programadas por linha e dia — US04

## Especificação e alcance

História: [US04 no Trello](https://trello.com/c/9bob1kHl). O processo
`python -m api.schedules` captura a programação oficial da SPTrans e produz
partidas por linha e data de referência em Parquet, separado da API HTTP.
Quando a fonte oficial não fornece uma linha/dia, pode usar uma referência
GTFS da US02. Uma linha usa uma fonte inteira, sem misturar sentidos de fontes
diferentes. A consulta pública descrita abaixo lê somente os artefatos publicados.

### Consulta pública — continuação US04

Task: https://trello.com/c/y3dQ2yyL. A tela `/#programacao` seleciona dia,
execução publicada, linha e sentido no sistema da própria fonte. Não coleta
nem recalcula horários ao consultar. O contrato HTTP parte dos modelos FastAPI
e gera o cliente TypeScript:

- `GET /schedules?day=YYYY-MM-DD`: execuções publicadas para o dia, mais recentes
  primeiro, com linhas, estado da fonte, captura, totais declarados/listados,
  hashes e ressalvas. Lista vazia significa nenhuma publicação encontrada.
- `GET /schedules/{run_id}/departures?line=...&direction=...&offset=0&limit=100`:
  partidas do Parquet verificado, na ordem original `source_order`, sem deduplicar
  multiplicidades nem converter `00:xx` em `24:xx`. Sentido é opcional; limite
  de 1–500 registros. Retorna total filtrado e totais por sentido.
  Use `direction=unknown` para sentido GTFS não informado; não se inventa um código.

404 indica execução/linha ausente; 422, filtro inválido; 503, armazenamento,
manifesto ou derivado indisponível/inconsistente. Uma captura com linha
`unavailable` é apresentada como indisponibilidade da fonte registrada, sem
confundir com GTFS conhecido sem partidas (`gtfs_no_departures`). Não se escolhe
automaticamente uma execução antiga quando a mais recente falha ou está incompleta.
O usuário pode selecionar outra execução explicitamente. Filtros/atualização
retiram os resultados anteriores enquanto a nova consulta está pendente.

A leitura confere bytes/hashes antes de publicar partidas e nunca expõe bucket,
chave, credenciais ou erros internos. Nesta versão a busca percorre até 1.000
manifestos de até 8 MiB e aceita derivados de até 128 MiB; exceder os limites
retorna 503. Histórico maior exigirá índice próprio. As rotas são somente leitura
e não alteram o aceite histórico com ressalva (22/30), brutos ou regras temporais.

Para usar uma publicação já preservada em outro bucket/versão, o leitor aplica
o mesmo `S3_RESTORE_MAP` da US32, sem reescrever o manifesto. A chave lógica
continua identificando os bytes originais; o mapa resolve o objeto físico
recuperado e o download confere tamanho e hash. O arquivo do mapa fica no
ambiente, sem credenciais, e não deve ser versionado como dependência pessoal.
No Compose, configure `S3_RESTORE_MAP` com o caminho local do JSON antes de
iniciar/recriar a API; ele será montado no destino já previsto pelo serviço.

O critério documental exige prioridade da fonte oficial, alternativa GTFS e
conferência dos totais em 30 linhas. Em 20/11/2026, Pedro transmitiu o aceite de
Victor (PO) para o recorte da US04 com a ressalva das oito linhas divergentes da
fonte. O aceite não transforma as 22 linhas concordantes em 30 nem altera os
resultados históricos `acceptance_30_lines=false` e `has_discrepancies=true`.
Veja a [conferência e a origem do aceite](evidencias/2026-11-19-us04.md).
Captura diária ou semanal, política de vigência histórica e corte do dia
operacional continuam sujeitos ao PO; essa resposta não define essas regras e
a implementação não instala um agendamento.

Em 21/11/2026, Daniel explicitou a necessidade de atualização automática.
A ausência de agendamento permanece uma lacuna de produto; a frequência e o
calendário ainda precisam ser definidos. A tela consulta uma linha por vez,
mas a carga local atual tem uma amostra de 30 linhas, sem cobertura integral
nem concordância de 100%. A nova captura não substitui a conferência histórica
citada acima. Números e pendências no
[registro da integração](evidencias/2026-11-21-us05.md#cobertura-divergências-e-automação-da-programação--us04).

## Fonte oficial e execução

A [página oficial de itinerários](https://www.sptrans.com.br/itinerarios/linha/)
usa `https://itinerariosapi.sptrans.com.br`. Em 19/11/2026, foram conferidos
`POST /RetornarLinhasTeste` (catálogo com `codigo` e `CdPjOID`) e
`POST /BuscarDetalheLinhaTeste` com `{"codPlanejamento": <CdPjOID>}`.
Os blocos `partidasIda`/`partidasVolta` contêm `tipoDia`, `totalPartidas` e
`horariosProgramados`. O coletor do cliente, no
[commit de referência](https://github.com/gabinete-falzoni/monitoramento-onibus/blob/c969bf1c9d0d271772cd61e9652af2eed59aa339/coleta_horarios_programados/coletar_linhas_sptrans.R),
serviu para localizar o contrato; a implementação do grupo é Python e foi
conferida com a própria fonte.

Configure o S3 conforme o README e aplique as migrações da US02 se consumir seu
catálogo. O bucket precisa existir e ter versionamento habilitado; no ambiente
local, `uv run --package amarelo-api python -m api.storage init` prepara isso.
`SCHEDULE_SOURCE_URL` em `apps/api/.env` permite uma origem de teste. Não use
credenciais reais em simulações.

```bash
# Amostra determinística das primeiras 30 linhas, por código do catálogo.
uv run --package amarelo-api python -m api.schedules --sample 30 --day-type U

# Recorte explícito, com alternativa retirada do catálogo PostgreSQL/S3 da US02.
uv run --package amarelo-api python -m api.schedules --lines 701A-10,7267-10 --day-type U --gtfs-source-id sptrans

# Alternativa usando um ZIP previamente capturado, sem modificar o original.
uv run --package amarelo-api python -m api.schedules --lines 701A-10 --day-type U --gtfs-file referencia.zip
```

`--day-type U|S|D` é obrigatório: o operador confirma a regra aplicável,
inclusive em feriados. Não há inferência automática de feriado ou conversão
automática entre a regra oficial e o calendário GTFS. A data da captura em
`America/Sao_Paulo` é a referência da saída oficial; não se permite retroagir
uma captura atual para representar maio. Captura não comprova vigência histórica.

`--output` aceita um diretório local; cada execução usa UUID próprio.
`--code-version` registra o commit que gerou a saída; o padrão `working-tree`
explicita a ausência dessa identificação. Não apresentar uma execução feita
sobre alterações locais como reprodução de um commit publicado.

As consultas são sequenciais, com pausa de 0,5 s por linha, timeout de 30 s
e até três tentativas para transporte, 429 ou 5xx, com espera crescente.
Respostas têm limite de 8 MiB. Falha ou JSON inválido não vira zero; o relatório
registra a indisponibilidade e a alternativa utilizada. Erro no armazenamento
interrompe a execução. Cada nova execução tem seu próprio manifesto e reutiliza
objetos idênticos sem sobrescrevê-los; não existe retomada por checkpoint.
Saída incompleta retorna código 1; divergência entre o total declarado e os
horários listados retorna código 2, mantendo os horários oficiais e o aviso.
Essa escolha de tratamento foi informada por Pedro em 19/11/2026 e não equivale
ao aceite do PO. Falhas fatais anteriores ao manifesto deixam
os brutos já arquivados e a pasta local para inspeção, sem anunciar sucesso.

## Contrato dos dados

- Brutos JSON originais: `raw/schedules/sptrans/<sha256>.json`.
- ZIP usado como alternativa: `raw/schedules/gtfs/<sha256>.zip`.
- Derivado: `derived/schedules/us04-v1/<sha256>.parquet`.
- Relatório e referências dos objetos: `manifests/schedules/<run_id>.json`.

As escritas reutilizam o contrato imutável da US12 (`IfNoneMatch`, verificação
de hash e retomada somente de conteúdo idêntico). O relatório inclui captura,
data/tipo de dia, versão da regra, referência de código informada, hashes de
entrada/saída, totais declarados por sentido e totais escritos. Divergências
aparecem em `declared_counts_match`, `warning` e `has_discrepancies`;
`official_lines_concordant` separa os casos concordantes dos consultados.
`acceptance_30_lines` permanece falso se houver divergência na amostra.
O catálogo desta
rotina é o manifesto S3; não há tabela nova no PostgreSQL.

O Parquet contém `line`, `direction`, `direction_system`, `service_date`,
`departure_seconds`, `kind`, `source_sha256`, `trip_id` e `source_order`.
`direction_system` distingue sentidos da API de itinerários e do GTFS; nenhum
deles é convertido implicitamente em sentido Olho Vivo. `source_order` preserva
a sequência da fonte. Horários oficiais `00:xx` permanecem assim; não são
transformados em `24:xx` por suposição. Portanto, não há timestamp operacional
de partida homologado nesta versão.

GTFS respeita `calendar.txt`, inclusões/exclusões de `calendar_dates.txt` e o
menor `stop_sequence` por viagem. Viagens com `frequencies.txt` substituem o
horário exemplar de `stop_times`; não o contam novamente. Cada faixa usa
`start_time <= horário < end_time`, sem sobreposição. `exact_times=1` gera
`gtfs_exact`; `0` ou ausente gera **possibilidades estimadas**, marcadas como
`gtfs_frequency_estimate`. A grade começa em `start_time` por convenção desta
regra, sem prometer partida real nesse instante. Sem frequência, o tipo é
`gtfs_fixed`. Horas GTFS acima de 24 são preservadas em segundos.
Referência: [especificação GTFS Schedule](https://gtfs.org/documentation/schedule/reference/),
consultada em 19/11/2026.

Uma linha ausente do GTFS é erro, nunca zero. Uma linha conhecida sem serviço
ativo no calendário resulta em `gtfs_no_departures`, distinguível de
`unavailable`. A cobertura declarada do ZIP precisa conter a data consultada.
Com `--gtfs-source-id`, só se usa versão da US02 conhecida até a consulta,
com hash conferido no S3; a captura anterior também não certifica vigência.
Após restauração pela US32, configure `S3_RESTORE_MAP` conforme o contrato de
[backup e restauração](backup-e-restauracao.md). O catálogo continua apontando
para bucket/chave originais; a US04 resolve esses aliases versionados pelo mapa
antes de acessar o bucket recuperado. Destino, hashes, tamanhos e codificação
devem corresponder ao ZIP catalogado, e o download confere os bytes efetivos.
Sem mapa correspondente, um bucket diferente continua sendo recusado.

## Verificação

Os testes cobrem totais divergentes, horários inválidos, meia-noite, calendários,
exceções, faixas sobrepostas, frequências exatas/estimadas, prioridade oficial,
retentativas, indisponibilidade e falha de armazenamento. O teste integrado usa
HTTP local real, S3 local e Parquet; as fixtures são inteiramente sintéticas.
A regressão de restauração usa catálogo PostgreSQL e ZIP legado da US02 no S3,
copia o objeto para outro bucket e carrega o mapa pela configuração da US32.
Confere a versão física lida, recusa bytes corrompidos e cobre ausência de mapa,
identidade incorreta e divergências de destino, hash, tamanho ou codificação.

```bash
uv run pytest apps/api/tests/test_schedules.py apps/api/tests/test_schedules_restore.py
```

Configure `TEST_S3_ENDPOINT_URL` para executar a integração S3; sem isso, ela é
explicitamente omitida. A conferência real de 30 linhas deve registrar seu
relatório e comparar os campos `totalPartidas` da fonte com a contagem do
Parquet, sem atribuir à contagem uma validação de viagens observadas ou de SLA.
Resultado da primeira validação real e reprodução da auditoria:
[evidências de 19/11/2026](evidencias/2026-11-19-us04.md).
