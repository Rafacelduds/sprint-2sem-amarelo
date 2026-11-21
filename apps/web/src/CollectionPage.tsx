import { useEffect, useState, type FormEvent } from "react";
import { getCollection, type CollectionStatus } from "./api/collection";
import "./BackupsPage.css";

const instant = (value: string | null) => value ? new Intl.DateTimeFormat("pt-BR", {
  timeZone: "America/Sao_Paulo", dateStyle: "short", timeStyle: "medium",
}).format(new Date(value)) : "Não informado";
type Request = { token: string; revision: number };
type Result = { request: Request; data?: CollectionStatus; error?: string };

function Status({ data }: { data: CollectionStatus }) {
  return <section className="backups-card"><h2>Coleta persistida</h2>
    <strong>{data.recent_activity ? "Atividade recente registrada" : "Coletor inativo ou atrasado"}</strong>
    <p>Atividade recente indica ciclos no banco; não confirma que o processo continua ativo. Limite: {data.activity_timeout_seconds} segundos.</p>
    <p>Último sucesso integral: {instant(data.last_success_at)}</p>
    <p>Idade da atividade: {data.age_seconds === null ? "Sem informação" : `${Math.floor(data.age_seconds)} segundos`}</p>
    <p>O mapa consulta um adaptador ao vivo separado. Veículos no mapa não comprovam histórico gravado. Contagens abaixo são registros novos, após deduplicação.</p>
    {!data.cycles.length ? <p>Nenhum ciclo persistido.</p> : <ul className="backups-points">{data.cycles.map(cycle => <li key={cycle.id}>
      <strong>{cycle.status === "success" ? "Sucesso integral" : cycle.status === "running" ? "Sem conclusão registrada" : "Ciclo incompleto / interrompido"}</strong>
      <p>ID: <code>{cycle.id}</code></p>
      <p>Início: {instant(cycle.scheduled_at)} · Fim: {instant(cycle.finished_at)}</p>
      <p>Última captura: {instant(cycle.collected_at)} · {cycle.snapshots} respostas · {cycle.positions} posições novas</p>
    </li>)}</ul>}
    <p>Guarda dos originais: US12 · <a href="#dados-brutos">Publicação US09</a> · <a href="#confiabilidade">Relatório US13</a></p>
  </section>;
}

function Panel({ token, onLock }: { token: string; onLock: () => void }) {
  const [request, setRequest] = useState<Request>({ token, revision: 0 });
  const [result, setResult] = useState<Result | null>(null);
  const resource = result?.request === request ? result : null;
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20_000);
    void getCollection(request.token, controller.signal)
      .then((data) => { if (active) setResult({ request, data }); })
      .catch((error: unknown) => { if (active) setResult({ request, error: error instanceof Error && error.message === "unauthorized" ? "unauthorized" : "unavailable" }); })
      .finally(() => clearTimeout(timeout));
    const poll = setTimeout(() => setRequest({ ...request, revision: request.revision + 1 }), 15_000);
    return () => { clearTimeout(poll); active = false; clearTimeout(timeout); controller.abort(); };
  }, [request]);
  return <>
    <div className="backups-toolbar"><button onClick={() => setRequest({ ...request, revision: request.revision + 1 })}>Atualizar coleta</button><button onClick={onLock}>Encerrar acesso</button></div>
    {!resource ? <p role="status">Consultando coleta…</p> : resource.error ? <div role="alert" className="backups-card">
      <h2>{resource.error === "unauthorized" ? "Acesso não autorizado" : "Não foi possível consultar a coleta"}</h2>
      <p>{resource.error === "unauthorized" ? "Encerre o acesso e informe uma chave de operação válida. O painel também fica indisponível quando o servidor não tem uma chave configurada." : "Tente atualizar novamente. Dados anteriores não são apresentados como atuais."}</p>
    </div> : resource.data && <><p className="backups-checked">Última consulta: {instant(resource.data.checked_at)} · Horários em São Paulo. Atualização a cada 15 segundos.</p><Status data={resource.data} /></>}
  </>;
}

export default function CollectionPage() {
  const [token, setToken] = useState("");
  function unlock(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = String(new FormData(form).get("operation-key") ?? "").trim();
    if (value) { setToken(value); form.reset(); }
  }
  return <main className="backups-page">
    <header><span className="backups-eyebrow">OPERAÇÃO DO TIME · ACESSO RESTRITO</span><h1>Coleta persistida</h1>
      <p>Acompanhe os ciclos gravados no banco, separados da consulta ao vivo do mapa.</p>
    </header>
    {!token ? <form className="backups-card backups-unlock" onSubmit={unlock}>
      <h2>Acessar painel de coleta</h2><p>Use a chave privada fornecida pela equipe. O acesso é encerrado ao sair desta tela ou recarregar a página.</p>
      <label htmlFor="operation-key">Chave de operação<input id="operation-key" name="operation-key" type="password" required autoComplete="off" /></label>
      <button type="submit">Consultar coleta</button>
    </form> : <Panel token={token} onLock={() => setToken("")} />}
  </main>;
}
