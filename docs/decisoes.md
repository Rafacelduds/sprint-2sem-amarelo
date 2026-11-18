# Decisões

Registre escolhas que afetem várias US, contratos, interpretação de indicadores ou a forma de trabalhar. Não é um diário de commits. A arquitetura existente está em [arquitetura.md](arquitetura.md); sua presença no código não comprova aprovação pelo cliente.

## D001 — Fluxo por história

- **Status:** definido por Victor em 18/11/2026, em orientação direta para o trabalho de implementação.
- **Contexto:** manter vínculo entre planejamento no Trello, implementação e revisão no GitHub.
- **Decisão:** uma branch e um PR por US. Outro desenvolvedor revisa, pede correções, faz merge e fecha o PR. Sequência operacional em [contribuicao.md](contribuicao.md).
- **Consequência:** abrir PR não conclui a entrega; Done aguarda revisão, correções e integração concluídas.

## Como registrar a próxima

Use ID sequencial e título. Em poucos parágrafos, informe **data e status** (proposta, aprovada, rejeitada ou substituída), **problema**, **escolha e motivo**, **consequências** e **fonte/aprovação** (pessoa, US, PR ou documento). Mencione alternativas apenas quando explicarem uma escolha relevante. Se substituir uma decisão, preserve o registro anterior e vincule a nova.

Propostas aguardando validação devem continuar marcadas como propostas. As pendências iniciais de escopo e indicadores estão em [contexto.md](contexto.md#pendências-que-exigem-confirmação); não há definição de fórmulas ou backlog aprovado implícita nesta estrutura.
