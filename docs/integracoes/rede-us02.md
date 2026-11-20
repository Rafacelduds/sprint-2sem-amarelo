# Catálogo de rede para o mapa (US22 ↔ US02)

Integração da US22 com a US02, conectada em 19/11/2026 a pedido de Rafa. Os endpoints públicos permanecem versionados. O mapa consome o ZIP original **já armazenado pela US02**; não faz outra coleta na SPTrans.

## Fonte automática

Sem `NETWORK_CATALOG_PATH`, a API consulta `gtfs_captures` e `gtfs_versions` para a fonte `GTFS_SOURCE_ID` (padrão `sptrans`): captura mais recente não futura cuja cobertura de calendário inclua a data atual em São Paulo. Cobertura e captura não são homologação de vigência operacional. As migrações e pelo menos uma execução de `python -m api.gtfs --once` são pré-requisitos; veja [gtfs.md](../gtfs.md).

O objeto é lido do S3 configurado, conferido por tamanho e SHA-256 e copiado para um cache descartável em `data/network/{hash}` (`NETWORK_CACHE_DIR` substitui a raiz). `routes.txt` e `trips.txt` formam o catálogo; `shapes.txt` é indexado por leitura sequencial em SQLite, sem materializar todos os pontos em objetos Python. A geometria é consultada apenas para os sentidos solicitados. O ZIP de origem, o catálogo da US02 e suas decisões temporais são preservados. O cache não deve ser versionado.

Após recuperação pela US32, o leitor usa `S3_RESTORE_MAP` para resolver o bucket,
a chave e a versão física recuperados, inclusive com cache vazio e origem
inacessível. Mapa e programação oficial compartilham essa resolução. Referências
divergentes do hash/tamanho catalogados, codificação inesperada e bytes corrompidos
deixam o catálogo indisponível; o leitor não volta silenciosamente ao bucket antigo.

Se o SHA-256 de um ZIP em cache divergir, o arquivo é fechado antes de ser removido, inclusive no Windows. A tentativa atual informa indisponibilidade e a seguinte volta a ler o objeto da US02; não exige limpeza manual do cache.

A referência é verificada a cada minuto. Ausência de fonte, erro de armazenamento ou hash inválido deixam o catálogo indisponível, sem substituir dados reais por fixtures. A primeira leitura de uma versão inclui a criação do índice; as seguintes reutilizam o cache. A lista de correspondências utiliza os códigos de linha observados no snapshot Olho Vivo, sem baixar outro catálogo externo.

## Correspondência e cores

Somente rotas de ônibus (`route_type=3`) entram no adaptador. A associação exige o letreiro completo (`route_short_name`, ou `route_id` quando ausente) e o destino normalizado correspondente a `trips.trip_headsign`, com **um único `direction_id`**. A normalização remove acentos/pontuação e expande abreviações explícitas (`Term.`, `Jd.`, `Vl.`, `Pq.`, `Prq.`, `Pça.`); não usa aproximação por similaridade ou GPS. Destino ausente, colisão de linhas ou sentido ambíguo não produzem percurso.

