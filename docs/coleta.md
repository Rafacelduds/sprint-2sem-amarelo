# Coleta Olho Vivo

Implementação da [US01](https://trello.com/c/MuuQFXEX) e da [US29](https://trello.com/c/3d9fUCnh), para revisão. Consulta posições em operação e, por empresa, posições nas garagens. O cliente mantém a sessão autenticada e atualiza a descoberta de empresas a cada ciclo. Não aplica os filtros analíticos da US03.

## Configuração e execução

Mantenha `apps/api/.env` privado, organizado como `apps/api/.env.example`.
Use os dois `--env-file` do README nos comandos Compose. O coletor aceita
`CHAVE_API_OLHO_VIVO` e o nome anterior `OLHOVIVO_TOKEN`; se ambos existirem,
`CHAVE_API_OLHO_VIVO` tem precedência. Nunca use `VITE_*` para credenciais.

| Variável | Uso |
| --- | --- |
| `OLHOVIVO_TOKEN` | Token privado da SPTrans; obrigatório para executar |
| `DATABASE_URL` | Mesmo PostgreSQL da API; no host use `localhost`, no Compose `postgres` |
| `COLLECTION_INTERVAL_SECONDS` | 15–60 segundos, padrão 30, contado entre inícios quando o ciclo cabe no intervalo |
| `COLLECTION_TIMEOUT_SECONDS` | Timeout HTTP, padrão 5 segundos |
| `COLLECTION_COMPANY_CODES` | Lista JSON opcional de empresas; sem ela, descoberta automática. Um recorte deve ser identificado como tal; disponível na execução Python |
| `COLLECTION_ALERT_WEBHOOK` | URL HTTPS privada opcional; recebe os eventos JSON descritos abaixo |
| `COLLECTION_ALERT_FORMAT` | `generic` (padrão, contrato JSON original) ou `discord` (mensagem no canal com confirmação) |
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
| `collection_cycles` | Instante agendado, término, diagnóstico do ciclo, entregas de falha/recuperação e resultado: `running`, `success`, `origin_failure`, `storage_failure` ou `interrupted` |
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

O início da falha contínua é o primeiro ciclo incompleto desde o último sucesso integral, consultado no banco para sobreviver a reinícios. Após pelo menos 600 segundos, a verificação ao término do ciclo emite um alerta local e tenta o webhook, se configurado. No formato genérico, o evento contém `event=collection_outage`, `cycle_id`, `started_at` em UTC, `text` e, quando disponível, `diagnostics`. A verificação pode ocorrer até um ciclo após atingir o limiar.

O diagnóstico usa o último ciclo incompleto: informa quais consultas falharam, se a resposta de operação foi gravada, quantas respostas de garagens foram preservadas e quantas rodadas de consulta/retentativa realmente ocorreram. A mensagem limita os exemplos de consultas com falha e não inclui respostas brutas, URLs ou credenciais. Se a informação não estiver disponível, apresenta isso explicitamente em vez de assumir perda total ou contagem zero. Os códigos detalhados continuam nos registros operacionais.

O alerta sugere uma ação conforme a causa: acompanhar erros de servidor da origem, conferir token/permissões em falhas de autenticação ou verificar conexão, permissões e espaço do banco em falhas de persistência. As retentativas e a reautenticação existentes continuam automáticas; não há reinício indiscriminado para tentar corrigir um HTTP 500 da SPTrans.

**Recuperação:** depois de um ciclo integralmente bem-sucedido, uma ocorrência cujo alerta de falha teve entrega confirmada fica elegível para `event=collection_recovered`, com `cycle_id`, `started_at`, `recovered_at` e `text`. A mensagem inclui a duração e esclarece que as lacunas passadas não foram preenchidas. A confirmação fica em `recovery_alerted_at`; uma falha de envio permanece pendente no banco e é retentada, no máximo uma vez por minuto, inclusive após reinício. Não se envia recuperação para incidentes nunca notificados, nem enquanto houver outra ocorrência ativa, para evitar indicar saúde durante uma nova falha. Pode haver duplicação se o processo cair entre enviar e gravar a confirmação, como no alerta inicial.

Quando o banco está inacessível, o processo mantém a ocorrência e a confirmação do alerta em memória e as registra quando a persistência volta, preservando o identificador para correlacionar a recuperação. Se o processo morrer antes desse registro, esse estado em memória é perdido: supervisão externa continua necessária. Aplique as migrações do README antes de iniciar a nova versão; a revisão `20261120_0009` acrescenta diagnóstico e confirmação de recuperação sem alterar posições existentes.

Só uma resposta HTTP bem-sucedida marca `alerted_at`. Falha ou ausência de destino mantém a entrega pendente, com nova tentativa no máximo uma vez por minuto. Após entrega, não repete o alerta da mesma falha contínua; se o processo cair entre envio e confirmação, pode haver repetição — o receptor genérico pode deduplicar por `cycle_id`. Não coloque sua URL privada no Trello ou no Git. Em 19/11/2026, Victor solicitou integrar o destino Discord; configuração e teste real devem ser conferidos antes de declarar entrega no canal.

## Configurar os alertas no Discord

No Discord, crie um servidor do projeto e um canal de **texto comum** chamado `alertas-coleta`. Em **Configurações do servidor → Integrações → Webhooks**, crie um webhook, selecione esse canal e dê um nome como `Coletor de ônibus`. Também é possível acessar as integrações pelas configurações do canal. Sua conta precisa da permissão de gerenciar webhooks. Copie a URL e salve somente em `apps/api/.env`:

```dotenv
COLLECTION_ALERT_WEBHOOK=https://discord.com/api/webhooks/SEU_ID/SEU_TOKEN
COLLECTION_ALERT_FORMAT=discord
```

Use a URL copiada, sem acrescentar `/github`. O modo Discord envia cartões visuais (`embeds`): vermelho para falha, verde para recuperação e amarelo para teste simples. Causa, coleta preservada, tentativas e ação sugerida ficam em campos separados; início, duração e identificador da ocorrência facilitam a leitura e a correlação. Os horários são de São Paulo. `allowed_mentions` vazio evita menções automáticas. Solicita `wait=true` e só confirma entrega com HTTP 200 e identificador da mensagem retornado. Respostas inválidas, erros HTTP e timeout não confirmam entrega. Em HTTP 429, respeita `retry_after` antes de tentar enviar novamente, sem bloquear a coleta; se o corpo de limitação vier inválido, aguarda pelo menos um minuto.

Para validar uma única mensagem claramente identificada como **TESTE**, execute na raiz, depois de combinar o envio com quem acompanha o canal:

```bash
uv run --package amarelo-api python -m api.collection --test-alert
```

No PowerShell, com a venv já instalada, também pode usar `.\.venv\Scripts\python.exe -m api.collection --test-alert`. Esse modo não inicia a coleta, não precisa do token Olho Vivo, não acessa o banco e não altera o estado dos alertas reais. Código de saída 0 significa envio confirmado; 1 indica falha ou ausência de configuração. Confirme visualmente a mensagem no canal. Evite chamar esse comando repetidamente: cada execução envia um teste novo.

Para testar a apresentação de **cada tipo**, na raiz do repositório, use os comandos abaixo no PowerShell. Cada comando envia exatamente uma mensagem, explicitamente marcada como **SIMULAÇÃO**, com dados fictícios e sem alterar estados reais:

```powershell
# Falha parcial: operação preservada, três consultas de garagem com HTTP 500.
.\.venv\Scripts\python.exe -m api.collection --test-failure-alert

# Recuperação: exemplo de um ciclo completo após uma ocorrência de 12 minutos.
.\.venv\Scripts\python.exe -m api.collection --test-recovery-alert
```

Também é possível usar `uv run --package amarelo-api python -m api.collection` com essas mesmas flags. Elas não consultam SPTrans nem o banco e não aguardam dez minutos: só validam o envio e a apresentação, não simulam uma falha real do coletor. Cada execução gera seu próprio identificador de demonstração.

Após alterar o `.env`, reinicie o processo do coletor. No Compose, recrie o serviço para carregar as variáveis:

```bash
docker compose --env-file apps/api/.env --env-file apps/web/.env --profile coleta up -d --build collector
```

O modo `generic` preserva os campos originais do alerta de falha, acrescenta diagnóstico opcional e passa a emitir também o evento de recuperação descrito acima. A URL é uma credencial; quem a possui pode publicar no canal. Não a exponha em prints, commits ou logs.

Referências: [criar webhook no Discord](https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks) e [contrato de execução](https://docs.discord.com/developers/resources/webhook#execute-webhook), consultados em 19/11/2026.

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
