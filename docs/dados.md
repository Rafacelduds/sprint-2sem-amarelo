# Dados e reprodutibilidade

Síntese da inspeção dos materiais recebidos, realizada em 17/11/2026 e complementada em 18/11/2026. Origem: [pasta do cliente](https://drive.google.com/drive/folders/1rM9NaLlOIkMIReFMT0XcfCGYvh2j5KyN) e [protótipo](https://github.com/gabinete-falzoni/monitoramento-onibus/tree/c969bf1c9d0d271772cd61e9652af2eed59aa339). A inspeção detalhada foi feita no ambiente local de Victor; esta síntese registra os limites relevantes ao desenvolvimento, sem certificar cobertura de futuras versões dos arquivos.

| Material inspecionado | Cobertura e cuidado principal |
| --- | --- |
| GPS `202605-001.tar.gz` | Maio/2026: 31 Parquet, 443.578.073 registros, cerca de 4,81 GB extraídos. Não é o histórico completo citado pelo cliente. |
| GTFS recebido | Fotografia sem data de captura comprovada; calendário declarado até 01/09/2026 não comprova vigência histórica dos trajetos. |
| Programação `collect_linhas` | Raspagens de 04 e 05/05/2026, com cobertura parcial; não equivalem às referências da demonstração de setembro. |
| Trânsito em CSV | No mês GPS, só cobre 20–31/05/2026. |
| Trânsito em Parquet | Período diferente: termina em junho/2025; não tem sobreposição com GPS de maio/2026. |
| Coluna `geometria` do trânsito | Contém códigos, não coordenadas; falta referência para associação espacial. |
| Clima | Planilhas heterogêneas e repetidas; não foi comprovada série horária ou de quinze minutos. |
| Saídas do protótipo | Duas linhas em setembro/2026, com pequena borda operacional de 31/08; não são brutos de maio nem indicadores homologados. |

No GPS consolidado, `ta` é horário do GPS em UTC, não timestamp da coleta. `py`/`px` são latitude/longitude; `c`, `cl`, `sl` e `p` identificam linha, código interno, sentido e veículo na fonte. Não presumir equivalência direta entre `sl` e `direction_id` do GTFS. Há lacunas e horários antigos dentro do pacote: ausência de registros não prova ausência de serviço.

## Regras para trabalhar com as bases

- Preserve os arquivos recebidos e mantenha derivados separados. Não versione bases volumosas, tokens ou caminhos pessoais; use configuração local. Uma fixture pequena deve ter origem e licença compatíveis com compartilhamento.
- Consulte Parquet por colunas e recortes de data/linha; evite carregar o mês inteiro em memória.
- Distinga horário GPS, horário de coleta, data do arquivo e dia operacional. Defina fuso e corte explicitamente antes de agregar.
- Preserve conflitos e proveniência ao limpar dados. Não transforme ausência de dado em zero, viagem cancelada ou trânsito livre sem regra validada.
- Trate fórmulas, tolerâncias e estimativas do protótipo como referências a validar, conciliando fichas recebidas e critérios acadêmicos.

## Registro mínimo de uma execução ou novo conjunto

O contrato do acervo de GTFS capturado pela US02 está em [gtfs.md](gtfs.md).
Ele separa instante de captura, identidade dos bytes e cobertura do calendário.
Capturar um arquivo hoje não comprova que ele era vigente no acervo GPS de maio.

Documente junto do resultado ou no relatório da execução: fonte e versão (link/nome e hash quando disponível), captura e período coberto, esquema relevante, recorte/filtros, fuso, regras/parâmetros, comando e commit usados, saída e validações/limitações. Não preencha valores desconhecidos por suposição.

Ao integrar uma nova fonte, acrescente aqui apenas o contrato e as restrições duradouras; mantenha os detalhes volumosos de cada execução junto dos artefatos. Para publicar um indicador, vincule a definição aprovada e os casos de validação que sustentam sua interpretação.
