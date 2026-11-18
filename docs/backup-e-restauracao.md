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

Configure `apps/api/.env` pelo exemplo. Para comandos Python no host use
`localhost:4566` no S3 principal, `localhost:4567` no backup e o host local no
`DATABASE_URL`. O código não registra URLs de conexão nem credenciais.

```bash
docker compose --env-file apps/api/.env --env-file apps/web/.env --profile backup up -d postgres s3 s3-backup
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
docker compose --env-file apps/api/.env --env-file apps/web/.env --profile backup up -d --build backup
docker compose logs -f backup
docker compose --env-file apps/api/.env --env-file apps/web/.env run --rm --no-deps backup .venv/bin/python -m api.backup run
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

O dump recupera o estado consistente de seu início; capturas posteriores ficam
fora daquele ponto. Algumas respostas no dump podem reaparecer com corpo, pois a
limpeza da inbox ocorre depois dele. Isso é esperado e não duplica posições.

Não existe expurgo ou sobrescrita automática do ambiente principal durante um
ensaio. Recuperações parciais que falham exigem outro destino vazio.

## AWS e limites da demonstração

No desenvolvimento são duas instâncias LocalStack com volumes distintos.
Isso permite desligar o principal no ensaio, mas compartilham a máquina física.
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
A CI fornece PostgreSQL, os dois S3 locais e clientes PostgreSQL 16.

O primeiro ensaio e seu tempo são evidência para o volume testado. Agende uma nova
restauração em até seis meses e depois a cada seis meses; a existência do comando
não comprova que o teste periódico foi realizado nem disponibilidade em nuvem.
