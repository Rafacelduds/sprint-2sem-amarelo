# Decisões

Registre escolhas que afetem várias US, contratos, interpretação de indicadores ou a forma de trabalhar. Não é um diário de commits. A arquitetura existente está em [arquitetura.md](arquitetura.md); sua presença no código não comprova aprovação pelo cliente.

## D001 — Fluxo por história

- **Status:** definido por Victor em 18/11/2026, em orientação direta para o trabalho de implementação.
- **Contexto:** manter vínculo entre planejamento no Trello, implementação e revisão no GitHub.
- **Decisão:** uma branch e um PR por US. Outro desenvolvedor revisa, pede correções, faz merge e fecha o PR. Sequência operacional em [contribuicao.md](contribuicao.md).
- **Consequência:** abrir PR não conclui a entrega; Done aguarda revisão, correções e integração concluídas.

## D002 — Inbox e deduplicação (proposta)

Em 18/11/2026, a implementação de US01 propõe usar o PostgreSQL existente para ciclos, respostas e posições normalizadas, com uma transação por resposta e unicidade de prefixo/horário GPS. Isso mantém deduplicação entre reinícios e preserva conflitos nas respostas. A inbox é um ponto de integração com a US12, que implementa o acervo imutável no S3, evitando antecipar seu contrato. Campos identificadores ausentes ficam nulos e não são deduplicados por suposição. **Status: proposta implementada para revisão no PR da US01; aprovação de outro dev pendente.**

## D003 — Retentativas e estado de falha da coleta (proposta)

Em 18/11/2026, a implementação de US29 propõe repetir apenas consultas pendentes, até cinco vezes, dentro de um orçamento de 50 segundos, preservando o que já foi gravado. Os ciclos persistidos identificam falhas, interrupções e o primeiro ciclo incompleto desde o último sucesso integral. O webhook marca entrega só após resposta 2xx; sua ausência não significa alerta entregue. Victor informou que o canal ainda não existe e pediu preparar um webhook configurável. O lock PostgreSQL evita duas instâncias ativas para o mesmo banco. **Status: implementação para revisão por outro dev; entrega real de alerta e metas operacionais pendentes.** Contrato em [coleta.md](coleta.md).

## D004 — Versões GTFS e referência temporal (proposta)

Em 18/11/2026, a implementação da [US02](https://trello.com/c/ueJSVg9W) propõe
preservar cada ZIP por SHA-256 no S3 e registrar cada captura bem-sucedida no
PostgreSQL, inclusive quando os bytes não mudam. O vínculo das posições usa a
última captura conhecida na coleta cuja cobertura inclui o dia civil do GPS em
São Paulo; a cobertura vinda dos calendários é marcada como inferida. Isso não
certifica a vigência histórica nem substitui o futuro conceito de dia operacional.
Ausências permanecem explícitas. Frequência diária preserva o critério original;
opção semanal continua pendente do PO. **Status: proposta implementada para revisão;
aprovação de outro dev e validação da política temporal pendentes.** O acervo de
respostas Olho Vivo e seu contrato com US12 não são alterados. Detalhes em [gtfs.md](gtfs.md).

## D005 — Programação oficial e divergências de totais

Em 19/11/2026, a implementação da [US04](https://trello.com/c/9bob1kHl) prioriza
os horários publicados na API de itinerários SPTrans e usa GTFS somente quando
a programação oficial não está disponível. Na primeira amostra de 30 linhas,
o campo `totalPartidas` divergiu das listas em oito respostas. Pedro orientou
manter os horários oficiais e sinalizar a divergência; os dois valores são
preservados no relatório, sem substituir o critério acadêmico de concordância.
Naquele momento, tratava-se de orientação de implementação, ainda sem aceite do
PO. O [PR #9](https://github.com/Rafacelduds/sprint-2sem-amarelo/pull/9) foi
posteriormente revisado e integrado.

**Status em 20/11/2026: recorte aceito pelo PO com ressalva.** Pedro reproduziu
a resposta de Victor: “sim, pode aceitar documentando essa ressalva”. A origem
é a mensagem de Victor transmitida por Pedro, registrada na
[US04](https://trello.com/c/9bob1kHl); não houve contato direto do agente com
Victor. O aceite preserva a divergência entre as listas de horários e os totais
declarados da fonte, o critério documental e o resultado factual 22/30. Não
autoriza inventar horários nem declarar `acceptance_30_lines=true`.

Victor também sugeriu indicar divergências na interface quando pertinente.
Essa melhoria está registrada para refinamento na
[US26](https://trello.com/c/Wnb0kTVp), sem condicionar retroativamente o aceite
da US04 nem substituir o critério próprio de falhas de coleta da US26. Frequência
de captura, vigência histórica e corte operacional continuam pendentes.
Contrato em [programacao.md](programacao.md) e detalhes da
[conferência](evidencias/2026-11-19-us04.md).

## Como registrar a próxima

Use ID sequencial e título. Em poucos parágrafos, informe **data e status** (proposta, aprovada, rejeitada ou substituída), **problema**, **escolha e motivo**, **consequências** e **fonte/aprovação** (pessoa, US, PR ou documento). Mencione alternativas apenas quando explicarem uma escolha relevante. Se substituir uma decisão, preserve o registro anterior e vincule a nova.

Propostas aguardando validação devem continuar marcadas como propostas. As pendências iniciais de escopo e indicadores estão em [contexto.md](contexto.md#pendências-que-exigem-confirmação); não há definição de fórmulas ou backlog aprovado implícita nesta estrutura.
