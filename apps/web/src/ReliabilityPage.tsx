import CollectionCoverage from "./CollectionCoverage";
import { useEffect, useState } from "react";
import { getReliability, type ReliabilityReport, type ReportResult } from "./api/reliability";
import "./ReliabilityPage.css";

const timezone = "America/Sao_Paulo";
const timestamp = new Intl.DateTimeFormat("pt-BR", {
  timeZone: timezone, dateStyle: "short", timeStyle: "medium",
});
const number = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 });
const dateLabel = (value: string) => value.split("-").reverse().join("/");
const instant = (value: string) => timestamp.format(new Date(value));
const duration = (seconds: number) => `${number.format(seconds)} s`;

function todayInSaoPaulo() {
  const parts = new Intl.DateTimeFormat("en", {
    timeZone: timezone, year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(new Date());
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === type)?.value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}

const causes = {
  no_cycle_record: "Sem registro de ciclo",
  origin_failure: "Falha de origem",
  storage_failure: "Falha de armazenamento",
  interrupted: "Ciclo interrompido",
  unfinished_cycle: "Ciclo não finalizado",
  unknown_cycle_status: "Estado de ciclo desconhecido",
};
const linkStatus: Record<string, string> = {
  matched: "Referência vinculada",
  no_gtfs_for_date: "Sem GTFS compatível com a data",
  missing_gps_time: "Horário GPS ausente",
  not_evaluated: "Vínculo não avaliado",
};

function Report({ report }: { report: ReliabilityReport }) {
  const seconds = (Date.parse(report.period_end) - Date.parse(report.period_start)) / 1000;
  const covered = Math.max(0, seconds - report.gap_seconds);
  const coverage = seconds > 0 && report.cycles > 0 ? covered / seconds * 100 : null;
  const expected = Math.ceil(seconds / report.fallback_interval_seconds);
  return (
    <article className="reliability-report" aria-label={`Relatório de ${dateLabel(report.day)}`}>
      <div className="reliability-report-heading">
        <div>
          <h2>{dateLabel(report.day)}</h2>
          <p>Gerado em {instant(report.generated_at)} · {report.timezone}</p>
        </div>
        <span className="reliability-badge">{report.provisional ? "Dia em andamento · provisório" : "Período encerrado"}</span>
      </div>
      <p>Período analisado: {instant(report.period_start)} até {instant(report.period_end)} (fim exclusivo).</p>
      {report.cycles === 0 && (
        <div className="reliability-notice" role="status">
          <strong>Sem evidência de coleta neste período</strong>
          <p>Nenhum ciclo registrado. Isso não comprova ausência de ônibus nem zero falhas de operação.</p>
        </div>
      )}
      <dl className="reliability-metrics">
        <div><dt>Tempo sem lacuna</dt><dd>{coverage === null ? "Sem evidência" : `${number.format(coverage)}%`}</dd></div>
        <div><dt>Ciclos registrados</dt><dd>{number.format(report.cycles)}</dd></div>
        <div><dt>Ciclos esperados · estimativa</dt><dd>{number.format(expected)}</dd></div>
        <div><dt>Tempo com lacunas</dt><dd>{duration(report.gap_seconds)}</dd></div>
      </dl>
      <p className="reliability-help">
        Cobertura temporal: duração sem lacunas / duração analisada. Não mede perda de GPS,
        viagens realizadas ou disponibilidade mensal. A estimativa de ciclos usa intervalo
        uniforme de {report.fallback_interval_seconds} s; mudanças de cadência e retentativas
        impedem compará-la diretamente aos ciclos registrados. {report.legacy_interval_cycles} ciclos
        históricos usam esse intervalo por falta de registro. Tolerância do agendador: {report.scheduling_tolerance_seconds} s.
      </p>

      <section className="reliability-section" aria-labelledby="gaps-heading">
        <h2 id="gaps-heading">Lacunas de coleta</h2>
        <p>Intervalos com coleta incompleta ou sem evidência de registro.</p>
        {report.gaps.length === 0 ? <p>Nenhuma lacuna identificada no período analisado. Isso não certifica a operação dos ônibus.</p> : (
          <div className="reliability-table-scroll" role="region" aria-label="Tabela de lacunas" tabIndex={0}>
            <table><thead><tr><th>Início / fim · São Paulo</th><th>Duração</th><th>Causa / evidência</th></tr></thead>
              <tbody>{report.gaps.map((gap, index) => (
                <tr key={`${gap.start}-${index}`}>
                  <td>{instant(gap.start)}<br />{instant(gap.end)}</td>
                  <td>{duration((Date.parse(gap.end) - Date.parse(gap.start)) / 1000)}</td>
                  <td><strong>{causes[gap.cause]}</strong><br />
                    {gap.evidence === "inferred_absence" ? "Ausência inferida de registro" : "Falha registrada em ciclo"}
                    {gap.possible_maintenance && <p>Manutenção da origem é apenas uma possibilidade, sem confirmação.</p>}
                  </td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </section>

      <section className="reliability-section" aria-labelledby="gtfs-heading">
        <h2 id="gtfs-heading">Referência GTFS</h2>
        <p>Fonte: <strong>{report.gtfs_source_id}</strong>. Cobertura de calendário e captura não comprovam vigência histórica.</p>
        {report.gtfs_reference_periods.length === 0 && <p>Sem períodos de referência informados.</p>}
        <ul className="reliability-reference-list">{report.gtfs_reference_periods.map((period, index) => (
          <li key={`${period.start}-${index}`}>
            <span>{instant(period.start)} até {instant(period.end)}</span>
            {period.sha256 ? <code>SHA-256: {period.sha256}</code> : <strong>Sem referência GTFS compatível neste intervalo</strong>}
          </li>
        ))}</ul>
        <h3>Versões usadas nas observações</h3>
        <p>Agregação pela data de coleta; o vínculo original usa o dia local do GPS.</p>
        {report.gtfs_used.length === 0 ? <p>Sem observações com vínculo GTFS registrado.</p> : (
          <ul className="reliability-reference-list">{report.gtfs_used.map((version, index) => (
            <li key={`${version.sha256}-${version.link_status}-${index}`}>
              <strong>{number.format(version.observations)} observações · {linkStatus[version.link_status] ?? version.link_status}</strong>
              {version.sha256 ? <code>SHA-256: {version.sha256}</code> : <span>Versão não identificada</span>}
            </li>
          ))}</ul>
        )}
      </section>

      <section className="reliability-section" aria-labelledby="schedules-heading">
        <h2 id="schedules-heading">Referências de programação</h2>
        {report.schedule_references.length === 0 ? (
          <p>Nenhum manifesto de programação encontrado para o dia. Isso não comprova ausência de programação oficial.</p>
        ) : report.schedule_references.map((reference) => (
          <div className="reliability-reference" key={reference.run_id}>
            <h3>Execução {reference.run_id}</h3>
            <p>{instant(reference.started_at)} até {instant(reference.finished_at)}</p>
            <p>{reference.complete ? "Captura completa" : "Captura incompleta"} · {reference.has_discrepancies ? "Divergências da fonte identificadas" : "Sem divergências sinalizadas no manifesto"}</p>
            <code>SHA-256 do manifesto: {reference.manifest_sha256}</code>
            {reference.source_hashes.length === 0 ? <p>Hashes de origem não informados.</p> : (
              <details><summary>Hashes das fontes ({reference.source_hashes.length})</summary>
                {reference.source_hashes.map((hash) => <code key={hash}>{hash}</code>)}
              </details>
            )}
          </div>
        ))}
      </section>

      <section className="reliability-section" aria-labelledby="limits-heading">
        <h2 id="limits-heading">Como interpretar este relatório</h2>
        <ul>{report.limitations.map((limit) => <li key={limit}>{limit}</li>)}</ul>
        <p>Dados tardios exigem nova geração do derivado. Atualizar esta página consulta a última publicação; não inicia coleta nem recalcula o dia.</p>
        <p>Regra: {report.rule_version ?? "não informada"} · Código gerador: <code>{report.code_version ?? "não informado"}</code></p>
      </section>
    </article>
  );
}

type RequestState = { day: string; revision: number };
export default function ReliabilityPage() {
  const today = todayInSaoPaulo();
  const [request, setRequest] = useState<RequestState>(() => ({ day: today, revision: 0 }));
  const [resource, setResource] = useState<{ request: RequestState; result: ReportResult } | null>(null);
  const valid = /^\d{4}-\d{2}-\d{2}$/.test(request.day) && request.day <= today;
  const result = resource?.request === request ? resource.result : null;
  useEffect(() => {
    if (!valid) return;
    const controller = new AbortController();
    let active = true;
    const timeout = setTimeout(() => controller.abort(), 20_000);
    void getReliability(request.day, controller.signal)
      .then((value) => { if (active) setResource({ request, result: value }); })
      .catch(() => { if (active) setResource({ request, result: { kind: "unavailable" } }); })
      .finally(() => clearTimeout(timeout));
    return () => { active = false; clearTimeout(timeout); controller.abort(); };
  }, [request, valid]);
  return (
    <main className="reliability-page">
      <CollectionCoverage />
      <header className="reliability-intro">
        <span className="reliability-eyebrow">DADOS ABERTOS · QUALIDADE</span>
        <h1>Confiabilidade da coleta</h1>
        <p>Consulte as lacunas e referências de cada dia. Dados ausentes pedem contexto; não significam ausência de serviço.</p>
      </header>
      <div className="reliability-filters">
        <label htmlFor="report-day">Dia civil · São Paulo
          <input id="report-day" type="date" value={request.day} max={today}
            onChange={(event) => setRequest({ day: event.target.value, revision: 0 })} />
        </label>
        <button disabled={!valid} onClick={() => setRequest({ ...request, revision: request.revision + 1 })}>Atualizar relatório</button>
        <p>Horários em {timezone}. Consulta pública, sem login.</p>
      </div>
      <div aria-live="polite" aria-busy={valid && !result}>
        {!valid ? <p className="reliability-notice">Selecione um dia válido, até hoje em São Paulo.</p>
          : !result ? <p className="reliability-notice" role="status">Carregando relatório de {dateLabel(request.day)}…</p>
            : result.kind === "ready" ? <Report report={result.data} />
              : result.kind === "unpublished" ? <div className="reliability-notice"><h2>Dia ainda não publicado</h2><p>Não há relatório publicado para {dateLabel(request.day)}. Isso não informa se houve coleta ou serviço.</p></div>
                : result.kind === "invalid" ? <p className="reliability-notice">A data foi recusada pela API. Escolha outro dia.</p>
                  : <div className="reliability-notice" role="alert"><h2>Não foi possível consultar o relatório</h2><p>A consulta falhou. Tente atualizar novamente; nenhum resultado anterior é apresentado como atual.</p></div>}
      </div>
    </main>
  );
}