No Olho Vivo, os campos de terminais se repetem nos dois sentidos: `lt0` corresponde ao destino do sentido 1 e `lt1` ao destino do sentido 2. O normalizador usa `sl` para escolher esse destino conforme a [documentação SPTrans](https://www.sptrans.com.br/desenvolvedores/api-do-olho-vivo-guia-de-referencia/documentacao-api/), consultada em 19/11/2026. Isso **não converte numericamente** `sl` em `direction_id` GTFS: o vínculo final depende do destino nas duas fontes. As tabelas seguem a [referência GTFS Schedule](https://gtfs.org/documentation/schedule/reference/).

A cor vem diretamente de `routes.route_color` e funciona mesmo quando o sentido não corresponde ou falta geometria. Valores ausentes/inválidos mantêm a apresentação neutra. A classificação em áreas usa somente a correspondência exata com as oito cores de área da SPTrans presentes no GTFS oficial inspecionado em 19/11/2026. Cores especiais são preservadas sem atribuir uma área. Não deduzir a área pelo primeiro dígito da linha ou pela posição. `color_source`, `area_source`, `match_source` e `match_status` preservam essa evidência.

## Substituição explícita para exportações e testes

`NETWORK_CATALOG_PATH` continua opcional: quando definido, substitui a fonte automática pelo JSON abaixo, inclusive quando esse arquivo estiver ausente ou inválido. A definição executável é `NetworkExport` em `apps/api/src/api/network.py`.

## Artefato consumido

JSON UTF-8, substituído atomicamente pelo produtor. Campos:

- `version`: SHA-256 (64 caracteres hexadecimais) do GTFS usado.
- `captured_at`: data/hora ISO com fuso da captura do GTFS. Não equivale a vigência.
- `source`: procedência da base e da exportação.
- `synthetic`: `false` em dados reais; `true` identifica fixtures e demonstrações na interface.
- `features`: uma Feature por código Olho Vivo/sentido, sem códigos duplicados. Cada geometria é `MultiLineString`, com segmentos `[[longitude, latitude], ...]` do GTFS. Preservar segmentos e variantes; não unir veículos por linhas retas nem fechar trajetos artificialmente. Lista vazia de segmentos significa percurso indisponível.

Cada `properties` contém `line_id` (código interno Olho Vivo), `label` (letreiro completo), `direction` (sentido Olho Vivo), `destination`, `route_id` e `direction_id` do GTFS, além de `match_source` com a evidência da correspondência. O identificador de sentido GTFS é tratado como texto independente: **não há conversão automática de `sl` para `direction_id`**.

`area_id` é opcional, 1–8 para áreas de operação ou 9 para central. Uma associação exige `area_source`; usar `null` quando desconhecida. Não deduzir pelo primeiro dígito da linha ou pelo GPS. Se uma linha/sentido não tem associação comprovada, pode não constar no artefato; as posições continuam disponíveis em cinza. Exportações inválidas falham como um todo, mantendo posições em funcionamento, sem reutilizar um catálogo inválido ou substituí-lo pela fixture. `color`, `color_source` e `match_status` são opcionais para preservar exportações anteriores.

As cores da paleta vêm do [padrão cromático SPTrans DV.01.001.1-2-R0](https://www.sptrans.com.br/media/13665/dv-01-001-1-2-r0-padrao_cromatico-parte_1-2.pdf?v=20072023_1151), consultado em 18/11/2026: verde claro, azul escuro, amarelo, vermelho, verde escuro, azul claro, vinho, laranja e prata. As oito cores de tela foram atualizadas com os valores de `routes.txt` do GTFS oficial capturado em 19/11/2026; não são especificações colorimétricas de pintura. A procedência da **paleta** não comprova a associação de uma **linha** a uma área.

## API pública

- `GET /network/catalog`: status `ready` ou `unavailable`, versão, captura, procedência, marcação sintética, áreas com cores e correspondências das linhas. Sem fonte válida, retorna áreas oficiais mas nenhuma correspondência inventada.
- `GET /network/routes/{line_id}?version={hash}`: GeoJSON FeatureCollection somente daquele código/sentido. Retorna 404 quando o percurso ou a versão solicitada não está disponível.

Mudanças nos filtros preservam os percursos carregados que continuam compatíveis com a versão e os IDs efetivos selecionados. Marcar a área de uma linha já selecionada ou alternar ambos/único sentido sem mudar os IDs não apaga os traçados nem exige novas consultas. Percursos excluídos são retirados da visualização imediatamente.

O catálogo é consultado a cada minuto pela tela. A geometria é carregada somente para linhas selecionadas e ligada à versão do catálogo; respostas de seleções anteriores são abortadas/ignoradas. O cache de arquivo verifica tamanho e mtime. Para atualizar com segurança, publicar um novo arquivo completo e trocar seu nome atomicamente.

## Desenvolvimento sem a US02

`apps/api/tests/fixtures/network.synthetic.json` é uma fixture pequena **inteiramente sintética**, incluindo associações, destinos e geometria. Nunca é carregada por padrão. Para validar manualmente o contrato, iniciar uma API separada apontando `NETWORK_CATALOG_PATH` para ela e usar uma fonte de posições sintéticas com códigos correspondentes. O banner de demonstração deve permanecer visível. Não associar a fixture a posições reais para apresentar resultado como oficial.

Testes verificam validação de coordenadas, ausência de fontes de área, duplicatas, consulta pública, ausência de dados e troca de versão. Os testes do adaptador verificam associação por destino (inclusive com sentidos numericamente diferentes), ambiguidade, pontos ordenados, geometria inválida/ausente, integridade e troca de versões. A prévia local de 19/11/2026 foi conferida com GTFS real; isso não homologa os demais indicadores do produto.

A CI também executa os testes focados de mapa/cache em Windows com Python 3.13 e UTF-8, incluindo a remoção do ZIP corrompido e recuperação na tentativa seguinte.
