# Coleta Olho Vivo

Implementação da [US01](https://trello.com/c/MuuQFXEX), para revisão. Consulta posições em operação e, por empresa, posições nas garagens. O cliente mantém a sessão autenticada e obtém os códigos das empresas no início do processo. Não aplica os filtros analíticos da US03.

## Configuração e execução

Mantenha um `.env` privado na raiz, organizado como o `.env.example`. O Compose lê esse arquivo para interpolação e passa ao coletor somente suas variáveis; a execução Python também parte da raiz. Nunca use `VITE_*` para credenciais: esses valores podem chegar ao navegador.

| Variável | Uso |
| --- | --- |
| `OLHOVIVO_TOKEN` | Token privado da SPTrans; obrigatório para executar |
| `DATABASE_URL` | Mesmo PostgreSQL da API; no host use `localhost`, no Compose `postgres` |
| `COLLECTION_INTERVAL_SECONDS` | 15–60 segundos, padrão 30, contado entre inícios quando o ciclo cabe no intervalo |
| `COLLECTION_TIMEOUT_SECONDS` | Timeout HTTP, padrão 5 segundos; disponível na execução Python |
| `COLLECTION_COMPANY_CODES` | Lista JSON opcional de empresas; sem ela, descoberta automática. Um recorte deve ser identificado como tal; disponível na execução Python |

Após instalar as dependências, subir o PostgreSQL e aplicar as migrações conforme o README, execute na raiz:

```bash
uv run --package amarelo-api python -m api.collection --once
uv run --package amarelo-api python -m api.collection
```

O primeiro comando executa um ciclo; o segundo mantém a coleta até interrupção. Não execute duas instâncias para o mesmo banco. Com Docker:

```bash
docker compose --profile coleta up -d --build collector
docker compose logs -f collector
docker compose stop collector
```

O coletor usa a imagem Python da API, mas é outro processo. No Compose, aguarda a saúde inicial da API para garantir que as migrações terminaram. O token é enviado apenas à autenticação HTTPS da origem e não é incluído nos logs da aplicação.

## Contrato de persistência

| Tabela | Conteúdo |
| --- | --- |
| `collection_cycles` | Instante agendado, término e resultado: `running`, `success`, `origin_failure` ou `storage_failure` |
| `collection_snapshots` | Inbox operacional: bytes exatos da resposta de posições, instante UTC de recebimento, endpoint, empresa e ciclo |
| `vehicle_positions` | Posições normalizadas com vínculo à resposta e horário de coleta; campos ausentes ficam nulos |

A restrição única de `(prefix, gps_at)` vale entre ciclos e reinícios. Para pares completos, a primeira observação persistida é mantida; as respostas seguintes continuam preservadas, inclusive conflitos de coordenadas/linha ou entre operação e garagem. Pares incompletos não permitem identificar duplicação com segurança e são mantidos com nulos. `in_garage` indica a origem da primeira observação normalizada; para examinar todas as origens use as respostas preservadas. Coordenadas não são descartadas por um recorte espacial analítico.

Uma resposta e suas posições são gravadas na mesma transação. Uma falha posterior de outra garagem não apaga as respostas já persistidas; o ciclo fica incompleto. Resposta vazia válida também é registrada. JSON sem a estrutura esperada ou horário GPS sem fuso é falha da origem, sem fabricação de posições.

**Integração com US12:** esta inbox no PostgreSQL preserva respostas para integração, mas não é o acervo bruto imutável no S3. A US12 tem tasks próprias para contrato de chaves, hashes e escrita imutável. O adaptador futuro deve consumir os bytes e metadados da inbox sem serializar novamente nem alterar o timestamp de captura. Retenção/expurgo só podem ser definidos depois de confirmar arquivamento; não há expurgo automático nesta entrega. Dimensionar o volume é necessário antes de operar o histórico completo.

## Validação

A lista `vs` é obrigatória em cada linha das respostas de operação e garagem. Sua ausência gera `invalid_positions`, sem registrar um sucesso vazio; uma lista explicitamente informada como `vs: []` continua válida. Campos ausentes dentro de um veículo continuam nulos, conforme o contrato da US01.

Testes HTTP usam respostas sintéticas e não exigem token nem chamam SPTrans. Para testar persistência real, defina `TEST_DATABASE_URL` apontando para PostgreSQL de desenvolvimento/testes com permissão de criar schemas e rode `uv run pytest`. Os testes criam e removem apenas schemas próprios aleatórios; sem a variável, esses casos são omitidos. A CI fornece um banco dedicado e executa as migrações.

A meta de 99% de ciclos no mês depende de medição operacional. Sucesso nesta implementação significa que todas as consultas previstas do ciclo foram persistidas; não comprova que a origem informou toda a frota real. Retentativas, alerta e retomada serão acrescentados pela [US29](https://trello.com/c/3d9fUCnh), dependente desta base.

Em 18/11/2026, três ciclos reais foram executados localmente com a credencial privada de Victor. Houve persistência de posições em operação e garagens, mas `/Posicao/Garagem` respondeu HTTP 500 para empresas 600, 602 e 603 na última execução, que terminou em cerca de dez segundos e foi marcada incompleta. Essas empresas não foram excluídas para produzir um sucesso artificial. Os 14 testes automatizados passaram, incluindo PostgreSQL real, além de Ruff, Pyright e validação do Compose. Isso não comprova a meta mensal nem disponibilidade futura da origem.

Referência externa: [documentação da API Olho Vivo/SPTrans](https://www.sptrans.com.br/desenvolvedores/api-do-olho-vivo-guia-de-referencia/documentacao-api/), consultada em 18/11/2026.
