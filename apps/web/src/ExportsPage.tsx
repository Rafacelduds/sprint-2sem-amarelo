import { useEffect, useRef, useState } from "react";
import { downloadExport, getDictionary, getExports, pageSize, saveExport, type ExportInfo } from "./api/exports";
import "./ExportsPage.css";

const dayLabel = (day: string) => day.split("-").reverse().join("/");
const instant = (value: string) => new Intl.DateTimeFormat("pt-BR", {
  timeZone: "America/Sao_Paulo", dateStyle: "short", timeStyle: "short",
}).format(new Date(value));
const number = new Intl.NumberFormat("pt-BR");
type Request = { before?: string; revision: number };
type Catalog = { request: Request; items?: ExportInfo[] };

function Publication({ item }: { item: ExportInfo }) {
  const [download, setDownload] = useState<{ busy: boolean; message?: string; error?: boolean }>({ busy: false });
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  async function startDownload() {
    const current = new AbortController();
    controller.current = current;
    setDownload({ busy: true });
    const timeout = setTimeout(() => current.abort(), 300_000);
    try {
      const blob = await downloadExport(item, current.signal);
      if (!current.signal.aborted) {
        saveExport(blob, item.dia);
        setDownload({ busy: false, message: "Arquivo recebido. Confira o salvamento no navegador." });
      }
    } catch (error) {
      if (controller.current === current) setDownload({ busy: false, error: true, message: current.signal.aborted
        ? "Download interrompido. Tente novamente." : error instanceof Error ? error.message : "Não foi possível baixar. Tente novamente." });
    } finally { clearTimeout(timeout); }
  }
  return (
    <article className="exports-publication" aria-label={`Publicação de ${dayLabel(item.dia)}`}>
      <div className="exports-publication-heading">
        <div><span className="exports-eyebrow">DIA CIVIL · SÃO PAULO</span><h2>{dayLabel(item.dia)}</h2></div>
        <span className="exports-badge">{item.publicado_no_prazo ? "Publicado no prazo" : "Publicado após o prazo"}</span>
      </div>
      <dl className="exports-metadata">
        <div><dt>Publicado em</dt><dd>{instant(item.publicado_em)}</dd></div>
        <div><dt>Prazo · 06h de D+1</dt><dd>{instant(item.prazo)}</dd></div>
        <div><dt>Capturas · respostas originais</dt><dd>{number.format(item.capturas)}</dd></div>
        <div><dt>Tamanho do Parquet</dt><dd>{number.format(item.bytes)} bytes</dd></div>
        <div><dt>Fuso do dia</dt><dd>{item.fuso ?? "Não informado"}</dd></div>
        <div><dt>Formato</dt><dd>Parquet · uma linha por resposta JSON</dd></div>
      </dl>
      <p className="exports-notice">{item.cobertura ?? "Cobertura não informada."} A quantidade de capturas não mede veículos ou viagens.</p>
      <dl className="exports-provenance">
        <div><dt>Fonte</dt><dd>{item.fonte ?? "Não informada"}</dd></div>
        <div><dt>Licença</dt><dd>{item.licenca === "https://creativecommons.org/licenses/by/4.0/"
          ? <a href={item.licenca} target="_blank" rel="noreferrer">CC BY 4.0 · termos e atribuição</a> : item.licenca ?? "Não informada"}</dd></div>
        <div><dt>SHA-256 · revisão publicada</dt><dd><code>{item.sha256}</code></dd></div>
      </dl>
      <p>O servidor confere a integridade antes de enviar o arquivo. A presença no catálogo, por si só, não comprova que o arquivo está acessível agora.</p>
      <button className="exports-primary" disabled={download.busy} onClick={() => void startDownload()}>
        {download.busy ? "Baixando Parquet…" : download.error ? "Tentar download novamente" : "Baixar Parquet"}
      </button>
      {download.busy && <button onClick={() => controller.current?.abort()}>Cancelar download</button>}
      {download.message && <p role={download.error ? "alert" : "status"}>{download.message}</p>}
    </article>
  );
}

