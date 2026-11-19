# Conferência das orientações de planejamento com IA

Conferência feita pelo autor da alteração em 19/11/2026 para o [cartão de melhoria interna](https://trello.com/c/T908L073). Escopo: [AGENTS.md](../../AGENTS.md), [guia de trabalho com IA](../trabalho-com-ia.md), índice da documentação e contribuição. Nenhuma alteração de aplicação, configuração, dependência ou regra de negócio foi necessária.

## Verificações documentais

- Leitura das instruções e docs atuais na base `0d32192d7e436449343e1adc4b8eb696c5dabc06`, com checkout inicialmente limpo e branch própria.
- Plano de escopo e validação apresentado antes das edições e registrado no cartão.
- Conferência dos destinos locais e âncoras Markdown nos documentos alterados, incluindo arquivos novos; referências de contexto, dados, arquitetura e contribuição resolvidas.
- Revisão do diff e de espaços em branco, sem alterações fora do escopo documental.
- Preservação de uma branch/PR por US, revisão independente, fontes e incertezas, proteção dos dados, Trello como andamento e relato honesto de verificações.

## Exercício de pedido claro

**Entrada:** pedido preenchido do guia para esta melhoria interna: fluxo curto de planejamento, modelo e exemplos, documentação apenas, links/coerência/diff e dois cenários como validação.

**Resultado esperado:** consultar cartão e Git, apresentar plano delimitado, executar as edições autorizadas e conferir a documentação, sem exigir confirmação para cada arquivo ou iniciar outra US.

**Resposta exercitada:** “Vou conferir o cartão e as instruções atuais, ajustar AGENTS.md e criar o guia, vinculá-lo ao índice e à contribuição; depois conferir links, diff e os dois cenários. O escopo é documental, sem mudar a aplicação.”

**Conferência:** a implementação desta tarefa seguiu essa sequência. O Trello registrou início e plano, e o diff ficou nos documentos indicados e neste registro de evidência. Não houve implementação da US05, instalação de dependências do projeto ou alteração de critérios de negócio. A conclusão do cartão continua dependendo de revisão e integração independentes.

## Exercício de pedido ambíguo

**Entrada:** “Arrume a pontualidade dos ônibus e publique um painel mostrando quem está errado.”

**Resultado esperado:** identificar a lacuna de problema/US e a diferença documental entre US16 e IPP; não escolher fórmula nem publicar conclusões por suposição. Prosseguir somente com leitura e mapeamento independentes da definição.

**Resposta exercitada:** “Vou consultar o contexto e as fontes em leitura. Qual problema observável e cartão devemos tratar: cálculo, dados ou visualização? A documentação distingue US16 da ficha IPP; qual definição foi validada para o recorte? O cálculo e a publicação dependem dessas definições e das evidências.”

**Conferência:** o [contexto existente](../contexto.md#pendências-que-exigem-confirmação) registra a divergência. As orientações novas encaminham a esse material e exigem esclarecer o resultado antes da parte dependente; a resposta exercitada não inventa parâmetros, responsáveis ou aceite. Nenhuma fórmula, coleta, dado ou painel foi modificado para esse cenário.

## Limites da conferência

Os dois cenários são exercícios de mesa redigidos e conferidos pelo próprio autor, não uma avaliação independente ou uma execução de outro agente/modelo. Verificam clareza e coerência das instruções e não medem taxa de adesão nem garantem comportamento futuro. O revisor deve avaliar também se o nível de planejamento é proporcional e se os exemplos preservam a autonomia autorizada.

Não foram executadas suítes de backend/frontend, benchmark ou deploy: o diff é apenas documental e o [fluxo de contribuição](../contribuicao.md) prevê essa validação proporcional. CI, revisão e integração do PR devem ser verificadas separadamente; este registro não as declara concluídas.
