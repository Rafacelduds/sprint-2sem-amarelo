# Armazenamento imutável e proveniência

Contrato implementado da [US12](https://trello.com/c/tHXI3rYq), integrado à inbox
do coletor US01/US29. A aplicação ainda não publica indicadores de negócio.

## Princípios

- Registros recebidos de uma fonte externa são gravados como brutos antes de qualquer
  limpeza, normalização ou enriquecimento.
- Um objeto bruto nunca é atualizado no lugar. Uma nova captura produz um novo objeto.
- Dados brutos e derivados usam namespaces distintos e permissões independentes.
- Todo resultado derivado aponta para as entradas exatas usadas no cálculo e registra
  as versões do código e da regra de negócio.
- Reprocessamentos são dirigidos por um manifesto de entradas, não por uma busca pelo
  arquivo "mais recente".

## Organização dos objetos

O bucket configurado por `S3_BUCKET` usa os seguintes prefixos:

```text
raw/olho-vivo/posicao/<data-UTC>/<snapshot-id>.json.gz
raw/olho-vivo/garagem/<empresa>/<data-UTC>/<snapshot-id>.json.gz
raw/received/<dataset>/<sha256>/<nome-do-arquivo>
derived/<conjunto>/<versao-da-regra>/<versao-do-codigo>/<identificador>.<extensao>
manifests/<processamento>/<identificador-da-execucao>.json
```

- `fonte` identifica o sistema de origem, como `olho-vivo`, `gtfs` ou `programacao`;
- a partição de captura usa `AAAA-MM-DD` em UTC;
- o identificador da captura precisa ser único e estável;
- versões são explícitas e imutáveis. Não usar `latest` em chaves persistidas.

Respostas JSON são comprimidas com gzip determinístico, sem nova serialização.
Descompactar recupera exatamente os bytes recebidos, inclusive campos não modelados.
Parquets históricos são preservados como recebidos. A data de importação no catálogo
não é apresentada como horário de captura desconhecido. Normalização fica em `derived/`.

O componente do nome do arquivo recebido usa codificação percentual UTF-8 na chave
(por exemplo, `gps maio.parquet` vira `gps%20maio.parquet`), também nas retomadas.
Isso não altera os bytes do arquivo. A referência é validada antes do upload.
O script pontual `scripts/consultar_olho_vivo.py --output CAMINHO` aceita caminhos
relativos à pasta atual e absolutos fora do repositório. O resultado informa o
caminho relativo à raiz quando possível e absoluto nos demais casos.

## Gravação de dados brutos

A operação de escrita deve ter semântica de criação:

1. calcular SHA-256 sobre os bytes antes do envio;
2. gravar o objeto somente se a chave ainda não existir;
3. recusar nova criação se a chave já existir, mesmo quando o conteúdo for igual;
4. retornar a chave, o tamanho e o SHA-256 efetivamente armazenados;
5. nunca apagar ou substituir automaticamente um objeto para resolver uma colisão.

O S3 executa a condição atomicamente com `If-None-Match: *`; não se usa HEAD seguido
de PUT como proteção. Em retomadas, o arquivador reconhece um upload anterior apenas
após conferir conteúdo e metadados. Divergência é erro e não é reparada por sobrescrita.

O catálogo `raw_objects` registra tamanho, hashes original e armazenado, encoding,
versão do objeto e vínculo à inbox. Cada objeto bruto carrega metadados de origem:

| Campo | Significado |
| --- | --- |
| `source` | Fonte que forneceu o registro |
| `captured_at` | Instante UTC em que a captura foi feita |
| `sha256` | Hash dos bytes armazenados |
| `content_type` | Tipo de mídia do objeto |
| `schema_version` | Versão do formato esperado, quando houver |

Credenciais, tokens e dados derivados não fazem parte desses metadados.

## Manifesto de processamento

Cada execução que produz dados derivados deve gerar um manifesto imutável com:

- identificador e período da execução;
- nome do conjunto ou indicador produzido;
- URI e SHA-256 de cada entrada bruta;
- versão do código, preferencialmente o commit Git completo;
- versão explícita da regra de negócio;
- URI e SHA-256 de cada saída;
- instantes de início e término e resultado da execução.

`ProcessingManifest` valida versões e referências; `ArchiveService.record` verifica
os arquivos, grava o manifesto imutável e persiste a execução em `processing_runs`.
O manifesto é autocontido; o banco oferece a indexação. Código usa commit Git completo,
não nome de branch. Publicação de indicadores deve chamar essa interface.

## Reprocessamento

Um reprocessamento recebe um manifesto de entradas fechado e usa exatamente as URIs
e os hashes registrados. Antes de calcular, ele confere o SHA-256 de todas as
entradas. A execução falha se um objeto estiver ausente ou tiver conteúdo diferente.

O aceite de "mesmos valores publicados" compara valores de domínio após a ordenação
e a normalização determinísticas definidas por cada indicador. A execução nova
registra suas próprias versões e saídas, sem substituir a execução anterior.

## Limites desta história

- A coleta é a implementação do Kayan. O arquivador consome sua inbox em lotes de dez;
  falha no S3 conserva a pendência no banco. O modo contínuo consulta a cada cinco
  segundos e usa advisory lock para impedir execução duplicada.
- Backup e restauração estão na US32; veja [operação](backup-e-restauracao.md).
- Publicação dos brutos para download pertence à US09.
- Recálculo automático quando chega dado atrasado ou muda uma regra pertence à US20.

## Operação e evidência

Comandos na raiz, depois das migrações. Para executar Python pelo host, configure
os hosts locais em `apps/api/.env`, conforme o README. Em AWS omita endpoint e
chaves explícitas para usar a identidade IAM do processo.

```bash
uv run --package amarelo-api python -m api.storage init
uv run --package amarelo-api python -m api.storage archive
uv run --package amarelo-api python -m api.storage archive --watch
uv run --package amarelo-api python -m api.storage import-history --path /caminho/dos/parquets --dataset gps-maio-2026
uv run --package amarelo-api python -m api.storage inventory --dataset gps-maio-2026 --code-version COMMIT_COMPLETO --period-start 2026-05-01T00:00:00+00:00 --period-end 2026-06-01T00:00:00+00:00
uv run --package amarelo-api python -m api.storage replay-inventory --manifest-key manifests/UUID.json
uv run --package amarelo-api python -m api.storage record-manifest --path manifesto.json
docker compose --env-file apps/api/.env --env-file apps/web/.env --profile arquivo up -d --build archiver
```

`inventory` e `replay-inventory` demonstram uma transformação técnica determinística
de hashes e tamanhos. Não calculam indicadores nem comprovam equivalência de um
indicador publicado. Para esse aceite da US12, integrar o processamento de negócio
e comparar seus valores com as versões e entradas registradas.

Testes de integração exigem `TEST_DATABASE_URL` e `TEST_S3_ENDPOINT_URL` de testes.
Usam schemas e buckets com nomes aleatórios; a CI fornece ambos os serviços.
Os arquivos completos e as capturas permanecem fora do Git.
