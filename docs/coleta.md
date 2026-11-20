# Coleta Olho Vivo

Implementação da [US01](https://trello.com/c/MuuQFXEX) e da [US29](https://trello.com/c/3d9fUCnh), para revisão. Consulta posições em operação e, por empresa, posições nas garagens. O cliente mantém a sessão autenticada e atualiza a descoberta de empresas a cada ciclo. Não aplica os filtros analíticos da US03.

## Configuração e execução

Mantenha `apps/api/.env` privado, organizado como `apps/api/.env.example`.
Use os dois `--env-file` do README nos comandos Compose. O coletor aceita
`CHAVE_API_OLHO_VIVO`, `OLHOVIVO_TOKEN` e `OLHO_VIVO_TOKEN`, nessa ordem de
precedência, compartilhada com o mapa. Valores vazios são ignorados; configure
apenas um dos nomes. Nunca use `VITE_*` para credenciais.

| Variável | Uso |
| --- | --- |
| `OLHOVIVO_TOKEN` | Token privado da SPTrans; obrigatório para executar |
| `DATABASE_URL` | Mesmo PostgreSQL da API; no host use `localhost`, no Compose `postgres` |
| `COLLECTION_INTERVAL_SECONDS` | 15–60 segundos, padrão 30, contado entre inícios quando o ciclo cabe no intervalo |
| `COLLECTION_TIMEOUT_SECONDS` | Timeout HTTP, padrão 5 segundos |
| `COLLECTION_COMPANY_CODES` | Lista JSON opcional de empresas; sem ela, descoberta automática. Um recorte deve ser identificado como tal; disponível na execução Python |
| `COLLECTION_ALERT_WEBHOOK` | URL HTTPS privada opcional; recebe os eventos JSON descritos abaixo |
| `COLLECTION_MAX_RETRIES` | De 0 a 5 novas tentativas, padrão 5; disponível na execução Python |
| `COLLECTION_CYCLE_BUDGET_SECONDS` | Até 50 segundos para consultas/retentativas e gravações das respostas, padrão 50; disponível na execução Python |

Após instalar as dependências, subir o PostgreSQL e aplicar as migrações conforme o README, execute na raiz:

```bash
uv run --package amarelo-api python -m api.collection --once
uv run --package amarelo-api python -m api.collection
```

O primeiro comando executa um ciclo (código de saída 1 se incompleto); o segundo mantém a coleta até interrupção. Um advisory lock no PostgreSQL impede duas instâncias simultâneas para o mesmo banco. Com Docker:

```bash
docker compose --profile coleta up -d --build collector
docker compose logs -f collector
docker compose stop collector
```

O coletor usa a imagem Python da API, mas é outro processo. No Compose, aguarda a saúde inicial da API para garantir que as migrações terminaram. O token é enviado apenas à autenticação HTTPS da origem e não é incluído nos logs da aplicação.

## Contrato de persistência

| Tabela | Conteúdo |
| --- | --- |
| `collection_cycles` | Instante agendado, término, alerta entregue e resultado: `running`, `success`, `origin_failure`, `storage_failure` ou `interrupted` |
| `collection_snapshots` | Inbox operacional: bytes exatos da resposta de posições, instante UTC de recebimento, endpoint, empresa e ciclo |
| `vehicle_positions` | Posições normalizadas com vínculo à resposta e horário de coleta; campos ausentes ficam nulos |

A restrição única de `(prefix, gps_at)` vale entre ciclos e reinícios. Para pares completos, a primeira observação persistida é mantida; as respostas seguintes continuam preservadas, inclusive conflitos de coordenadas/linha ou entre operação e garagem. Pares incompletos não permitem identificar duplicação com segurança e são mantidos com nulos. `in_garage` indica a origem da primeira observação normalizada; para examinar todas as origens use as respostas preservadas. Coordenadas não são descartadas por um recorte espacial analítico.

Uma resposta e suas posições são gravadas na mesma transação. Uma falha posterior de outra garagem não apaga as respostas já persistidas; o ciclo fica incompleto. Resposta vazia válida também é registrada. JSON sem a estrutura esperada ou horário GPS sem fuso é falha da origem, sem fabricação de posições.

**Integração com US12:** esta inbox no PostgreSQL preserva respostas para integração, mas não é o acervo bruto imutável no S3. A US12 tem tasks próprias para contrato de chaves, hashes e escrita imutável. O adaptador futuro deve consumir os bytes e metadados da inbox sem serializar novamente nem alterar o timestamp de captura. Retenção/expurgo só podem ser definidos depois de confirmar arquivamento; não há expurgo automático nesta entrega. Dimensionar o volume é necessário antes de operar o histórico completo.

## Validação

A lista `vs` é obrigatória em cada linha das respostas de operação e garagem. Sua ausência gera `invalid_positions`, sem registrar um sucesso vazio; uma lista explicitamente informada como `vs: []` continua válida. Campos ausentes dentro de um veículo continuam nulos, conforme o contrato da US01.

Testes HTTP usam respostas sintéticas e não exigem token nem chamam SPTrans. Para testar persistência real, defina `TEST_DATABASE_URL` apontando para PostgreSQL de desenvolvimento/testes com permissão de criar schemas e rode `uv run pytest`. Os testes criam e removem apenas schemas próprios aleatórios; sem a variável, esses casos são omitidos. A CI fornece um banco dedicado e executa as migrações.

A meta de 99% de ciclos no mês depende de medição operacional. Sucesso nesta implementação significa que todas as consultas previstas do ciclo foram persistidas; não comprova que a origem informou toda a frota real.

## Resiliência e alertas (US29)

Cada ciclo faz uma tentativa inicial e até cinco novas tentativas apenas das consultas ainda pendentes, com esperas de 1, 2, 4, 8 e 16 segundos. O orçamento de 50 segundos pode encerrar antes as retentativas, reservando tempo para finalizar o registro do ciclo. Sessão expirada leva à reautenticação na tentativa seguinte. Respostas já persistidas não são baixadas novamente naquele ciclo.

A consulta de posições em operação independe da descoberta de empresas: se `/Empresa` falhar, a resposta disponível de `/Posicao` continua sendo persistida. A descoberta permanece pendente para retentativa e impede declarar o ciclo completo até consultar também as garagens. Falhas persistentes ao finalizar ciclos no banco também acionam o alerta de armazenamento, respeitando o mesmo limiar de dez minutos e o intervalo mínimo de um minuto entre tentativas de alerta.

Falhas são registradas separando origem e armazenamento. Ciclos incompletos representam lacunas de cobertura, mesmo quando parte das posições foi coletada; os erros identificam as consultas pendentes. No reinício, ciclos deixados `running` viram `interrupted`. Nenhuma posição é criada para preencher lacunas ou recuperar um instante que já passou. O próximo ciclo retoma consultas atuais automaticamente. Se o banco fica inacessível, há log local; no mesmo processo, o intervalo conhecido é registrado quando ele volta. Sem banco e sem processo ativo não é possível reconstruir a extensão exata da indisponibilidade: isso exige supervisão externa (US30).

O início da falha contínua é o primeiro ciclo incompleto desde o último sucesso integral, consultado no banco para sobreviver a reinícios. Após pelo menos 600 segundos, a verificação ao término do ciclo emite um alerta local e tenta o webhook, se configurado. O evento contém `event=collection_outage`, `cycle_id`, `started_at` em UTC e `text`. O receptor deve aceitar um POST JSON e devolver 2xx; integrações de canais com outro formato precisam de adaptação. A verificação pode ocorrer até um ciclo após atingir o limiar.

Só uma resposta HTTP bem-sucedida marca `alerted_at`. Falha ou ausência de destino mantém a entrega pendente, com nova tentativa no máximo uma vez por minuto. Após entrega, não repete o alerta da mesma falha contínua; se o processo cair entre envio e confirmação, pode haver repetição — o receptor pode deduplicar por `cycle_id`. A configuração do canal e a entrega à equipe ainda estão pendentes: Victor pediu apenas preparar o webhook em 18/11/2026. Não coloque sua URL privada no Trello ou no Git.

O Compose reinicia o coletor após encerramento inesperado. Rodando pelo terminal, o laço retoma falhas de ciclos; se o processo for encerrado, é necessário reiniciar o comando ou usar um supervisor. A perda da conexão que mantém o lock encerra o processo para adquirir novamente a exclusividade no reinício.

Para inspecionar latência e completude, sem consultar posições individuais:

```sql
SELECT status, count(*) AS cycles,
       percentile_cont(0.99) WITHIN GROUP
         (ORDER BY extract(epoch FROM finished_at - scheduled_at)) AS p99_seconds
FROM collection_cycles
WHERE finished_at IS NOT NULL
GROUP BY status;
```

Use um filtro temporal explícito ao medir um mês. Para US01, separe falhas da origem; falhas de armazenamento/interrupções não podem ser excluídas como se fossem falhas da API. Para US29, reporte também ciclos concluídos em até 60 segundos e os incompletos. Esta consulta cobre ciclos registrados, não detecta sozinha ciclos que nem começaram enquanto o processo estava parado.

Em 18/11/2026, três ciclos reais foram executados localmente com a credencial privada de Victor. Houve persistência de posições em operação e garagens, mas `/Posicao/Garagem` respondeu HTTP 500 para empresas 600, 602 e 603 na última execução, que terminou em cerca de dez segundos e foi marcada incompleta. Essas empresas não foram excluídas para produzir um sucesso artificial. Os 14 testes automatizados passaram, incluindo PostgreSQL real, além de Ruff, Pyright e validação do Compose. Isso não comprova a meta mensal nem disponibilidade futura da origem.

Na validação adicional da US29, passaram 30 testes, incluindo retentativas, reautenticação, deadline, falha do banco, alerta simulado e estado persistente após reinício. Um ciclo real fez as cinco retentativas, terminou em 33,77 segundos e preservou a falha das mesmas três empresas. O alerta local foi observado; entrega real por webhook não foi executada, pois o destino não foi definido.

A imagem Docker também foi construída e executada com o coletor real. Após ajustar a quinta espera para 16 segundos, o ciclo no contêiner novamente gravou respostas, executou as cinco retentativas e terminou incompleto devido aos mesmos HTTP 500, com código de saída 1 esperado. A execução não foi deixada rodando continuamente.

Referência externa: [documentação da API Olho Vivo/SPTrans](https://www.sptrans.com.br/desenvolvedores/api-do-olho-vivo-guia-de-referencia/documentacao-api/), consultada em 18/11/2026.
