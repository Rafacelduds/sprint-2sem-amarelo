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

## Como registrar a próxima

Use ID sequencial e título. Em poucos parágrafos, informe **data e status** (proposta, aprovada, rejeitada ou substituída), **problema**, **escolha e motivo**, **consequências** e **fonte/aprovação** (pessoa, US, PR ou documento). Mencione alternativas apenas quando explicarem uma escolha relevante. Se substituir uma decisão, preserve o registro anterior e vincule a nova.

Propostas aguardando validação devem continuar marcadas como propostas. As pendências iniciais de escopo e indicadores estão em [contexto.md](contexto.md#pendências-que-exigem-confirmação); não há definição de fórmulas ou backlog aprovado implícita nesta estrutura.
