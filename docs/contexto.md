# Contexto do produto

## Objetivo e escopo

O projeto acadêmico do Grupo Amarelo trata de infraestrutura para auditoria cidadã contínua dos ônibus de São Paulo. O documento de requisitos identifica como parceiro o Gabinete da Vereadora Renata Falzoni, por meio do Núcleo de Dados. A visão inclui integrar posições dos ônibus, programação e contexto para publicar indicadores e visualizações de interesse público.

A fonte contém **US01–US32**, em seis grupos: coleta operacional; dados contextuais; histórico e dados abertos; indicadores; mapas e painéis; desempenho e resiliência. Isso é a visão documental do produto, não o compromisso de entregar todas as histórias nas três semanas. A seleção e os critérios de cada entrega devem estar explícitos no Trello; preserve os IDs e confira dependências ao recortar uma história.

O projeto tem cinco integrantes, todos desenvolvedores, inclusive quem exerce PO ou Scrum Master. O processo acadêmico prevê três sprints semanais; este documento não fixa datas nem declara qual sprint está em andamento.

## Vocabulário mínimo

| Termo | Significado neste projeto |
| --- | --- |
| US | História de usuário, identificada por US01–US32; entrega com critérios de aceite |
| Task | Trabalho derivado de uma US, registrado e acompanhado no Trello |
| GPS | Posição observada de um veículo; não comprova isoladamente uma viagem completa |
| GTFS | Referência de rede e oferta programada, cuja versão e vigência precisam ser identificadas |
| IPP / ICV | Indicadores de pontualidade de partidas / cumprimento de viagens; fórmulas e agregações dependem da referência aplicável |
| Dia operacional | Agrupamento de serviço cujo corte precisa ser definido; pode diferir da data civil e da data do arquivo |

## Fontes e limites de interpretação

| Fonte | Uso e procedência |
| --- | --- |
| `Requisitos - Análise de dados do transporte público 02.docx` | Requisitos acadêmicos fornecidos ao grupo; preservar IDs, critérios e dependências. Existem seleções e marcações cuja precedência precisa de esclarecimento. |
| `Guia_do_Projeto_Scrum_Kanban_Squad.pdf` | Processo, cartões e métricas acadêmicas. Exemplos de WIP não equivalem a limites aprovados pelo grupo. |
| [Materiais do cliente no Drive](https://drive.google.com/drive/folders/1rM9NaLlOIkMIReFMT0XcfCGYvh2j5KyN) | Bases e referências recebidas; acesso depende das permissões da pasta. Cuidados em [dados.md](dados.md). |
| [Protótipo do cliente](https://github.com/gabinete-falzoni/monitoramento-onibus) | Referência técnica em R/Rcpp e Shiny; não define a arquitetura deste repositório nem homologa resultados. |
| Orientação de Victor em 18/11/2026 | Fluxo de colaboração registrado em [contribuicao.md](contribuicao.md). |

Os dois documentos acadêmicos foram fornecidos fora deste repositório, na pasta de materiais `Orientações`; não são anexados nesta estrutura. Para usá-los como critério, obtenha os originais com o grupo. As sínteses aqui não substituem esses documentos.

## Pendências que exigem confirmação

- Recorte de US e prioridades para cada sprint; cores de grifo não têm significado confirmado.
- Conciliação dos critérios acadêmicos com as fichas do IQT recebidas. Por exemplo, a ficha de IPP usa tolerância de ±3 minutos e partidas programadas no denominador, com divergência em relação à US16; não substituir uma definição silenciosamente.
- Referências temporais das bases e regras de reconstrução de viagens, deduplicação e dia operacional antes de publicar indicadores.

Ao resolver uma dúvida, registre fonte, data e quem aprovou em [decisoes.md](decisoes.md), atualize a explicação afetada e os critérios da US. Relatos de reunião e hipóteses não devem aparecer como decisões confirmadas.
