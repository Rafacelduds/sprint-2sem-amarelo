# Como contribuir

Fluxo informado por Victor em 18/11/2026. Backlog e andamento ficam no [Trello do grupo](https://trello.com/b/QAMKiFut/sprint-2-semestre-grupo-amarelo), sem cópia paralela neste diretório.

1. Pegue uma US do backlog e confira critérios de aceite e dependências.
2. Defina suas tasks no Trello, mantendo o vínculo com o ID da US.
3. Implemente na branch da US, escreva/execute testes relevantes e atualize a documentação afetada.
4. Mova as tasks prontas para revisão para **Review**, conforme as listas reais do quadro.
5. Abra o PR da US no GitHub, com link da história e validação executada.
6. Aplique as correções solicitadas por outro desenvolvedor e atualize a validação.
7. Após revisão e integração concluídas por outro desenvolvedor, mova o trabalho concluído para **Done**. Uma história só está concluída com todas as suas tasks prontas; o aceite do PO na review acadêmica continua sendo um registro próprio.

## Branch e PR

**Uma branch e um PR por US.** Sugestão de nome: `us01-descricao-curta`, preservando o ID existente. Revisão, pedidos de correção, merge e fechamento do PR ficam com **outro desenvolvedor**. O autor implementa e responde à revisão.

O PR deve dizer qual problema resolve e qual comportamento entrega, vincular a US e informar testes executados e limitações relevantes. Se uma verificação não foi executada, explique o motivo. Não declare critérios atendidos sem evidência.

Use os comandos de qualidade do [README](../README.md#qualidade) conforme o impacto da alteração. Verificações automáticas estão em [.github/workflows](../.github/workflows); aprovação de CI não substitui revisão nem aceite da US. Alterações só de documentação pedem conferência de fatos, links e diff, sem necessidade de executar testes da aplicação.

## Documentação e processo

Atualize o documento pertinente no mesmo PR; veja o [índice](README.md). Registre escolhas duradouras em [decisoes.md](decisoes.md), com status e aprovação identificados. Todos os cinco membros desenvolvem, inclusive PO e Scrum Master; este fluxo não atribui especializações individuais.

As obrigações de campos dos cartões, WIP e métricas vêm do guia acadêmico citado em [contexto.md](contexto.md). Não deduza prioridades ou limites de WIP a partir de exemplos ou cores sem acordo explícito.

A criação inicial desta estrutura documental teve autorização pontual de Victor para commit e push direto na `main`, sem PR. Essa exceção não muda o fluxo habitual acima.
