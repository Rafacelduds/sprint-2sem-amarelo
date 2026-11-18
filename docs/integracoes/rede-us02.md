# Catálogo de rede para o mapa (US22 ↔ US02)

Contrato de integração local preparado a pedido de Rafa em 18/11/2026; não é aprovação de uma interface compartilhada com a US02. O produtor GTFS ainda não está neste checkout. O adaptador do mapa **não baixa nem coleta** GTFS: consome um arquivo exportado da US02, indicado por `NETWORK_CATALOG_PATH` no processo ou no ambiente da API. A definição executável é `NetworkExport` em `apps/api/src/api/network.py`.

## Artefato consumido

JSON UTF-8, substituído atomicamente pelo produtor. Campos:

- `version`: SHA-256 (64 caracteres hexadecimais) do GTFS usado.
- `captured_at`: data/hora ISO com fuso da captura do GTFS. Não equivale a vigência.
- `source`: procedência da base e da exportação.
- `synthetic`: `false` em dados reais; `true` identifica fixtures e demonstrações na interface.
- `features`: uma Feature por código Olho Vivo/sentido, sem códigos duplicados. Cada geometria é `MultiLineString`, com segmentos `[[longitude, latitude], ...]` do GTFS. Preservar segmentos e variantes; não unir veículos por linhas retas nem fechar trajetos artificialmente. Lista vazia de segmentos significa percurso indisponível.

Cada `properties` contém `line_id` (código interno Olho Vivo), `label` (letreiro completo), `direction` (sentido Olho Vivo), `destination`, `route_id` e `direction_id` do GTFS, além de `match_source` com a evidência da correspondência. O identificador de sentido GTFS é tratado como texto independente: **não há conversão automática de `sl` para `direction_id`**.

`area_id` é opcional, 1–8 para áreas de operação ou 9 para central. Uma associação exige `area_source`; usar `null` quando desconhecida. Não deduzir pelo primeiro dígito da linha ou pelo GPS. Se uma linha/sentido não tem associação comprovada, pode não constar no artefato; as posições continuam disponíveis em cinza. Exportações inválidas falham como um todo, mantendo posições em funcionamento, sem reutilizar um catálogo inválido ou substituí-lo pela fixture.

As cores da paleta vêm do [padrão cromático SPTrans DV.01.001.1-2-R0](https://www.sptrans.com.br/media/13665/dv-01-001-1-2-r0-padrao_cromatico-parte_1-2.pdf?v=20072023_1151), consultado em 18/11/2026: verde claro, azul escuro, amarelo, vermelho, verde escuro, azul claro, vinho, laranja e prata. Os valores hexadecimais são aproximações para tela, não especificações colorimétricas de pintura. A procedência da **paleta** não comprova a associação de uma **linha** a uma área.

## API pública

- `GET /network/catalog`: status `ready` ou `unavailable`, versão, captura, procedência, marcação sintética, áreas com cores e correspondências das linhas. Sem fonte válida, retorna áreas oficiais mas nenhuma correspondência inventada.
- `GET /network/routes/{line_id}?version={hash}`: GeoJSON FeatureCollection somente daquele código/sentido. Retorna 404 quando o percurso ou a versão solicitada não está disponível.

O catálogo é consultado a cada minuto pela tela. A geometria é carregada somente para linhas selecionadas e ligada à versão do catálogo; respostas de seleções anteriores são abortadas/ignoradas. O cache de arquivo verifica tamanho e mtime. Para atualizar com segurança, publicar um novo arquivo completo e trocar seu nome atomicamente.

## Desenvolvimento sem a US02

`apps/api/tests/fixtures/network.synthetic.json` é uma fixture pequena **inteiramente sintética**, incluindo associações, destinos e geometria. Nunca é carregada por padrão. Para validar manualmente o contrato, iniciar uma API separada apontando `NETWORK_CATALOG_PATH` para ela e usar uma fonte de posições sintéticas com códigos correspondentes. O banner de demonstração deve permanecer visível. Não associar a fixture a posições reais para apresentar resultado como oficial.

Testes verificam validação de coordenadas, ausência de fontes de área, duplicatas, consulta pública, ausência de dados e troca de versão. A integração real deve ser conferida com Pedro/US02 e ter a correspondência validada antes de declarar os percursos reais disponíveis.
