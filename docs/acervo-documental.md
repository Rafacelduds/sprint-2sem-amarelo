# Acervo documental — US05

O catálogo reúne documentos de referência e aponta para os PDFs originais,
preservados pelo armazenamento imutável da [US12](armazenamento-e-proveniencia.md).
O cadastro é feito por CLI; a API e a tela oferecem consulta e acesso ao PDF,
sem escrita pública. História e critérios
no [Trello](https://trello.com/c/LsacnkBw).

## Consultar pela interface

Com o projeto iniciado conforme o [README](../README.md), abra
[Acervo documental](http://localhost:5173/#acervo) ou use a navegação no topo do
mapa. A página consome a API real pelo cliente TypeScript gerado.

Escolha o tipo e, se necessário, o período e qual data deve ser usada; clique em
**Aplicar filtros**. O formulário valida intervalos invertidos, e **Limpar**
restaura a consulta sem filtros. A paginação mostra até 20 registros por página;
aplicar filtros reinicia na primeira. Estados de carregamento, falha com nova
tentativa e resultado vazio são exibidos explicitamente. Respostas antigas não
substituem uma consulta posterior quando os filtros mudam.

Cada documento mostra título, categoria, órgão e as duas datas separadamente.
Data documental é exibida sem conversão de fuso; inclusão usa São Paulo.
Campos desconhecidos permanecem identificados. Abra **Procedência e detalhes**
para consultar fonte, ressalvas, nome do arquivo, tamanho e SHA-256. **Abrir PDF**
abre o original pela API em nova aba; indisponibilidade/integridade são tratadas
pelo endpoint, que pode retornar 503 em vez de um PDF. Não há pré-visualização,
edição, upload ou correção de metadados pela tela.

A navegação usa `#mapa` e `#acervo`, com suporte a links diretos e voltar/avançar
do navegador. A página do mapa foi movida para `MapPage.tsx`, preservando seu
comportamento; a coleta visual do mapa não fica ativa enquanto o acervo está
montado. A fonte de indicadores/documentos continua sendo responsabilidade de
quem cataloga, sem assumir vigência a partir da presença na tela.

## Metadados

Cada cadastro recebe um JSON UTF-8, sem campos adicionais:

| Campo | Significado |
| --- | --- |
| `title` | Título do documento, obrigatório, até 500 caracteres |
| `agency` | Órgão emissor confirmado; `null` quando desconhecido, até 300 caracteres |
| `document_type` | `contrato`, `aditivo`, `procedimento` ou `ficha_indicador` |
| `document_date` | Data do documento/versão em `AAAA-MM-DD`; `null` se não identificada |
| `source` | URL ou descrição da procedência, obrigatória, até 2.000 caracteres |
| `notes` | Ressalvas de identificação, versão e procedência; opcional, até 4.000 caracteres |

`catalogued_at` é gerado pelo sistema em UTC na primeira inclusão. Não confundir
essa data com emissão, versão, captura histórica, vigência ou início do prazo de
30 dias. Ausências permanecem nulas, sem usar a data atual como substituição.
O cadastro não verifica se a fonte é oficial nem se o documento está vigente:
essa conferência é responsabilidade de quem prepara os metadados. A URL de fonte
é registrada como texto e não é acessada pela CLI.

## Executar o cadastro

Com PostgreSQL e S3 configurados e dependências instaladas conforme o
[README](../README.md), aplique as migrações e registre um PDF:

```bash
uv run --package amarelo-api alembic -c apps/api/alembic.ini upgrade head
uv run --package amarelo-api python -m api.documents register \
  --file "/caminho/documento.pdf" --metadata "/caminho/metadados.json"
```

Para usar apenas Docker, monte os documentos e metadados em modo somente leitura.
Exemplo PowerShell, executado na raiz do repositório, com arquivos fora do código:

```powershell
$documentos = (Resolve-Path '../Dados_GPS_Onibus/Licitação + Contratos').Path
docker compose --env-file apps/api/.env --env-file apps/web/.env run --rm --no-deps `
  -e PYTHONPATH=/workspace/apps/api/src -v "${documentos}:/input:ro" `
  api .venv/bin/python -m api.documents register `
  --file '/input/IQT.GSO.005.00 - Ficha Técnica do Indicador ICF.pdf' `
  --metadata apps/api/examples/documents/ficha-icf.json
```

O exemplo pressupõe a imagem da API reconstruída com esta implementação e o
banco migrado pelo serviço API. Não inclui os PDFs no Git ou no contexto de build.
Ajuste o caminho da pasta recebida no seu computador. Não colocar credenciais no
JSON. O comando retorna JSON com `created`, ID, metadados, nome original, instante
de cadastro e referência S3 com hash/tamanho/versão; falhas retornam código 1.

Há dois metadados iniciais em [`apps/api/examples/documents`](../apps/api/examples/documents):
`procedimentos-avaliacao.json` corresponde a `ANEXO_III_3_2_PROCEDIMENTO_PARA_AVALIACAO.pdf`;
`ficha-icf.json` corresponde à ficha ICF. Títulos e data de versão ICF foram
conferidos no texto dos PDFs recebidos em 19/11/2026; órgão emissor e data do anexo
ficam explicitamente sem confirmação. Não são cópias dos documentos nem atestados
de vigência; revise os metadados antes de cadastrar em outro ambiente.

## Preservação e repetição

- PDFs passam por checagem básica de assinatura `%PDF-` e marcador final `%%EOF`.
  Isso detecta erros comuns de arquivo/término, sem certificar toda a estrutura,
  assinatura digital ou segurança do conteúdo. Não há interpretação de regras
  contratuais nem extração automática de indicadores.
- Uma cópia temporária em disco estabiliza os bytes durante o cadastro e é
  removida ao terminar. O PDF não é carregado inteiro em memória nem transformado.
- `official_documents` referencia `raw_objects`. A chave S3 é
  `raw/received/official-documents/<sha256>/original.pdf`, com tipo `application/pdf`.
  O nome recebido fica no catálogo. Não criar cópia no repositório.
- Mesmo conteúdo, mesmo conjunto de metadados: retorna `created=false`, preserva
  ID, primeiro nome e data de cadastro, inclusive após renomear o arquivo.
  Campos opcionais omitidos equivalem a `null`; espaços externos são removidos.
- Mesmo conteúdo e metadados diferentes: falha sem editar o registro existente.
  Correção de metadados com histórico é evolução futura; não contornar apagando
  originais. Outro conteúdo gera outro registro, mesmo com título/nome iguais.
- Cadastros concorrentes do mesmo hash usam lock transacional PostgreSQL e
  restrições de unicidade. Upload e banco não formam uma transação distribuída:
  uma interrupção pode deixar um objeto S3 ainda sem catálogo. Repetir o cadastro
  verifica e reutiliza esse objeto; não sobrescreve ou remove automaticamente.
- Falha de integridade no recadastro é erro, sem reparação silenciosa do original.

O prazo de inclusão em até 30 dias ainda exige definir com PO/cliente quando se
inicia a contagem e como identificar documentos novos. Cadastro manual habilita
a operação, mas não comprova monitoramento ou cumprimento contínuo desse prazo.

## Consulta pela API

Com os serviços iniciados, abra http://localhost:8000/docs e procure o grupo
`documents`. Não há autenticação para leitura. Rotas:

| Rota GET | Resultado |
| --- | --- |
| `/documents` | Página com `items`, `total`, `limit` e `offset` |
| `/documents/{identity}` | Metadados, nome original, tamanho, SHA-256 e `pdf_url` |
| `/documents/{identity}/pdf` | PDF original da versão referenciada, exibível no navegador |

Na listagem, os filtros são combinados por **E**:

- `document_type`: uma das quatro categorias do cadastro.
- `date_from` e `date_to`: limites opcionais e inclusivos em `AAAA-MM-DD`.
- `date_field`: `document_date` (padrão) ou `catalogued_at`.
  No primeiro caso, usa a data documental; no segundo, o dia civil do cadastro
  em `America/Sao_Paulo`, embora o instante seja armazenado em UTC.
- `limit`: 1 a 100, padrão 20; `offset`: inteiro não negativo, padrão 0.

Sem intervalo de datas, documentos sem data identificada aparecem normalmente.
Com qualquer limite por `document_date`, os nulos ficam fora do período; não são
tratados como documentos atuais. Para encontrá-los por inclusão, escolha
`date_field=catalogued_at`. Ordem: cadastro mais recente primeiro, com desempate
por ID decrescente para paginação determinística em um catálogo sem alterações.
Inclusões entre requisições podem deslocar páginas baseadas em offset.

Exemplos locais:

- Todos: http://localhost:8000/documents
- Fichas de setembro/2021:
  http://localhost:8000/documents?document_type=ficha_indicador&date_from=2021-09-01&date_to=2021-09-30
- Cadastros de 19/11/2026:
  http://localhost:8000/documents?date_field=catalogued_at&date_from=2026-11-19&date_to=2026-11-19

`pdf_url` é um caminho relativo à raiz da API. Quando consumir pelo proxy do
frontend, prefixe a base `/api`; não é um endereço público do bucket. O cliente
TypeScript gerado inclui os três endpoints, sem expor credenciais/chaves S3.

O PDF é baixado em blocos para um arquivo temporário, com tamanho/hash conferidos
pela US12 antes de enviar a resposta; a versão S3 exata do cadastro é respeitada.
O arquivo temporário é removido ao terminar a resposta, inclusive em falhas.
O download exige espaço temporário e transfere o arquivo inteiro do S3 para
verificar integridade, mesmo se o navegador depois pedir apenas um trecho.
Não há cache ou limite global de concorrência de downloads nesta etapa.

Resultados sem correspondência retornam 200 com lista vazia; ID inexistente, 404;
tipo/data/UUID/paginação inválidos ou período invertido, 422; falha do catálogo,
original ausente ou hash divergente, 503 sem detalhes internos. Metadados podem
continuar disponíveis mesmo quando o original estiver indisponível. O contrato
de leitura não transforma o cadastro em confirmação de vigência ou oficialidade.

## Verificação

Os testes do catálogo usam PostgreSQL/S3 configurados por `TEST_DATABASE_URL` e
`TEST_S3_ENDPOINT_URL`, conforme o padrão dos testes de armazenamento. Criam
schemas e um banco temporário; o usuário de testes precisa permitir criação de
banco. Não apontar para produção. Execute:

```bash
uv run pytest apps/api/tests/test_documents.py apps/api/tests/test_documents_http.py apps/api/tests/test_storage.py
```

A suíte cobre preservação dos bytes, duplicatas renomeadas, conflitos, entradas
inválidas, concorrência, retomada após upload interrompido, CLI real e migração
desde a revisão anterior, incluindo reversão da tabela documental em banco de teste.
Os testes HTTP também exercitam filtros e paginação, datas ausentes, fronteira
de dia de São Paulo, versão original fixada, arquivo corrompido/ausente, limpeza
temporária e indisponibilidade do banco sem expor detalhes de conexão.
Os testes frontend exercitam carregamento, filtros enviados pelo cliente gerado,
paginação, datas/fuso, procedência/link PDF, erros/nova tentativa, respostas
atrasadas e navegação mapa/acervo. Execute `npm test` na raiz do repositório.
