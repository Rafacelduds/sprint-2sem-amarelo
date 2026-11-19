# Trabalhar com IA no projeto

Antes de editar, o agente precisa entender o resultado esperado, o contexto e como conferir a entrega. O [AGENTS.md](../AGENTS.md) define essa rotina para o repositório; este guia ajuda integrantes a formular pedidos e avaliar a resposta. Origem da melhoria: [cartão de orientações para IA](https://trello.com/c/T908L073), solicitado por Eduardo em 19/11/2026. A revisão deste documento segue o fluxo normal do grupo.

## Do pedido ao plano

O agente deve primeiro consultar o cartão, as instruções, o código e as dependências pertinentes. Não precisa pedir que o usuário repita algo que já está disponível. Um plano curto deve deixar claro o problema, o limite da alteração, a abordagem e a evidência de conclusão.

| Situação | Conduta esperada antes da alteração |
| --- | --- |
| Correção pequena, objetivo e aceite claros | Explicar em uma frase o que será corrigido e como conferir; executar dentro da autorização |
| Vários componentes, migração, contrato ou regra de domínio | Apresentar etapas, dependências, riscos e verificações; preservar invariantes e identificar pontos de integração |
| Lacuna que muda o resultado, o escopo ou o aceite | Consultar fontes e fazer perguntas objetivas sobre o que continuar indefinido; aguardar resposta apenas para a parte dependente |
| Detalhe técnico reversível sem efeito no aceite | Escolher com base nas convenções existentes e tornar a premissa explícita quando relevante |
| Nova informação contradiz o plano | Explicar o conflito e ajustar a abordagem; não ampliar o escopo silenciosamente |

Por exemplo, “deixe mais rápido” não informa qual operação, carga ou tempo importa. “Corrija o link X que aponta para um arquivo removido” pode ser suficiente sem preencher um formulário. Planejamento proporcional evita tanto execução sem entendimento quanto perguntas e documentos que não ajudam a decisão.

## Modelo curto de pedido

Use os campos úteis e links para o que já existe; não é necessário repetir toda a história ou fornecer todos os campos em cada chat.

```text
Tarefa/US: link do cartão; identificar melhoria interna quando não houver US.
Problema e contexto: o que acontece hoje, para quem e em qual cenário.
Resultado esperado: comportamento ou documento que deve existir ao terminar.
Escopo e restrições: o que a tarefa abrange, fontes e decisões a respeitar.
Critérios de aceite: exemplos ou condições observáveis de conclusão.
Validação: como conferir; ambiente/recorte autorizado e limites conhecidos.

Consulte primeiro o contexto do projeto e apresente um plano proporcional antes
de editar. Esclareça lacunas que mudem o resultado e mantenha a tarefa no Trello.
```

Não inclua tokens, senhas, `.env` privados ou cópias desnecessárias de bases. Referencie a configuração esperada e use exemplos sintéticos identificados quando necessário.

## Exemplo de pedido com escopo claro

```text
Tarefa: https://trello.com/c/T908L073 (melhoria interna).
Problema: as instruções de IA já orientam leitura e revisão, mas não explicitam
o planejamento anterior à edição nem como tratar pedidos mal definidos.
Resultado: fluxo curto no AGENTS.md e guia com modelo e exemplos, acessível
pelo índice das docs e pela contribuição.
Escopo: documentação; preservar regras de negócio, fluxo de revisão e contexto
pessoal fora do repositório. Não instalar ferramentas ou alterar a aplicação.
Aceite: diferenciar pedido claro de ambiguidade que afete o resultado; manter
planejamento proporcional e acompanhamento completo no Trello.
Validação: conferir links, coerência e diff; exercitar pedido claro e ambíguo.
```

Uma resposta inicial adequada identifica o cartão e o Git atual, apresenta os documentos que serão alterados e a conferência pretendida. Ela pode seguir com o trabalho autorizado; não precisa aguardar confirmação a cada edição. Não deve aplicar uma solução de negócio à US05 apenas por ela aparecer no contexto do autor.

## Exemplo de pedido que exige esclarecimento

```text
Arrume a pontualidade dos ônibus e publique um painel mostrando quem está errado.
```

Antes de alterar cálculo ou publicar conclusões, o agente precisa identificar a história e o problema observável: corrigir um cálculo, investigar dados ou criar uma visualização são trabalhos diferentes. Deve consultar [contexto](contexto.md) e [dados](dados.md), que registram diferenças entre US16 e a ficha de IPP. Não pode escolher uma tolerância/denominador ou atribuir responsabilidade às empresas sem validação das regras e evidências.

Perguntas úteis após essa consulta seriam: “Qual problema e cartão devemos tratar?” e “Para esse recorte, qual definição foi validada com PO/cliente: a US16 ou a ficha de IPP?”. Enquanto isso, é possível mapear os componentes e fontes existentes em leitura. A parte dependente da definição e a publicação ficam aguardando o esclarecimento e a autorização pertinentes. A pergunta não deve pedir um segredo nem transformar o relato em fato confirmado.

## Durante e depois do trabalho

Siga [Como contribuir](contribuicao.md) para branch, PR e revisão. No Trello, mantenha a tarefa vinculada à US ou ao objetivo interno, responsável, categoria/labels, tamanho estimado, prioridade com origem, datas reais, critérios e evidências. Reutilize tags e tarefas; um rótulo temporário de impedimento deixa de fazer sentido quando a condição termina. Preserve outros integrantes e as convenções atuais do quadro.

O plano detalhado, quando necessário, cabe no cartão ou na descrição do PR. O repositório guarda orientações e decisões reutilizáveis, não uma cópia do backlog. Registre aprendizados duradouros no documento afetado; não é preciso salvar cada comando como contexto.

Na entrega, compare o resultado com os critérios, explique verificações e limites e confira se o Trello reflete o estado real. Código pronto vai para Review; correções voltam a Doing; Done aguarda a revisão e integração aplicáveis. O aceite da história pelo PO é separado. Não apresente resultado de teste relatado por outro integrante como execução própria.

Uma instrução escrita não assegura adesão de todo modelo, ferramenta ou sessão. O grupo deve conferir se o agente consultou o contexto, respeitou o escopo e trouxe evidências; revisão humana e validação do produto continuam necessárias.
