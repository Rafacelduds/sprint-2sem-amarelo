import { useEffect, useState, type FormEvent } from "react";
import {
  documentPdfUrl,
  getDocuments,
  pageSize,
  type DocumentFilters,
  type DocumentPage,
  type DocumentView,
} from "./api/documents";
import "./DocumentsPage.css";

const emptyFilters: DocumentFilters = {
  type: "",
  dateField: "document_date",
  from: "",
  to: "",
};
const types = {
  contrato: "Contrato",
  aditivo: "Aditivo",
  procedimento: "Procedimento",
  ficha_indicador: "Ficha de indicador",
};
const catalogueDate = new Intl.DateTimeFormat("pt-BR", {
  dateStyle: "short",
  timeStyle: "short",
  timeZone: "America/Sao_Paulo",
});

function DocumentCard({ document }: { document: DocumentView }) {
  return (
    <article className="document-card">
      <div className="document-card-heading">
        <div>
          <span className="document-type">{types[document.document_type]}</span>
          <h2>{document.title}</h2>
        </div>
        <a
          className="document-pdf"
          href={documentPdfUrl(document.id)}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`Abrir PDF: ${document.title} (nova aba)`}
        >
          Abrir PDF <span aria-hidden="true">↗</span>
        </a>
      </div>
      <dl className="document-metadata">
        <div>
          <dt>Órgão emissor</dt>
          <dd>{document.agency ?? "Não confirmado"}</dd>
        </div>
        <div>
          <dt>Data do documento</dt>
          <dd>
            {document.document_date
              ? document.document_date.split("-").reverse().join("/")
              : "Não identificada"}
          </dd>
        </div>
        <div>
          <dt>Incluído no acervo</dt>
          <dd>{catalogueDate.format(new Date(document.catalogued_at))}</dd>
        </div>
      </dl>
      <details className="document-details">
        <summary>Procedência e detalhes</summary>
        <dl>
          <div>
            <dt>Fonte informada</dt>
            <dd>{document.source}</dd>
          </div>
          {document.notes && (
            <div>
              <dt>Observações</dt>
              <dd>{document.notes}</dd>
            </div>
          )}
          <div>
            <dt>Arquivo original</dt>
            <dd>
              {document.original_filename} ·{" "}
              {(document.size / 1024 / 1024).toLocaleString("pt-BR", {
                maximumFractionDigits: 2,
              })}{" "}
              MB
            </dd>
          </div>
          <div>
            <dt>SHA-256 do original</dt>
            <dd className="document-checksum">{document.sha256}</dd>
          </div>
        </dl>
      </details>
    </article>
  );
}

interface RequestState {
  filters: DocumentFilters;
  offset: number;
  revision: number;
}
interface Resource {
  request: RequestState | null;
  data: DocumentPage | null;
  error: boolean;
}

