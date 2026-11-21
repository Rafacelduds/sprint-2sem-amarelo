import { useEffect, useState, type FormEvent } from "react";
import { getBackups, type BackupStatus } from "./api/backups";
import "./BackupsPage.css";

const instant = (value: string | null) => value ? new Intl.DateTimeFormat("pt-BR", {
  timeZone: "America/Sao_Paulo", dateStyle: "short", timeStyle: "medium",
}).format(new Date(value)) : "Não informado";
type Request = { token: string; revision: number };
type Result = { request: Request; data?: BackupStatus; error?: string };

function Status({ data }: { data: BackupStatus }) {
  const latest = data.attempts[0];
  return <>
    <section className="backups-card" aria-labelledby="backup-state">
      <div className="backups-heading"><h2 id="backup-state">Situação da rotina</h2>
        <strong className={data.worker_active ? "backups-badge" : "backups-warning"}>
          {data.worker_active ? "Sinal recente da rotina" : "Rotina inativa ou sem sinal recente"}
        </strong></div>
      <p>O sinal é enviado pelo processo de backup. Após {data.heartbeat_timeout_seconds} segundos sem atualização, a rotina deixa de ser considerada ativa.</p>
      <dl className="backups-metrics">
        <div><dt>Último sinal do processo</dt><dd>{instant(data.heartbeat_at)}</dd></div>
        <div><dt>Último ponto concluído</dt><dd>{instant(data.last_success_at)}</dd></div>
        <div><dt>Próxima execução / tentativa</dt><dd>{data.worker_active ? instant(data.next_execution) : "Sem previsão enquanto inativa"}</dd></div>
        <div><dt>Agenda configurada</dt><dd>{data.schedule}</dd></div>
      </dl>
      {data.overdue && <p className="backups-warning" role="status">Backup do período diário pendente. A existência de pontos antigos não resolve este atraso.</p>}
      {latest?.status === "failed" && <p className="backups-warning" role="status">A última tentativa falhou. Consulte a operação; nenhum novo sucesso é presumido.</p>}
      {latest?.status === "running" && <p role="status">{data.worker_active ? "Execução em andamento" : "Tentativa sem conclusão registrada; pode ter sido interrompida"} desde {instant(latest.started_at)}.</p>}
    </section>
    <section className="backups-card" aria-labelledby="recovery-points">
      <h2 id="recovery-points">Pontos de recuperação</h2>
      <p>Últimos 20 registros. Integridade conferida na criação não equivale a verificação atual dos bytes nem a um ensaio de restauração.</p>
      {data.points.length === 0 ? <p>Nenhum ponto de recuperação registrado.</p> : <ul className="backups-points">{data.points.map((point) => <li key={point.id}>
        <div className="backups-heading"><h3>{instant(point.completed_at)}</h3><strong>{point.expired_at ? "Expirado pela retenção" : "Ponto catalogado"}</strong></div>
        <p>ID: <code>{point.id}</code></p>
        <p>{point.verified_at_creation ? `Integridade verificada na criação: ${instant(point.verified_at_creation)}` : "Sem evidência de verificação nesta instrumentação; registro histórico não revalidado."}</p>
        {point.expired_at && <p>Expirado em {instant(point.expired_at)}. Não é um ponto disponível para recuperação.</p>}
        <details><summary>Referências de integridade</summary>
          <p>SHA-256 do manifesto: <code>{point.manifest_sha256 ?? "Não informado"}</code></p>
          <p>SHA-256 do dump: <code>{point.dump_sha256 ?? "Não informado"}</code></p>
          <p>Os arquivos e seus endereços internos não são expostos por este painel.</p>
        </details>
      </li>)}</ul>}
    </section>
    <section className="backups-card" aria-labelledby="backup-attempts"><h2 id="backup-attempts">Tentativas de execução</h2>
      {data.attempts.length === 0 ? <p>Nenhuma tentativa registrada nesta instrumentação. Pontos históricos são apresentados separadamente.</p> : <ul className="backups-points">{data.attempts.map((attempt) => <li key={attempt.id}>
        <strong>{attempt.status === "success" ? "Concluída com sucesso" : attempt.status === "failed" ? "Falhou ou foi interrompida" : attempt.status === "running" ? "Sem conclusão registrada" : "Estado desconhecido"}</strong>
        <p>Início: {instant(attempt.started_at)} · Fim: {instant(attempt.finished_at)}</p>
        <p>ID da tentativa: <code>{attempt.id}</code></p>
        {attempt.backup_id && <p>Ponto: <code>{attempt.backup_id}</code></p>}
      </li>)}</ul>}
    </section>
  </>;
}

function Panel({ token, onLock }: { token: string; onLock: () => void }) {
  const [request, setRequest] = useState<Request>({ token, revision: 0 });
  const [result, setResult] = useState<Result | null>(null);
  const resource = result?.request === request ? result : null;
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20_000);
    void getBackups(request.token, controller.signal)
      .then((data) => { if (active) setResult({ request, data }); })
      .catch((error: unknown) => { if (active) setResult({ request, error: error instanceof Error && error.message === "unauthorized" ? "unauthorized" : "unavailable" }); })
      .finally(() => clearTimeout(timeout));
    return () => { active = false; clearTimeout(timeout); controller.abort(); };
  }, [request]);
  return <>
    <div className="backups-toolbar"><button onClick={() => setRequest({ ...request, revision: request.revision + 1 })}>Atualizar backups</button><button onClick={onLock}>Encerrar acesso</button></div>
    {!resource ? <p role="status">Consultando backups…</p> : resource.error ? <div role="alert" className="backups-card">
      <h2>{resource.error === "unauthorized" ? "Acesso não autorizado" : "Não foi possível consultar os backups"}</h2>
      <p>{resource.error === "unauthorized" ? "Encerre o acesso e informe uma chave de operação válida. O painel também fica indisponível quando o servidor não tem uma chave configurada." : "Tente atualizar novamente. Dados anteriores não são apresentados como atuais."}</p>
    </div> : resource.data && <><p className="backups-checked">Última consulta: {instant(resource.data.checked_at)} · Horários em São Paulo. Atualização manual.</p><Status data={resource.data} /></>}
  </>;
}

export default function BackupsPage() {
  const [token, setToken] = useState("");
  function unlock(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = String(new FormData(form).get("operation-key") ?? "").trim();
    if (value) { setToken(value); form.reset(); }
  }
  return <main className="backups-page">
    <header><span className="backups-eyebrow">OPERAÇÃO DO TIME · ACESSO RESTRITO</span><h1>Backups e recuperação</h1>
      <p>Acompanhe a rotina e os pontos de recuperação. Este painel apenas consulta os registros; não inicia backup nem restauração.</p>
    </header>
    {!token ? <form className="backups-card backups-unlock" onSubmit={unlock}>
      <h2>Acessar painel de backups</h2><p>Use a chave privada fornecida pela equipe. O acesso é encerrado ao sair desta tela ou recarregar a página.</p>
      <label htmlFor="operation-key">Chave de operação<input id="operation-key" name="operation-key" type="password" required autoComplete="off" /></label>
      <button type="submit">Consultar backups</button>
    </form> : <Panel token={token} onLock={() => setToken("")} />}
  </main>;
}
