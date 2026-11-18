# Decisões

Registre escolhas que afetem várias US, contratos, interpretação de indicadores ou a forma de trabalhar. Não é um diário de commits. A arquitetura existente está em [arquitetura.md](arquitetura.md); sua presença no código não comprova aprovação pelo cliente.

## D001 — Fluxo por história

- **Status:** definido por Victor em 18/11/2026, em orientação direta para o trabalho de implementação.
- **Contexto:** manter vínculo entre planejamento no Trello, implementação e revisão no GitHub.
- **Decisão:** uma branch e um PR por US. Outro desenvolvedor revisa, pede correções, faz merge e fecha o PR. Sequência operacional em [contribuicao.md](contribuicao.md).
- **Consequência:** abrir PR não conclui a entrega; Done aguarda revisão, correções e integração concluídas.

## Como registrar a próxima

### Proposta técnica da US02 — versões e referência temporal

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

### Proposta técnica da US01 — inbox e deduplicação

Em 18/11/2026, a implementação de US01 propõe usar o PostgreSQL existente para ciclos, respostas e posições normalizadas, com uma transação por resposta e unicidade de prefixo/horário GPS. Isso mantém deduplicação entre reinícios e preserva conflitos nas respostas. A inbox é um ponto de integração com a US12, que implementa o acervo imutável no S3, evitando antecipar seu contrato. Campos identificadores ausentes ficam nulos e não são deduplicados por suposição. **Status: proposta implementada para revisão no PR da US01; aprovação de outro dev pendente.**

Use ID sequencial e título. Em poucos parágrafos, informe **data e status** (proposta, aprovada, rejeitada ou substituída), **problema**, **escolha e motivo**, **consequências** e **fonte/aprovação** (pessoa, US, PR ou documento). Mencione alternativas apenas quando explicarem uma escolha relevante. Se substituir uma decisão, preserve o registro anterior e vincule a nova.

Propostas aguardando validação devem continuar marcadas como propostas. As pendências iniciais de escopo e indicadores estão em [contexto.md](contexto.md#pendências-que-exigem-confirmação); não há definição de fórmulas ou backlog aprovado implícita nesta estrutura.
