# Download diário dos dados brutos

Implementação da [US09](https://trello.com/c/R1IJCY3a), dependente do arquivo
imutável da [US12](armazenamento-e-proveniencia.md). O critério vigente do Trello
é publicar o dia D até 06:00 de D+1. A alternativa semanal/mensal da fonte
acadêmica continua pendente do PO; esta implementação preserva a frequência diária.

## Conteúdo e dicionário

Cada Parquet contém **uma linha por resposta original da API Olho Vivo**,
incluindo operação e garagem, respostas vazias e campos ainda não modelados.
`corpo_original` é BLOB com os bytes JSON originais descomprimidos, sem nova
serialização, limpeza ou deduplicação. A exportação não é uma tabela de posições
normalizadas: o pesquisador decodifica o corpo em UTF-8 e lê o JSON para acessar
linhas e veículos. Isso preserva inclusive observações repetidas e campos extras.

O dicionário executável está em `GET /exports/raw/dictionary` e nos metadados
`data_dictionary` de cada arquivo. Colunas: `captura_id`, `ciclo_id`,
`coletado_em` (TIMESTAMPTZ UTC), `endpoint`, `empresa` (nullable), `fonte`,
`sha256_original` e `corpo_original`.

Nos corpos da fonte, `l` contém linhas e `vs`, veículos; `p` é prefixo, `py`/`px`
são latitude/longitude e `ta` é horário GPS. Campos ausentes continuam ausentes;
não se presume equivalência de sentido com GTFS. Consulte [dados](dados.md).

Os metadados Parquet identificam CC BY 4.0, o endereço da licença, a atribuição
SPTrans/API Olho Vivo e Grupo Amarelo, a fonte original sem credenciais, versão do
esquema, dia e fuso. São incorporados ao arquivo, independentemente do catálogo HTTP.

O dia é **civil em America/Sao_Paulo**, de 00:00 inclusive a 00:00 exclusivo
do dia seguinte, pelo instante **de captura**. Não é dia operacional nem data do
horário GPS. O fuso acompanha as regras históricas, inclusive horário de verão.

## Acesso público

Na aplicação, abra **Dados brutos** (`#dados-brutos`). A tela consulta o catálogo
público, mostra até 31 dias por página e permite escolher um dia realmente
publicado. Antes do download apresenta publicação, prazo da revisão atual,
quantidade de respostas, tamanho, fonte, licença, fuso, cobertura e SHA-256.
O dicionário é consultado na API, independentemente do catálogo.

O download depende de uma ação explícita. A tela trata falhas, permite repetir ou
cancelar e recusa respostas com tipo, tamanho ou ETag divergentes do item
selecionado. Se houver republicação durante a consulta, atualize o catálogo antes
de baixar. A verificação criptográfica dos bytes é feita no servidor; a tela
compara o ETag com o SHA-256 anunciado e o tamanho recebido, sem apresentar essa
comparação como um novo cálculo de hash no navegador. A conclusão informa que o
arquivo foi recebido, sem afirmar que o usuário já o salvou em disco.

Quando `VITE_API_URL` aponta diretamente para uma API em outra origem, configure
essa origem do frontend em `CORS_ORIGINS`. A API expõe `ETag` nas respostas CORS
para permitir a mesma conferência de revisão usada com o proxy; isso não libera
origens fora da lista configurada.

O navegador recebe o arquivo completo como Blob antes de iniciar o salvamento;
considere memória disponível ao baixar dias grandes, especialmente no celular.
O ensaio desta interface usou um arquivo de 416.784 bytes, não um dia completo de
coleta. Para volumes que excedam o navegador, use o endpoint de download com um
cliente que grave diretamente em disco. A interface não altera os limites do
servidor descritos abaixo.

Atualizar a tela apenas consulta o catálogo: não aciona coleta, arquivamento nem
publicação. Arquivo presente não comprova coleta completa. Evidência e limitações
do ensaio com capturas reais em [validação do frontend](evidencias/2026-11-20-us09-frontend.md).

Sem login, na API e na documentação Swagger `/docs`:

| Rota | Resultado |
| --- | --- |
| `GET /exports/raw` | Últimos 31 dias publicados; `limit` entre 1 e 366; `before=AAAA-MM-DD` exclusivo para paginar |
| `GET /exports/raw/dictionary` | Dicionário das colunas |
| `GET /exports/raw/AAAA-MM-DD` | Tamanho, SHA-256, capturas, prazo, publicação e caminho de download |
| `GET /exports/raw/AAAA-MM-DD/download` | Parquet como anexo, ETag SHA-256 e link da licença |

No acesso via Vite, acrescente `/api` às rotas. Exemplo local:

```bash
curl -f http://localhost:8000/exports/raw
curl -f http://localhost:8000/exports/raw/2026-05-18/download -o brutos-2026-05-18.parquet
```

O download verifica o hash antes de enviar o arquivo e respeita o mapa de
restauração da US32. O bucket permanece privado. O catálogo não expõe credenciais,
chaves internas ou URLs assinadas. Dia sem publicação retorna 404; falha de
armazenamento retorna 503 sem corpo Parquet parcial. Cada requisição usa arquivo
temporário em disco e o remove após o envio; dimensione disco e concorrência na
implantação. Esse endpoint não implementa extrações assíncronas da US28.

## Operação automática

Aplique as migrações conforme o README e mantenha coleta e arquivamento ativos.
O publicador roda **em processo separado**, sem trabalho pesado no servidor HTTP:

```bash
uv run --package amarelo-api python -m api.exports --code-version COMMIT_GIT_COMPLETO --watch
```

Ou configure `APP_CODE_VERSION` com o commit completo na configuração usada pelo
Compose e execute:

```bash
docker compose --profile arquivo --profile publicacao up -d --build archiver raw-publisher
```

O código exige 40 caracteres hexadecimais, sem valor presumido. Em produção,
injete o commit da imagem e identidade IAM; endpoint e chaves explícitas são do
ambiente local. O serviço HTTP só lê o que já foi publicado.

A cada cinco minutos, o processo procura **todos os dias encerrados** que têm
capturas inéditas, inclusive dias antigos. Normalmente o dia anterior entra na
primeira verificação após meia-noite; se arquivo, banco ou S3 falhar, permanece
pendente para nova tentativa. Uma falha diária não bloqueia os demais dias.
Advisory lock PostgreSQL impede dois publicadores simultâneos no mesmo banco.
Interrupção do processo libera o lock e o reinício retoma a varredura.

Para publicar/reprocessar um dia específico, inclusive após mudar versão do código:

```bash
uv run --package amarelo-api python -m api.exports --day 2026-05-18 --code-version COMMIT_GIT_COMPLETO
```

O comando pontual falha com saída não zero se houver pendência de arquivamento ou
armazenamento. Dias correntes/futuros são recusados. Sem capturas, não publica um
arquivo vazio que possa ser interpretado como ausência de serviço; o log informa
zero e o HTTP permanece 404. Mudanças de regra/código em dias já publicados exigem
reprocessamento explícito; a varredura automática detecta novas capturas por contagem.

## Integridade e revisões

Todas as capturas selecionadas precisam de referência arquivada da US12. Os bytes
são baixados e verificados um corpo por vez, mesmo se a inbox já tiver sido limpa.
O [escritor incremental PyArrow](https://arrow.apache.org/docs/python/generated/pyarrow.parquet.ParquetWriter.html)
descarrega lotes no Parquet com até 8 MiB de corpos
ou 256 respostas. Uma resposta maior é escrita sozinha. Não há tabela intermediária
acumulando BLOBs do dia; referências, metadados do arquivo, um lote e um corpo
individual ainda ocupam memória, além dos buffers de conversão/compressão.
O orçamento do lote não é limite absoluto de memória do processo. É necessário
disco para o Parquet, o corpo em verificação e os downloads temporários.

O resultado vai para `derived/public-raw/<dia>/<assinatura>.parquet`, com criação
condicional e manifesto de processamento US12 que registra entradas, hashes,
versão do código e regra. Somente após verificar objeto e manifesto uma transação
altera o catálogo público. Falha conserva a revisão anterior; retomadas usam os
mesmos bytes. Capturas tardias geram outra revisão imutável, sem apagar a anterior.

`publicado_no_prazo` compara **a revisão atual** com 06:00 D+1. Republicações
tardias aparecem como fora do prazo, mesmo se uma revisão anterior saiu no prazo.
O total é de respostas, não de veículos ou viagens. Publicação não comprova
cobertura integral da coleta; a US13 trata do relatório de confiabilidade.

## Alcance da validação

Testes usam respostas sintéticas e serviços descartáveis; não consultam a SPTrans
nem publicam os arquivos recebidos do cliente. O acervo histórico importado em
`raw/received/` continua preservado e não é misturado automaticamente a capturas
da plataforma: nele, instante de captura e esquema têm procedência distinta.

O processo e a verificação do prazo estão implementados. Disponibilidade pública,
volume real e cumprimento diário até 06:00 dependem de implantação, serviços
ativos e observação operacional; testes locais não constituem esse aceite.
