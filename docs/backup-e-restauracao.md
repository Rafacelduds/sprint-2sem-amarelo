# Backup e restauração

Implementação da [US32](https://trello.com/c/P5y56tPC), dependente da US12.
Usa PostgreSQL 16, Python/boto3 e S3 já presentes no projeto. Não exige uma
segunda EC2 permanente. AWS ainda depende de liberação de recursos.

## O que é protegido

O backup copia brutos, manifestos e derivados existentes e gera um dump consistente
do PostgreSQL. Os objetos são imutáveis e conferidos por SHA-256, inclusive depois
da cópia. A listagem ocorre após o snapshot do dump e inclui as referências exatas
do catálogo, que é append-only. Falha interrompe a criação do ponto de recuperação;
uploads incompletos não autorizam limpeza da inbox.

Uma execução gera `backups/database/<uuid>.dump` e
`backups/runs/<uuid>.json`. O manifesto relaciona objetos originais e cópias,
versões, hashes, commit do código e revisão Alembic. O banco registra o ponto
somente depois de verificar o manifesto no backup.

As referências são identificadas pela tupla bucket, chave e versão. Depois de
uma restauração, aliases originais e físicos continuam no manifesto seguinte,
mesmo quando apontam para uma única cópia dos mesmos bytes. Os recibos de limpeza
usam a identidade original do catálogo. Conteúdos divergentes sob a mesma chave
interrompem o backup, em vez de produzir um ponto de recuperação ambíguo.

O agendamento é diário às 03:00 UTC (00:00 em São Paulo nesta data).
Ao iniciar, faz uma execução se não existir backup do período vencido. Falhas
são registradas sem credenciais e tentadas novamente após cinco minutos.
Um advisory lock impede dois jobs no mesmo banco. Em funcionamento normal,
a janela de perda corresponde ao último backup concluído, de até cerca de um dia;
falhas prolongadas podem aumentá-la e devem ser acompanhadas nos logs.

Mantém sete pontos completos bem-sucedidos do banco. Depois de confirmar um novo,
exclui somente dumps e manifestos de recuperação antigos; os brutos e manifestos
de processamento ficam preservados durante o projeto. O usuário do job deve poder
excluir versões somente em `backups/database/` e `backups/runs/`.

## Operar

### Painel de operação

A navegação **Backups · equipe** (`#backups`) reutiliza a aplicação que contém os
[downloads da US09](publicacao-brutos.md). A tela só consulta dados: não executa
backup, não disponibiliza dumps e não inicia restauração.

Configure uma chave aleatória longa em `OPERATIONS_TOKEN`, somente no ambiente
privado da API, e reinicie a API. Informe essa chave no formulário do painel.
Sem configuração, chave incorreta ou ausência de autenticação, a API responde
401 antes de consultar o banco. Nunca configure essa chave em `VITE_*`, URL,
Git, imagem ou arquivo público. Fora de localhost, exija HTTPS e restrição de
rede da operação. Esta solução usa uma chave compartilhada de leitura para o time;
não implementa contas individuais, auditoria por pessoa ou autenticação corporativa.

A chave permanece apenas em memória na tela. Sair da página, recarregar ou
**Encerrar acesso** exige informá-la novamente. Não é gravada em cookies,
localStorage ou sessionStorage. O formulário vazio faz parte da navegação pública;
as informações operacionais ficam em `GET /operations/backups`, protegido por
Bearer e com `Cache-Control: no-store`. A resposta usa uma lista explícita de
campos e não inclui buckets, chaves internas, endpoints, credenciais nem links
para dumps. O contrato e o cliente TypeScript são gerados normalmente.

Antes de iniciar o job atualizado, aplique as migrações até `20261120_0011`.
A `20261120_0010` acrescenta `backup_worker` e `backup_attempts`, preservando os
pontos anteriores; a `20261120_0011` permite desativar o heartbeat sem perder uma
tentativa reagendada. O downgrade desta última é recusado enquanto houver retry
pendente numa rotina parada, evitando descartar a agenda silenciosamente. O processo
`watch` registra heartbeat a cada 30 segundos; a consulta considera o sinal recente
por até 120 segundos. Parada abrupta pode levar até esse limite para aparecer como
inativa. Falhas transitórias do heartbeat são tentadas novamente no próximo intervalo,
sem registrar detalhes privados da exceção. O encerramento normal desativa o sinal
e preserva o reagendamento. Existência de um
backup antigo, API respondendo e contagem de objetos não são provas de rotina ativa.

As tentativas de `run` e `watch` são registradas com início, fim, resultado e vínculo
com o ponto somente depois do retorno do serviço. Falhas persistem sem mensagens
internas ou argumentos de conexão. Ao obter o lock exclusivo, o job identifica como
falhas as tentativas que ficaram sem conclusão após uma interrupção. Comandos
pontuais não anunciam rotina diária ativa. O próximo horário usa o mesmo corte
das 03:00 UTC do job; falhas do `watch` exibem a próxima tentativa em cinco minutos.
Sem sinal recente, a tela não promete uma próxima execução.

O reagendamento pendente tem precedência sobre o corte diário: é respeitado mesmo
quando o ponto foi catalogado antes de uma falha de limpeza/retenção. O reinício
conserva essa pendência, aguarda seu horário e só a limpa após uma execução completa
bem-sucedida. Um retry pode criar outro ponto válido no mesmo período. Os testes
do agendador exercitam falha pós-catálogo, retomada, espera e encerramento normal.

O painel mostra os últimos 20 pontos e tentativas, última consulta, último ponto
concluído, agenda, atraso, hashes e expiração. Um ponto criado com a nova
instrumentação pode indicar integridade verificada **na criação**; os registros
históricos não recebem esse selo retroativamente. Não há verificação remota de
bytes durante a consulta nem promessa de disponibilidade atual ou restauração
testada. Uma falha de limpeza/retenção após catalogar um ponto continua sendo
tentativa malsucedida; o ponto catalogado permanece separado dessa tentativa.

A atualização é manual. Consulta falha, acesso recusado, ausência de pontos,
tentativa malsucedida e rotina sem sinal são estados distintos. Evidência real,
incluindo backup do Parquet da US09 e reinício da API, em
[ensaio do painel](evidencias/2026-11-20-us32-painel.md).

Configure `.env` pelo exemplo. Para comandos Python no host use
`localhost:4566` no S3 principal, `localhost:4567` no backup e o host local no
`DATABASE_URL`. O código não registra URLs de conexão nem credenciais.

```bash
docker compose --profile backup up -d postgres s3 s3-backup
uv run --package amarelo-api alembic -c apps/api/alembic.ini upgrade head
uv run --package amarelo-api python -m api.backup init
export APP_CODE_VERSION=$(git rev-parse HEAD)
uv run --package amarelo-api python -m api.backup run
uv run --package amarelo-api python -m api.backup watch
```

Os comandos Python precisam de `pg_dump` e `pg_restore` versão 16 no PATH.
A imagem dedicada já contém os clientes e permite operação sem instalar no host:

```bash
export APP_CODE_VERSION=$(git rev-parse HEAD)
docker compose --profile backup up -d --build backup
docker compose logs -f backup
docker compose run --rm --no-deps backup .venv/bin/python -m api.backup run
```

No desenvolvimento, também é possível usar os clientes do container PostgreSQL:
exporte `PG_TOOLS_CONTAINER=sprint-amarelo-postgres-1` antes dos comandos Python.
Nesse caso, o host visto pelo cliente é `localhost:5432` dentro desse container.
Para outro destino use `PG_TOOLS_HOST` e `PG_TOOLS_PORT`. Essa opção é apenas
conveniência de teste; o job em produção não monta o socket Docker.

## Limpeza automática

Depois do backup, o job confere novamente as versões exatas no principal e no
backup e libera somente `collection_snapshots.body` elegível. Mantém registro,
metadados, posições normalizadas e `body_purged_at` para auditoria.
Qualquer erro de integridade bloqueia essa liberação. A rotina é retomável.

Os bytes ainda não arquivados aguardam no PostgreSQL. As posições normalizadas
também crescem continuamente; medir com `pg_total_relation_size` antes de
dimensionar o RDS. Não se promete que um banco de 20 GB comporte a frota inteira.
Depois de haver corpos nulos, o downgrade da migração exige recuperá-los antes.

## Restaurar em ambiente novo

1. Separar um banco vazio, um bucket vazio e acesso ao bucket de backup.
2. Usar o commit registrado no manifesto e a imagem correspondente.
3. Configurar `RESTORE_DATABASE_URL` privadamente; configurar acesso ao backup.
4. Executar o comando abaixo. Ele recusa banco, bucket ou mapa já ocupados.
5. Configurar a aplicação com banco e bucket restaurados e `S3_RESTORE_MAP`
   apontando ao mapa gerado. Conferir health, contagens, hashes e reprodução.

```bash
uv run --package amarelo-api python -m api.backup restore --manifest-key backups/runs/UUID.json --target-bucket restored-data --target-endpoint http://localhost:4568 --map-output data/restore-map.json
export S3_RESTORE_MAP=/caminho/absoluto/data/restore-map.json
```

O bucket deve ser preparado com versionamento antes. O mapa associa referências
originais às novas versões físicas, permitindo abrir os manifestos originais
sem reescrevê-los. Preserve esse mapa na configuração recuperada; pode ser
reconstruído repetindo o ensaio em outro destino vazio.

O diretório do mapa é criado e uma saída gravável é reservada exclusivamente antes
de copiar objetos ou carregar o banco. O mapa é escrito e sincronizado em arquivo
temporário no mesmo diretório antes do `pg_restore`, e publicado por substituição
atômica após a conferência do banco. Em caso de falha, reserva e temporário são
removidos; mapas já existentes nunca são substituídos.

O Compose monta o arquivo indicado por `S3_RESTORE_MAP` como configuração somente
de leitura na API, arquivador e job de backup. Sem restauração, usa o mapa vazio
versionado em `infra/storage/`. Use caminho absoluto no arquivo de ambiente do host.

O dump recupera o estado consistente de seu início; capturas posteriores ficam
fora daquele ponto. Algumas respostas no dump podem reaparecer com corpo, pois a
limpeza da inbox ocorre depois dele. Isso é esperado e não duplica posições.

Não existe expurgo ou sobrescrita automática do ambiente principal durante um
ensaio. Recuperações parciais que falham exigem outro destino vazio.

## AWS e limites da demonstração

Após a integração da US02, o backup também inclui os ZIPs no namespace `gtfs/`,
respeitando as chaves e metadados já publicados por esse coletor. Seu SHA-256 é
conferido na leitura; a origem não é reescrita. O mapa preserva esses aliases em
restaurações sucessivas. A migração de união `20261118_0005` mantém uma única
head Alembic para US02 e US32, sem reescrever migrações publicadas.

No desenvolvimento são duas instâncias LocalStack com volumes distintos.
É possível desligar o principal no ensaio, mas ambos compartilham a máquina física.
As duas usam `gresau/localstack-persist:3.8.1`, distribuição aberta baseada no
LocalStack 3.8 com persistência. Na imagem Community anterior, `PERSISTENCE=1`
sozinho não implementa a persistência nativa, restrita à edição paga; o ensaio
real de recriação detectou essa limitação antes de concluir a correção.
O [projeto da distribuição](https://github.com/GREsau/localstack-persist/tree/v3.8.1)
é uma dependência de desenvolvimento, com versão fixada e persistência habilitada
somente para S3 (`PERSIST_DEFAULT=0`, `PERSIST_S3=1`). Sua manutenção futura é
limitada; mudança de versão ou substituição exige repetir o ensaio da CI.

Os volumes anteriores `localstack_data` e `backup_data` permanecem declarados,
sem montagem na imagem nova. O estado novo usa volumes exclusivos
`localstack_persisted` e `backup_persisted` montados em `/persisted-data`, com
layout suportado `s3/`. Não há importação automática ou remoção dos dados antigos.
`PERSIST_BASE_DIR` não é suportada nesta versão e foi removida.
Interrompa os produtores de forma controlada antes de atualizar containers.
Não use `down --volumes` no ambiente que contém dados.
Isso não recupera bytes já ausentes nem garante recuperação de encerramento
abrupto; mantenha cópias independentes fora da máquina para dados importantes.

O ensaio `uv run python scripts/check_localstack_persistence.py` usa os dois
serviços S3 da configuração efetiva, mas cria um projeto aleatório com volumes
exclusivos, credenciais de teste e portas locais aleatórias, sem iniciar API,
coletores ou banco. Grava duas versões de um objeto sintético em cada S3,
recria os containers preservando esses volumes e confere VersionId, SHA-256 e
versão atual. Só os recursos desse projeto descartável são removidos ao fim.
A CI executa esse ensaio; `--config-only` permite conferir a configuração sem
daemon Docker. Ele não testa os dados existentes nem durabilidade em AWS.

Em AWS use buckets privados versionados em Virgínia, preferencialmente com o
backup em outra conta. Omita endpoints e chaves de teste e use role IAM com
permissões mínimas; exemplo em `infra/aws/storage-policy.example.json`.
O exemplo é uma política de identidade; acesso entre contas também exige a
política do bucket de destino. Substitua os nomes antes de aplicar.

O bucket de backup inclui também dumps do banco: 100 GB é uma estimativa a
recalibrar com o volume medido, não uma reserva nem garantia de suficiência.

Testes exigem `TEST_DATABASE_URL`, `TEST_S3_ENDPOINT_URL` e
`TEST_BACKUP_S3_ENDPOINT_URL`. O usuário do banco de testes precisa criar bancos
temporários. Eles usam nomes `test_backup_<uuid>`, removidos no encerramento.
A CI fornece PostgreSQL e os dois S3 locais. Usa os clientes versão 16 do próprio
container PostgreSQL, evitando depender da versão disponível no Ubuntu do runner.

O primeiro ensaio e seu tempo são evidência para o volume testado. Agende uma nova
restauração em até seis meses e depois a cada seis meses; a existência do comando
não comprova que o teste periódico foi realizado nem disponibilidade em nuvem.

Primeiro ensaio executado em 18/11/2026:
[resultado e limites](evidencias/2026-11-18-us12-us32.md).
Próximo teste periódico previsto até 18/05/2027, a ser incorporado à operação;
nenhuma automação externa ou evento de calendário foi criado.
