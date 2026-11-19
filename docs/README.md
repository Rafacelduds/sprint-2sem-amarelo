# Documentação do grupo

Comece pelo [README do projeto](../README.md) para instalar, executar e verificar o ambiente. Aqui fica o contexto compartilhado necessário para desenvolver e revisar.

| Preciso entender… | Onde consultar |
| --- | --- |
| Objetivo, vocabulário, fontes e dúvidas de escopo | [Contexto](contexto.md) |
| Componentes existentes e seus limites | [Arquitetura](arquitetura.md) |
| Bases, procedência e cuidados de processamento | [Dados](dados.md) |
| Captura GTFS, versões e vínculo das posições | [GTFS](gtfs.md) |
| Partidas programadas oficiais e alternativa GTFS | [Programação](programacao.md) |
| Executar e integrar o coletor Olho Vivo | [Coleta](coleta.md) |
| Publicar lacunas diárias e versões de referência | [Confiabilidade — US13](confiabilidade.md) |
| Preservar brutos, importar arquivos e registrar proveniência | [Armazenamento](armazenamento-e-proveniencia.md) |
| Cadastrar, consultar e acessar documentos oficiais | [Acervo documental — US05](acervo-documental.md) |
| Operar backup diário e recuperar a plataforma | [Backup e restauração](backup-e-restauracao.md) |
| Fluxo US → código → revisão → entrega | [Contribuição](contribuicao.md) |
| Formular pedidos, planejar com IA e tratar ambiguidades | [Trabalhar com IA](trabalho-com-ia.md) |
| Por que uma escolha foi feita ou ainda está aberta | [Decisões](decisoes.md) |

## O que manter em cada lugar

- **Trello:** backlog, critérios de aceite da US, tasks, responsáveis, prioridade e andamento. [Quadro do grupo](https://trello.com/b/QAMKiFut/sprint-2-semestre-grupo-amarelo).
- **PR:** resumo da alteração, vínculo com a US, validação executada, limitações e discussão da revisão.
- **Repositório:** instruções reproduzíveis, contratos e regras de domínio, decisões duradouras e limitações conhecidas. Código, migrações, OpenAPI e testes são as referências executáveis; a prosa explica o que eles não deixam claro.

## Como manter enxuto e atual

Atualize a documentação afetada no mesmo PR que muda o comportamento. Edite a explicação existente, evitando acrescentar diários de implementação ou copiar o backlog. Vincule a US, o PR ou a fonte quando sustentarem uma afirmação. Uma proposta só passa a decisão quando houver aprovação identificada.

Crie um documento novo apenas quando o assunto precisar de consulta própria. Uma funcionalidade pequena cabe no documento existente; documentação específica de um componente pode ficar junto dele, com link neste índice. Registre uma decisão curta em [decisoes.md](decisoes.md); se crescer, extraia para `docs/decisoes/NNNN-titulo.md` e mantenha ali o índice. Não é necessário criar um arquivo por task ou por US.

Use links relativos para arquivos do repositório. Fontes externas precisam de título, link quando disponível, data/versão e indicação do que sustentam. Não use caminhos pessoais como dependência de leitura e não versione credenciais, bases volumosas ou cópias de materiais recebidos sem necessidade e autorização de distribuição.