export default function DocumentsPage() {
  const [draft, setDraft] = useState<DocumentFilters>({ ...emptyFilters });
  const [request, setRequest] = useState<RequestState>({
    filters: emptyFilters,
    offset: 0,
    revision: 0,
  });
  const [resource, setResource] = useState<Resource>({
    request: null,
    data: null,
    error: false,
  });
  const [validation, setValidation] = useState("");
  const loading = resource.request !== request;
  const data = !loading ? resource.data : null;
  const failed = !loading && resource.error;

  useEffect(() => {
    const controller = new AbortController();
    let disposed = false;
    void getDocuments(request.filters, request.offset, controller.signal)
      .then((data) => {
        if (!disposed) setResource({ request, data, error: false });
      })
      .catch(() => {
        if (!disposed) setResource({ request, data: null, error: true });
      });
    return () => {
      disposed = true;
      controller.abort();
    };
  }, [request]);

  function apply(event: FormEvent) {
    event.preventDefault();
    if (draft.from && draft.to && draft.from > draft.to) {
      setValidation("A data inicial deve ser anterior ou igual à data final.");
      return;
    }
    setValidation("");
    setRequest({
      filters: { ...draft },
      offset: 0,
      revision: request.revision + 1,
    });
  }
  function clear() {
    setDraft({ ...emptyFilters });
    setValidation("");
    setRequest({
      filters: { ...emptyFilters },
      offset: 0,
      revision: request.revision + 1,
    });
  }

  return (
    <main className="documents-page">
      <header className="documents-intro">
        <span className="documents-eyebrow">DOCUMENTOS DE REFERÊNCIA</span>
        <h1>Acervo documental</h1>
        <p>
          Consulte contratos, procedimentos e fichas de indicadores do
          transporte público. Acesse os PDFs originais e confira sua
          procedência.
        </p>
      </header>

      <form
        className="document-filters"
        onSubmit={apply}
        aria-label="Filtrar documentos"
      >
        <label>
          Tipo de documento
          <select
            value={draft.type}
            onChange={(e) =>
              setDraft({
                ...draft,
                type: e.target.value as DocumentFilters["type"],
              })
            }
          >
            <option value="">Todos os tipos</option>
            {Object.entries(types).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Filtrar período por
          <select
            value={draft.dateField}
            onChange={(e) =>
              setDraft({
                ...draft,
                dateField: e.target.value as DocumentFilters["dateField"],
              })
            }
          >
            <option value="document_date">Data do documento</option>
            <option value="catalogued_at">Data de inclusão no acervo</option>
          </select>
        </label>
        <label>
          De
          <input
            type="date"
            value={draft.from}
            onChange={(e) => setDraft({ ...draft, from: e.target.value })}
            aria-describedby="document-date-help"
          />
        </label>
        <label>
          Até
          <input
            type="date"
            value={draft.to}
            onChange={(e) => setDraft({ ...draft, to: e.target.value })}
            aria-describedby="document-date-help"
          />
        </label>
        <div className="document-filter-actions">
          <button className="document-apply" type="submit">
            Aplicar filtros
          </button>
          <button type="button" onClick={clear}>
            Limpar
          </button>
        </div>
        <p id="document-date-help" className="document-filter-help">
          {draft.dateField === "document_date"
            ? "Ao definir um período, documentos sem data identificada ficam fora do resultado."
            : "A inclusão considera o dia e horário de São Paulo."}
        </p>
        {validation && (
          <p role="alert" className="document-error">
            {validation}
          </p>
        )}
      </form>

      <section
        className="document-results"
        aria-label="Resultados do acervo"
        aria-busy={loading}
      >
        <div className="document-results-heading">
          <h2>Documentos</h2>
          <span role="status">
            {loading
              ? "Buscando documentos…"
              : data
                ? `${data.total} ${data.total === 1 ? "documento encontrado" : "documentos encontrados"}`
                : "Consulta indisponível"}
          </span>
        </div>
        {loading && <p className="document-state">Carregando acervo…</p>}
        {failed && (
          <div className="document-state" role="alert">
            <h3>Não foi possível consultar o acervo.</h3>
            <p>Tente novamente em instantes.</p>
            <button
              onClick={() =>
                setRequest({ ...request, revision: request.revision + 1 })
              }
            >
              Tentar novamente
            </button>
          </div>
        )}
        {data?.items.length === 0 && (
          <div className="document-state">
            <h3>Nenhum documento encontrado.</h3>
            <p>
              O acervo pode estar vazio ou não há documentos para os filtros
              aplicados.
            </p>
            <button onClick={clear}>Limpar filtros</button>
          </div>
        )}
        {data &&
          data.items.map((document) => (
            <DocumentCard key={document.id} document={document} />
          ))}
        {data && data.total > pageSize && (
          <nav className="document-pagination" aria-label="Páginas do acervo">
            <button
              disabled={request.offset === 0}
              onClick={() =>
                setRequest({
                  ...request,
                  offset: Math.max(0, request.offset - pageSize),
                })
              }
            >
              Anterior
            </button>
            <span>
              {request.offset + 1}–
              {Math.min(request.offset + data.items.length, data.total)} de{" "}
              {data.total}
            </span>
            <button
              disabled={request.offset + data.items.length >= data.total}
              onClick={() =>
                setRequest({ ...request, offset: request.offset + pageSize })
              }
            >
              Próxima
            </button>
          </nav>
        )}
      </section>
      <p className="document-footnote">
        A presença no acervo não confirma a vigência do documento. Confira a
        fonte e as observações. PDFs abrem em uma nova aba.
      </p>
    </main>
  );
}
