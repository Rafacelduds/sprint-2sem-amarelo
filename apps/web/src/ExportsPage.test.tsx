import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import ExportsPage from "./ExportsPage";
import { downloadExport, type ExportInfo } from "./api/exports";

const item: ExportInfo = {
  dia: "2026-11-18", publicado_em: "2026-11-19T08:00:00Z", prazo: "2026-11-19T09:00:00Z",
  publicado_no_prazo: true, capturas: 25, bytes: 4, sha256: "a".repeat(64),
  download: "/exports/raw/2026-11-18/download", fonte: "https://api.olhovivo.sptrans.com.br/v2.1",
  licenca: "https://creativecommons.org/licenses/by/4.0/", fuso: "America/Sao_Paulo",
  cobertura: "Capturas disponíveis; não comprova coleta completa ou ausência de serviço.",
};
const urlOf = (input: RequestInfo | URL) => new URL(input instanceof Request ? input.url : String(input));
const dictionary = { corpo_original: "BLOB: JSON original, sem limpeza." };
function serve(catalog: (url: URL) => Response | Promise<Response>, download?: () => Response) {
  const mock = vi.fn(async (input: RequestInfo | URL) => {
    const url = urlOf(input);
    if (url.pathname.endsWith("/dictionary")) return Response.json(dictionary);
    if (url.pathname.endsWith("/download")) return download?.() ?? new Response(null, { status: 503 });
    return catalog(url);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it("mostra carregamento, dias reais do catálogo, metadados e dicionário antes do download", async () => {
  let finish!: (value: Response) => void;
  serve(() => new Promise<Response>((resolve) => { finish = resolve; }));
  render(<ExportsPage />);
  expect(screen.getByText("Carregando publicações…")).toBeInTheDocument();
  await waitFor(() => expect(finish).toBeTypeOf("function"));
  await act(async () => finish(Response.json([item, { ...item, dia: "2026-11-17", sha256: "b".repeat(64) }])));
  expect(screen.getByRole("heading", { name: "18/11/2026" })).toBeInTheDocument();
  expect(screen.getByText("19/11/2026, 05:00")).toBeInTheDocument();
  expect(screen.getByText(item.sha256)).toBeInTheDocument();
  expect(screen.getByText(item.fonte!)).toBeInTheDocument();
  expect(screen.getByText(dictionary.corpo_original)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /CC BY 4.0/ })).toHaveAttribute("href", item.licenca);
  fireEvent.change(screen.getByLabelText("Dia publicado"), { target: { value: "2026-11-17" } });
  expect(screen.getByRole("heading", { name: "17/11/2026" })).toBeInTheDocument();
  expect(screen.getByText("b".repeat(64))).toBeInTheDocument();
});

it("distingue falha de catálogo e vazio e permite nova tentativa sem mostrar erro privado", async () => {
  let fail = true;
  serve(() => fail ? Response.json({ detail: "segredo interno" }, { status: 503 }) : Response.json([]));
  render(<ExportsPage />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível consultar o catálogo");
  expect(screen.queryByText(/segredo interno/)).not.toBeInTheDocument();
  fail = false;
  fireEvent.click(screen.getByText("Atualizar catálogo"));
  expect(await screen.findByRole("heading", { name: "Nenhum arquivo publicado" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Baixar Parquet" })).not.toBeInTheDocument();
});

it("pagina com before exclusivo e volta mesmo ao chegar numa página vazia", async () => {
  const dates = Array.from({ length: 31 }, (_, i) => ({ ...item, dia: `2026-10-${String(31 - i).padStart(2, "0")}` }));
  const urls: URL[] = [];
  serve((url) => { urls.push(url); return Response.json(url.searchParams.has("before") ? [] : dates); });
  render(<ExportsPage />);
  await screen.findByRole("heading", { name: "31/10/2026" });
  fireEvent.click(screen.getByText("Dias anteriores"));
  await screen.findByRole("heading", { name: "Não há dias anteriores publicados" });
  expect(urls.at(-1)?.searchParams.get("before")).toBe("2026-10-01");
  expect(urls.at(-1)?.searchParams.get("limit")).toBe("31");
  fireEvent.click(screen.getByText("Dias mais recentes"));
  await screen.findByRole("heading", { name: "31/10/2026" });
  expect(urls.at(-1)?.searchParams.has("before")).toBe(false);
});

it("ignora catálogo antigo após atualizar e recupera falha independente do dicionário", async () => {
  let finish!: (value: Response) => void;
  let catalogs = 0; let dictionaries = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    if (urlOf(input).pathname.endsWith("dictionary")) return ++dictionaries === 1 ? new Response(null, { status: 503 }) : Response.json(dictionary);
    return ++catalogs === 1 ? new Promise<Response>((resolve) => { finish = resolve; }) : Response.json([item]);
  }));
  render(<ExportsPage />);
  await screen.findByText("Não foi possível consultar o dicionário.");
  fireEvent.click(screen.getByText("Atualizar catálogo"));
  await screen.findByRole("heading", { name: "18/11/2026" });
  await act(async () => finish(Response.json([])));
  expect(screen.queryByText("Nenhum arquivo publicado")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("Tentar dicionário novamente"));
  expect(await screen.findByText(dictionary.corpo_original)).toBeInTheDocument();
});

it("só salva após ação explícita, valida revisão/tipo/tamanho e permite repetir falha", async () => {
  const create = vi.fn(() => "blob:arquivo");
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: create });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  let fail = true;
  serve(() => Response.json([item]), () => fail ? new Response(null, { status: 503 }) : new Response("PAR1", {
    headers: { ETag: `"${item.sha256}"`, "Content-Type": "application/vnd.apache.parquet" },
  }));
  render(<ExportsPage />);
  await screen.findByRole("heading", { name: "18/11/2026" });
  expect(create).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Baixar Parquet"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Arquivo indisponível");
  expect(create).not.toHaveBeenCalled();
  fail = false;
  fireEvent.click(screen.getByText("Tentar download novamente"));
  await screen.findByText(/Arquivo recebido/);
  expect(click).toHaveBeenCalledOnce();
  expect(click.mock.instances[0]).toHaveAttribute("download", "brutos-2026-11-18.parquet");
});

it.each([
  ["b".repeat(64), "application/vnd.apache.parquet", "PAR1", /revisão do arquivo mudou/],
  [item.sha256, "application/json", "PAR1", /não retornou um arquivo Parquet/],
  [item.sha256, "application/vnd.apache.parquet", "PA", /incompleto/],
])("recusa conteúdo divergente de metadados (%s, %s)", async (hash, type, body, message) => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { headers: { ETag: `"${hash}"`, "Content-Type": type } })));
  await expect(downloadExport(item, new AbortController().signal)).rejects.toThrow(message);
});

it("cancela um download pendente e permite tentar novamente", async () => {
  let signal: AbortSignal | undefined;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (urlOf(input).pathname.endsWith("/dictionary")) return Response.json(dictionary);
    if (urlOf(input).pathname.endsWith("/download")) {
      signal = init?.signal ?? (input instanceof Request ? input.signal : undefined);
      return new Promise<Response>((_resolve, reject) => signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError"))));
    }
    return Response.json([item]);
  }));
  render(<ExportsPage />);
  await screen.findByRole("heading", { name: "18/11/2026" });
  fireEvent.click(screen.getByText("Baixar Parquet"));
  expect(await screen.findByText("Baixando Parquet…")).toBeDisabled();
  fireEvent.click(screen.getByText("Cancelar download"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Download interrompido");
  expect(signal?.aborted).toBe(true);
  expect(screen.getByText("Tentar download novamente")).toBeEnabled();
});
