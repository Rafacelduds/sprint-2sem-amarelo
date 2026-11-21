# Relatório diário de confiabilidade — US13

## Especificação curta

Publicar, sem login, as lacunas de coleta e as referências GTFS de cada dia civil
de São Paulo. O processo `api.reliability` deriva o relatório dos ciclos US01/US29,
do catálogo US02, dos vínculos já persistidos nas posições e dos manifestos US04.
Não modifica posições, respostas brutas ou versões de origem. A API apenas lê o
último documento publicado no PostgreSQL; não consulta o Olho Vivo nem o S3.

Critérios e andamento: [US13 no Trello](https://trello.com/c/U0lxddQ7).
O relatório identifica início, fim, causa e evidência de cada lacuna, apresenta
períodos de referência GTFS e versões efetivamente utilizadas. Inclui as execuções
de programação encontradas para o dia, com hashes e divergências preservadas.
Manutenção do Olho Vivo nunca é confirmada automaticamente.

## Consulta no produto

A navegação **Confiabilidade**, em `/#confiabilidade`, consulta o derivado público
pelo cliente gerado do OpenAPI. A [continuação frontend da US13](https://trello.com/c/cxOVnRRC)
permite selecionar o dia civil em São Paulo e atualizar a última publicação,
sem iniciar coleta nem recalcular indicadores no navegador. Mostra período com
fim exclusivo, fuso, geração, condição provisória, ciclos registrados, lacunas e
suas evidências, referências GTFS e manifestos de programação disponíveis.

Trocar o dia ou atualizar retira imediatamente os dados anteriores. Consultas
anteriores são canceladas e respostas atrasadas ignoradas. Carregamento, 404
(não publicado), erro de consulta e relatório publicado sem ciclos são estados
distintos. Sem ciclos, a cobertura aparece como **Sem evidência**; ausência de
registro não vira ausência de serviço ou zero falhas operacionais. Sem manifesto
US04, a tela não declara ausência de programação oficial.

O tempo sem lacuna é `(duração analisada − gap_seconds) / duração analisada`;
inclui a interpretação de falhas parciais do derivado, não mede perda de GPS.
O contrato atual não publica uma contagem exata de ciclos esperados sob mudanças
de cadência. A tela identifica como **estimativa** o teto de duração analisada
dividida por `fallback_interval_seconds`. Não compara esse valor diretamente
aos ciclos registrados, que podem ter retentativas/intervalos diferentes.
O intervalo de referência, a quantidade de ciclos históricos sem intervalo e a
tolerância do agendador ficam explícitos. Não há alteração da regra `us13-v1`.

Hashes completos, fonte GTFS, vínculos das observações, execuções de programação,
divergências e limitações permanecem consultáveis em telas pequenas. A tabela
de lacunas tem rolagem horizontal própria, sem alargar a página.

## Executar e consultar

**Limitação observada em 21/11/2026:** o relatório provisório do ambiente local
mostra tempo sem lacunas próximo de zero. A coleta começou às 14:15 e há falhas
parciais de origem em consultas de garagem; as respostas disponíveis continuam
preservadas. Publicar o relatório não comprova operação integral saudável.
Leitura do resultado, evidências e investigação pendente no
[registro da integração](evidencias/2026-11-21-us05.md#confiabilidade-baixa-e-coleta-incompleta--us01us29us13).

Aplique as migrações conforme o README. Configure `DATABASE_URL`, S3 e
`GTFS_SOURCE_ID` como nos coletores existentes. Nenhum token Olho Vivo é necessário.

```bash
# Publicação pontual; sem --day, publica ontem.
uv run --package amarelo-api python -m api.reliability --day 2026-11-19

# Atualiza ontem e hoje a cada 300 s, retomando após falhas.
uv run --package amarelo-api python -m api.reliability --watch
```

`--refresh-seconds` aceita valores a partir de 60 s. `--day` não pode ser combinado
com `--watch`. Para recuperar dias anteriores após uma parada longa, execute cada
dia com `--day`: o modo contínuo atualiza somente ontem e hoje. Pode ser iniciado
com o profile Compose `relatorios`, seguindo os arquivos de ambiente do README:

```bash
docker compose --env-file apps/api/.env --env-file apps/web/.env --profile relatorios up --build -d reliability
```

Esse comando é uma instrução de operação; adicionar o profile não o ativa.
Use `--code-version <SHA completo>` ou `APP_CODE_VERSION` para identificar o código
implantado; sem eles, a proveniência informa explicitamente `working-tree`.

`GET /reports/reliability/2026-11-19` retorna o relatório em JSON público;
404 significa que o dia ainda não foi publicado, 422 indica data inválida e 503
indica indisponibilidade do banco. O contrato completo vem do OpenAPI, e o cliente
TypeScript deve ser regenerado pelo comando do README.

## Regras de leitura

- O período é `[00:00, 00:00 do dia seguinte)` em `America/Sao_Paulo`, convertido
  para instantes com fuso. Hoje termina no instante de geração e é provisório;
  dias futuros são recusados. `generated_at` permite avaliar a idade da publicação.
- Cada ciclo representa seu intervalo configurado, limitado pelo próximo ciclo.
  Novos ciclos guardam `interval_seconds`. Nos antigos, usa-se
  `--legacy-interval` ou `COLLECTION_INTERVAL_SECONDS` (padrão 30 s); essa escolha e
  a quantidade de ciclos sem intervalo ficam explícitas no relatório. Não se
  afirma que a configuração atual era a configuração histórica.
- Até cinco segundos adicionais entre ciclos são tolerados para o agendador.
  Atrasos maiores produzem `no_cycle_record` após o intervalo nominal. Essa é uma
  inferência de ausência de registro; não atribui a causa à API ou ao banco.
- Ciclos `origin_failure`, `storage_failure` e `interrupted` mantêm essas causas.
  Ciclos ainda `running` são `unfinished_cycle`, e estados desconhecidos ficam
  `unknown_cycle_status`. Intervalos contíguos da mesma causa são unidos e cortados
  nos limites do dia. O último ciclo anterior ao dia participa quando o sobrepõe.
  Ciclos com o mesmo agendamento preservam a falha, mesmo que outro ciclo no
  mesmo instante tenha sucesso; armazenamento tem precedência sobre origem,
  interrupção, ciclo não finalizado, estado desconhecido e sucesso.
- Uma falha de origem pode ser parcial, inclusive restrita a uma garagem. Apenas
  nessa categoria, `possible_maintenance=true` sinaliza uma possibilidade sem
  diagnóstico; `maintenance_confirmed` permanece falso. Erros internos, URLs,
  endpoints privados, credenciais e corpos brutos não são publicados.
- `gap_seconds` é duração de intervalos com coleta incompleta ou sem evidência;
  não é percentual de GPS perdido, disponibilidade mensal ou ausência de serviço.

## Versões e publicação

`gtfs_reference_periods` usa exatamente a resolução temporal US02: última captura
da fonte configurada, conhecida no instante inicial do período e com cobertura
de calendário para o dia local. Uma captura intradiária divide os períodos quando
muda o hash elegível; ausência é `null`. Capturas futuras e fontes diferentes não
retroagem. Cobertura do calendário não comprova operação de cada viagem nem
vigência histórica homologada.

`gtfs_used` agrega no banco os hashes e estados de vínculo das posições **pela data
da coleta**, sem carregar GPS em memória. Uma posição pode usar outro dia de
serviço, pois a US02 vincula pelo horário GPS local. O documento mantém essa
distinção em vez de relincar observações antigas.

Os manifestos em `manifests/schedules/` são lidos e verificados por hash no S3;
somente os do `service_date` solicitado entram em `schedule_references`. São
referências de captura, sem inferir vigência entre execuções ou resolver as
divergências de `totalPartidas`. Sem manifesto, o estado é
`no_manifest_for_day`, sem afirmar ausência de programação oficial. A geração
percorre manifestos pequenos, nunca os Parquet GPS; para um histórico grande,
um índice de manifestos será necessário. O mapa US32 é aplicado pelo leitor S3.

A consolidação no banco usa snapshot `REPEATABLE READ`. A publicação de um dia é
atômica; regenerar substitui somente o derivado daquele dia, e uma geração mais
antiga não sobrescreve uma mais nova. Falha de leitura, validação ou persistência
mantém o relatório anterior. Dados tardios exigem regeneração; o modo contínuo
refaz ontem e hoje. O backup do banco US32 inclui os documentos publicados.

## Validação

`apps/api/tests/test_reliability.py` cobre cortes de dia, duração e classificação
de lacunas, intervalos diferentes, tolerância do agendador, ausência completa,
capturas GTFS intradiárias, referência futura recusada, agregação de vínculos,
manifestos US04, publicação atômica, preservação após corrupção e contrato público.
Integrações usam PostgreSQL e S3 de testes, com schemas/buckets próprios e dados
sintéticos. Os testes de migração existentes verificam atualização e reversão
desde as branches publicadas, preservando as observações anteriores.

Os testes não demonstram operação contínua em produção nem confirmam a causa de
uma indisponibilidade real. A regra de cinco segundos e a interpretação de
coleta incompleta permanecem explícitas para revisão técnica e aceite do PO.
