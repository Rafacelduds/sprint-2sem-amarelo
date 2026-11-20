import { useEffect, useMemo, useState } from "react";
import { getSchedules, getDepartures, schedulePageSize,
  type ScheduleCatalog, type ScheduleDepartures, type DepartureQuery } from "./api/schedules";
import "./SchedulesPage.css";

const dateLabel = (value: string) => value.split("-").reverse().join("/");
const time = new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo",
  dateStyle: "short", timeStyle: "medium" });
const captured = (value: string) => time.format(new Date(value));
const kind = { official: "Oficial", gtfs_fixed: "GTFS · horário fixo",
  gtfs_exact: "GTFS · frequência exata", gtfs_frequency_estimate: "GTFS · possibilidade estimada" };
const dayTypes = { U: "Útil", S: "Sábado", D: "Domingo/feriado" };
function today() {
  const parts = new Intl.DateTimeFormat("en", { timeZone: "America/Sao_Paulo",
    year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === type)?.value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}
function sense(value: string, official: boolean) {
  return official ? (value === "0" ? "Ida (0)" : "Volta (1)")
    : value === "" ? "Sentido GTFS não identificado" : `Sentido GTFS ${value}`;
}

function Publication({ data }: { data: ScheduleDepartures }) {
  const { run, line } = data;
  const official = line.status === "official";
  return (
    <>
      <section className="schedule-card" aria-labelledby="publication-title">
        <div className="schedule-heading">
          <h2 id="publication-title">Linha {line.line}</h2>
          <span className="schedule-badge">{official ? "Programação oficial" : line.status === "unavailable"
            ? "Fonte indisponível na captura" : "Alternativa GTFS"}</span>
        </div>
        <p>Referência de {dateLabel(run.service_date)} · {dayTypes[run.day_type]} (seleção do operador).</p>
        <p>Captura da fonte: {data.source_captured_at ? captured(data.source_captured_at) : "instante não informado"} · America/Sao_Paulo.</p>
        <p>Captura não comprova vigência histórica. Corte do dia operacional não definido;
          horários 00:xx e GTFS acima de 24h são preservados, sem atribuir timestamp de partida.</p>
        {line.declared_counts_match === false && (
          <div className="schedule-warning" role="status">
            <strong>Divergência nos totais da fonte</strong>
            <p>A quantidade de horários listados difere do total declarado. A lista original foi preservada, sem completar ou corrigir partidas por suposição.</p>
          </div>
        )}
        {!official && line.status !== "unavailable" && <p className="schedule-warning">
          A fonte oficial não forneceu esta linha/tipo de dia nesta captura. A alternativa GTFS
          pode conter possibilidades estimadas por frequência; não são partidas observadas.
        </p>}
        <div className="schedule-totals">
          <div><span>Horários neste filtro</span><strong>{line.status === "unavailable" ? "Indisponível" : data.total.toLocaleString("pt-BR")}</strong></div>
          {data.direction_totals.map((item) => <div key={item.direction}>
            <span>{sense(item.direction, official)}</span>
            <strong>{item.written.toLocaleString("pt-BR")} listados</strong>
            <small>{item.declared === null ? "Sem total oficial declarado" : `${item.declared} declarados`}</small>
          </div>)}
        </div>
        <details className="schedule-provenance">
          <summary>Fonte, versão e integridade</summary>
          <p>Origem: {official ? "Programação oficial capturada pela US04" : line.status === "unavailable" ? "Nenhuma fonte utilizável" : "GTFS de referência"}.</p>
          {run.source_url && official && <p>Fonte: {run.source_url}</p>}
          <p>Execução: {run.run_id} · {captured(run.started_at)} até {captured(run.finished_at)}.</p>
          <p>Regra: {run.rule_version} · Código gerador: <code>{run.code_version}</code>.</p>
          <code>SHA-256 da fonte: {line.source_sha256 ?? "não identificado"}</code>
          <code>SHA-256 do manifesto: {run.manifest_sha256}</code>
          <code>SHA-256 do Parquet: {run.parquet_sha256}</code>
          <p>Manifesto e Parquet tiveram os bytes verificados nesta consulta. Isso confirma
            integridade dos artefatos lidos, não a correção dos totais declarados pela fonte.</p>
          <p>Esta execução: {run.official_lines_concordant}/{run.official_lines_checked} linhas oficiais
            concordantes. {run.complete ? "Captura concluída" : "Captura incompleta"}.</p>
        </details>
      </section>
      <section className="schedule-card" aria-labelledby="departures-title">
        <h2 id="departures-title">Partidas programadas</h2>
        <p>Ordem original da fonte, com repetições preservadas. Sentidos pertencem à
          API de itinerários ou ao GTFS; não equivalem automaticamente aos códigos Olho Vivo.</p>
        {line.status === "unavailable" ? <p className="schedule-warning">A captura não disponibilizou programação para esta linha. Isso não significa zero partidas ou ausência de serviço.</p>
          : line.status === "gtfs_no_departures" ? <p>Nenhuma partida GTFS para a linha no calendário desta referência. Isso não comprova ausência de serviço real.</p>
            : data.total === 0 ? <p>Nenhum horário listado para o sentido selecionado nesta publicação.</p>
              : <div className="schedule-table" role="region" aria-label="Tabela de partidas" tabIndex={0}>
                <table><thead><tr><th>Horário</th><th>Sentido da fonte</th><th>Tipo</th></tr></thead>
                  <tbody>{data.items.map((item, index) => <tr key={`${item.source_order}-${index}`}>
                    <td><strong>{item.time}</strong></td>
                    <td>{sense(item.direction, item.direction_system === "sptrans_itinerarios")}</td>
                    <td>{kind[item.kind]}</td>
                  </tr>)}</tbody>
                </table>
              </div>}
      </section>
    </>
  );
}

type DayRequest = { day: string; revision: number };
type Choice = { run: string; line: string; direction: string; offset: number };
const emptyChoice: Choice = { run: "", line: "", direction: "", offset: 0 };

export default function SchedulesPage() {
  const [request, setRequest] = useState<DayRequest>(() => ({ day: today(), revision: 0 }));
  const [choice, setChoice] = useState<Choice>(emptyChoice);
  const [catalogResource, setCatalog] = useState<{ request: DayRequest; data: ScheduleCatalog | null } | null>(null);
  const [publication, setPublication] = useState<{ query: DepartureQuery; data: ScheduleDepartures | null } | null>(null);
  const validDay = /^\d{4}-\d{2}-\d{2}$/.test(request.day);
  const catalog = catalogResource?.request === request ? catalogResource : null;
  const run = catalog?.data?.runs.find((item) => item.run_id === choice.run) ?? catalog?.data?.runs[0];
  const line = run?.lines.find((item) => item.line === choice.line) ?? run?.lines[0];
  const query = useMemo<DepartureQuery | null>(() => run && line ? {
    day: request.day, revision: request.revision, run: run.run_id,
    line: line.line, direction: choice.direction, offset: choice.offset,
  } : null, [request.day, request.revision, run, line, choice.direction, choice.offset]);
  const result = publication?.query === query ? publication : null;

  useEffect(() => {
    if (!validDay) return;
    const controller = new AbortController(); let active = true;
    const timeout = setTimeout(() => controller.abort(), 20_000);
    void getSchedules(request.day, controller.signal)
      .then((data) => { if (active) setCatalog({ request, data }); })
      .catch(() => { if (active) setCatalog({ request, data: null }); })
      .finally(() => clearTimeout(timeout));
    return () => { active = false; clearTimeout(timeout); controller.abort(); };
  }, [request, validDay]);
  useEffect(() => {
    if (!query) return;
    const controller = new AbortController(); let active = true;
    const timeout = setTimeout(() => controller.abort(), 30_000);
    void getDepartures(query, controller.signal)
      .then((data) => { if (active) setPublication({ query, data }); })
      .catch(() => { if (active) setPublication({ query, data: null }); })
      .finally(() => clearTimeout(timeout));
    return () => { active = false; clearTimeout(timeout); controller.abort(); };
  }, [query]);

  return (
    <main className="schedules-page">
      <header className="schedules-intro"><span>DADOS ABERTOS · OFERTA PROGRAMADA</span>
        <h1>Programação das linhas</h1>
        <p>Consulte os horários publicados e suas fontes. Programação não comprova viagem realizada.</p>
      </header>
      <div className="schedule-filters">
        <label>Dia de referência<input type="date" value={request.day} onChange={(event) => {
          setRequest({ day: event.target.value, revision: 0 }); setChoice(emptyChoice);
        }} /></label>
        <label>Publicação<select value={run?.run_id ?? ""} disabled={!run} onChange={(event) =>
          setChoice({ ...emptyChoice, run: event.target.value })}>
          {!run && <option value="">Nenhuma carregada</option>}
          {catalog?.data?.runs.map((item, index) => <option key={item.run_id} value={item.run_id}>
            {index === 0 ? "Mais recente · " : ""}{captured(item.finished_at)} · {item.run_id.slice(0, 8)}
          </option>)}
        </select></label>
        <label>Linha<select value={line?.line ?? ""} disabled={!line} onChange={(event) =>
          setChoice({ ...choice, line: event.target.value, direction: "", offset: 0 })}>
          {!line && <option value="">Nenhuma disponível</option>}
          {run?.lines.map((item) => <option key={item.line} value={item.line}>{item.line}</option>)}
        </select></label>
        <label>Sentido<select value={choice.direction} disabled={!line} onChange={(event) =>
          setChoice({ ...choice, direction: event.target.value, offset: 0 })}>
          <option value="">Todos os sentidos</option>
          <option value="0">{line?.status === "official" ? "Ida (0)" : "Sentido GTFS 0"}</option>
          <option value="1">{line?.status === "official" ? "Volta (1)" : "Sentido GTFS 1"}</option>
          {line?.status !== "official" && <option value="unknown">GTFS não identificado</option>}
        </select></label>
        <button disabled={!validDay} onClick={() => {
          setRequest({ ...request, revision: request.revision + 1 });
          setChoice({ ...choice, offset: 0 });
        }}>Atualizar publicações</button>
        <p>Horários em America/Sao_Paulo. A data seleciona publicações existentes; não dispara coleta.</p>
      </div>
      <div aria-live="polite" aria-busy={validDay && (!catalog || (!!query && !result))}>
        {!validDay ? <p className="schedule-notice">Selecione um dia válido.</p>
          : !catalog ? <p className="schedule-notice" role="status">Carregando publicações…</p>
            : !catalog.data ? <div className="schedule-notice" role="alert"><h2>Não foi possível consultar as publicações</h2><p>Tente atualizar novamente. Isso não significa ausência de programação.</p></div>
              : !run ? <div className="schedule-notice"><h2>Sem publicação para este dia</h2><p>Nenhuma captura encontrada para {dateLabel(request.day)}. Não equivale a zero partidas ou ausência de serviço.</p></div>
                : !line ? <p className="schedule-notice">Esta publicação não contém linhas.</p>
                  : !result ? <p className="schedule-notice" role="status">Conferindo integridade e carregando partidas…</p>
                    : !result.data ? <div className="schedule-notice" role="alert"><h2>Publicação indisponível</h2><p>Não foi possível confirmar o acesso e a integridade dos horários. Atualize para tentar novamente ou selecione outra publicação.</p></div>
                      : <>
                        <Publication data={result.data} />
                        <div className="schedule-pagination">
                          <span>{result.data.line.status === "unavailable" ? "Programação indisponível" : result.data.total ? `${choice.offset + 1}–${Math.min(choice.offset + result.data.limit, result.data.total)} de ${result.data.total}` : "Nenhum horário neste filtro"}</span>
                          <button disabled={choice.offset === 0} onClick={() => setChoice({ ...choice, offset: Math.max(0, choice.offset - schedulePageSize) })}>Anterior</button>
                          <button disabled={choice.offset + result.data.limit >= result.data.total} onClick={() => setChoice({ ...choice, offset: choice.offset + schedulePageSize })}>Próxima</button>
                        </div>
                      </>}
      </div>
      <aside className="schedule-history"><h2>Ressalva da conferência histórica</h2>
        <p>A amostra de 19/11/2026 teve 22 de 30 linhas concordantes e oito com divergências
          nos totais da própria fonte. O PO aceitou esse recorte com ressalva, conforme registro
          transmitido por Pedro em 20/11. Isso não homologa outras capturas nem transforma o
          resultado histórico em concordância integral.</p>
        <p>Frequência de captura, vigência histórica e corte do dia operacional seguem pendentes de definição.</p>
      </aside>
    </main>
  );
}