function Dictionary() {
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<{ revision: number; data?: Record<string, string> } | null>(null);
  const resource = state?.revision === revision ? state : null;
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const timeout = setTimeout(() => controller.abort(), 20_000);
    void getDictionary(controller.signal).then((data) => { if (active) setState({ revision, data }); })
      .catch(() => { if (active) setState({ revision }); }).finally(() => clearTimeout(timeout));
    return () => { active = false; clearTimeout(timeout); controller.abort(); };
  }, [revision]);
  return <section className="exports-dictionary" aria-labelledby="dictionary-heading">
    <h2 id="dictionary-heading">Dicionário do arquivo</h2>
    <p>Os corpos JSON originais ficam em uma coluna de bytes. Para obter posições de veículos, decodifique o corpo em UTF-8 e leia o JSON.</p>
    {!resource ? <p role="status">Carregando dicionário…</p> : !resource.data ? <div role="alert">
      <p>Não foi possível consultar o dicionário.</p><button onClick={() => setRevision(revision + 1)}>Tentar dicionário novamente</button>
    </div> : <dl>{Object.entries(resource.data).map(([column, description]) => <div key={column}><dt><code>{column}</code></dt><dd>{description}</dd></div>)}</dl>}
  </section>;
}

export default function ExportsPage() {
  const [request, setRequest] = useState<Request>({ revision: 0 });
  const [history, setHistory] = useState<(string | undefined)[]>([]);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [day, setDay] = useState("");
  const result = catalog?.request === request ? catalog : null;
  const selected = result?.items?.find((item) => item.dia === day) ?? result?.items?.[0];
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const timeout = setTimeout(() => controller.abort(), 20_000);
    void getExports(request.before, controller.signal)
      .then((items) => { if (active) setCatalog({ request, items }); })
      .catch(() => { if (active) setCatalog({ request }); }).finally(() => clearTimeout(timeout));
    return () => { active = false; clearTimeout(timeout); controller.abort(); };
  }, [request]);
  return <main className="exports-page">
    <header className="exports-intro"><span className="exports-eyebrow">DADOS ABERTOS · SEM LOGIN</span>
      <h1>Dados brutos em Parquet</h1>
      <p>Escolha um dia publicado para consultar a origem e baixar as respostas preservadas da API Olho Vivo.</p>
    </header>
    <div className="exports-toolbar">
      <button onClick={() => setRequest({ ...request, revision: request.revision + 1 })}>Atualizar catálogo</button>
      <p>Horários em America/Sao_Paulo. O dia considera a captura, não o horário GPS.</p>
    </div>
    <div className="exports-layout">
      <section aria-label="Catálogo de dias" aria-busy={!result}>
        {!result ? <p className="exports-notice" role="status">Carregando publicações…</p>
          : !result.items ? <div className="exports-notice" role="alert"><h2>Não foi possível consultar o catálogo</h2><p>Tente atualizar o catálogo novamente.</p></div>
            : result.items.length === 0 ? <div className="exports-notice"><h2>{request.before ? "Não há dias anteriores publicados" : "Nenhum arquivo publicado"}</h2><p>Sem publicação disponível neste recorte. Isso não informa se houve coleta ou serviço.</p></div>
              : <><label className="exports-day" htmlFor="export-day">Dia publicado<select id="export-day" value={selected?.dia ?? ""} onChange={(event) => setDay(event.target.value)}>
                {result.items.map((item) => <option value={item.dia} key={item.dia}>{dayLabel(item.dia)}</option>)}
              </select></label>
                {selected && <Publication key={`${selected.dia}-${selected.sha256}`} item={selected} />}</>}
        <div className="exports-pagination">
          <button disabled={history.length === 0} onClick={() => {
            setRequest({ before: history.at(-1), revision: request.revision + 1 });
            setHistory(history.slice(0, -1));
          }}>Dias mais recentes</button>
          <button disabled={!result?.items || result.items.length < pageSize} onClick={() => {
            setHistory([...history, request.before]);
            setRequest({ before: result!.items!.at(-1)!.dia, revision: request.revision + 1 });
          }}>Dias anteriores</button>
        </div>
        <p className="exports-help">Até {pageSize} dias por página. A atualização consulta publicações existentes; não inicia coleta nem gera arquivos. Consulte também a <a href="#confiabilidade">confiabilidade da coleta</a>.</p>
      </section>
      <Dictionary />
    </div>
  </main>;
}
