# Armazenamento imutável e proveniência

Este documento define o contrato inicial da US12. Ele orienta a futura coleta e o
processamento sem definir como o coletor será implementado.

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
raw/<fonte>/<data-de-captura>/<identificador-da-captura>.<extensao>
derived/<conjunto>/<versao-da-regra>/<versao-do-codigo>/<identificador>.<extensao>
manifests/<processamento>/<identificador-da-execucao>.json
```

- `fonte` identifica o sistema de origem, como `olho-vivo`, `gtfs` ou `programacao`;
- `data-de-captura` usa `AAAA-MM-DD` no fuso aplicável à fonte;
- o identificador da captura precisa ser único e estável;
- versões são explícitas e imutáveis. Não usar `latest` em chaves persistidas.

O prefixo `raw/` contém somente a representação recebida da fonte. Conversões de
formato, correções de tipo, deduplicação e particionamento pertencem a `derived/`.

## Gravação de dados brutos

A operação de escrita deve ter semântica de criação:

1. calcular SHA-256 sobre os bytes antes do envio;
2. gravar o objeto somente se a chave ainda não existir;
3. recusar a operação se a chave já existir, mesmo quando o conteúdo for igual;
4. retornar a chave, o tamanho e o SHA-256 efetivamente armazenados;
5. nunca apagar ou substituir automaticamente um objeto para resolver uma colisão.

Cada objeto bruto deve carregar, como metadados ou em um registro de catálogo:

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

O PostgreSQL pode indexar essas informações para consulta, mas o manifesto continua
sendo a referência autocontida do processamento. A estrutura persistida será criada
na task de proveniência da US12.

## Reprocessamento

Um reprocessamento recebe um manifesto de entradas fechado e usa exatamente as URIs
e os hashes registrados. Antes de calcular, ele confere o SHA-256 de todas as
entradas. A execução falha se um objeto estiver ausente ou tiver conteúdo diferente.

O aceite de "mesmos valores publicados" compara valores de domínio após a ordenação
e a normalização determinísticas definidas por cada indicador. A execução nova
registra suas próprias versões e saídas, sem substituir a execução anterior.

## Limites desta história

- A implementação do coletor e sua política de agendamento serão definidas pelo
  Kayan.
- Backup e restauração pertencem à US32.
- Publicação dos brutos para download pertence à US09.
- Recálculo automático quando chega dado atrasado ou muda uma regra pertence à US20.
