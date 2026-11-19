import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import DocumentsPage from "./DocumentsPage";
import type { DocumentPage, DocumentView } from "./api/documents";

const document: DocumentView = {
  id: "99cda40f-24c3-5dcf-955f-36daa8ffec6b",
  title: "Ficha ICF",
  agency: null,
  document_type: "ficha_indicador",
  document_date: "2021-09-01",
  catalogued_at: "2026-11-19T02:30:00Z",
  source: "Pasta recebida do cliente",
  notes: "Data da versão impressa.",
  original_filename: "Ficha ICF.pdf",
  sha256: "a".repeat(64),
  size: 238815,
  pdf_url: "/documents/99cda40f-24c3-5dcf-955f-36daa8ffec6b/pdf",
};
const page = (items = [document], total = items.length): DocumentPage => ({
  items,
  total,
  offset: 0,
  limit: 20,
});
function urlOf(input: RequestInfo | URL) {
  return new URL(input instanceof Request ? input.url : String(input));
}
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("consulta do acervo", () => {
  it("mostra carregamento, metadados sem deslocar data documental e PDF via proxy", async () => {
    let finish!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise<Response>((resolve) => {
            finish = resolve;
          }),
      ),
    );
    render(<DocumentsPage />);
    expect(screen.getByText("Carregando acervo…")).toBeInTheDocument();
    await waitFor(() => expect(finish).toBeTypeOf("function"));
    await act(async () => {
      finish(Response.json(page()));
    });
    expect(
      await screen.findByRole("heading", { name: "Ficha ICF" }),
    ).toBeInTheDocument();
    expect(screen.getByText("01/09/2021")).toBeInTheDocument();
    expect(screen.getByText("18/11/2026, 23:30")).toBeInTheDocument();
    expect(screen.getByText("Não confirmado")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /Abrir PDF: Ficha ICF/ });
    expect(link).toHaveAttribute(
      "href",
      expect.stringContaining(`/api/documents/${document.id}/pdf`),
    );
    expect(link).toHaveAttribute("target", "_blank");
    fireEvent.click(screen.getByText("Procedência e detalhes"));
    expect(screen.getByText(document.source)).toBeInTheDocument();
    expect(screen.getByText(document.sha256)).toBeInTheDocument();
  });

  it("envia filtros e paginação reais pelo cliente gerado; aplicar filtro reinicia página", async () => {
    const urls: URL[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = urlOf(input);
        urls.push(url);
        return Response.json(page([document], 21));
      }),
    );
    render(<DocumentsPage />);
    await screen.findByRole("heading", { name: "Ficha ICF" });
    fireEvent.click(screen.getByRole("button", { name: "Próxima" }));
    await waitFor(() =>
      expect(urls.at(-1)?.searchParams.get("offset")).toBe("20"),
    );
    await screen.findByRole("heading", { name: "Ficha ICF" });
    fireEvent.change(screen.getByLabelText("Tipo de documento"), {
      target: { value: "procedimento" },
    });
    fireEvent.change(screen.getByLabelText("Filtrar período por"), {
      target: { value: "catalogued_at" },
    });
    fireEvent.change(screen.getByLabelText("De"), {
      target: { value: "2026-11-19" },
    });
    fireEvent.change(screen.getByLabelText("Até"), {
      target: { value: "2026-11-19" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Aplicar filtros" }));
    await waitFor(() => {
      const params = urls.at(-1)!.searchParams;
      expect(params.get("offset")).toBe("0");
      expect(params.get("document_type")).toBe("procedimento");
      expect(params.get("date_field")).toBe("catalogued_at");
      expect(params.get("date_from")).toBe("2026-11-19");
      expect(params.get("date_to")).toBe("2026-11-19");
    });
    await screen.findByRole("heading", { name: "Ficha ICF" });
    fireEvent.click(screen.getByRole("button", { name: "Limpar" }));
    await waitFor(() =>
      expect(urls.at(-1)?.searchParams.has("document_type")).toBe(false),
    );
    expect(screen.getByLabelText("De")).toHaveValue("");
  });

  it("não consulta intervalo invertido e mantém resultado anterior", async () => {
    const fetch = vi.fn(async () => Response.json(page()));
    vi.stubGlobal("fetch", fetch);
    render(<DocumentsPage />);
    await screen.findByRole("heading", { name: "Ficha ICF" });
    fireEvent.change(screen.getByLabelText("De"), {
      target: { value: "2026-11-20" },
    });
    fireEvent.change(screen.getByLabelText("Até"), {
      target: { value: "2026-11-19" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Aplicar filtros" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "A data inicial deve ser anterior",
    );
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(
      screen.getByRole("heading", { name: "Ficha ICF" }),
    ).toBeInTheDocument();
  });

  it("mostra vazio, falha legível e permite tentar novamente", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        Response.json({ detail: "database secret" }, { status: 503 }),
      )
      .mockResolvedValueOnce(Response.json(page([])));
    vi.stubGlobal("fetch", fetch);
    render(<DocumentsPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Não foi possível consultar",
    );
    expect(screen.queryByText(/database secret/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Tentar novamente" }));
    expect(
      await screen.findByRole("heading", {
        name: "Nenhum documento encontrado.",
      }),
    ).toBeInTheDocument();
  });

  it("ignora resposta antiga depois de trocar o filtro", async () => {
    let first!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementationOnce(
          () =>
            new Promise<Response>((resolve) => {
              first = resolve;
            }),
        )
        .mockResolvedValueOnce(
          Response.json(
            page([
              { ...document, title: "Resultado novo", document_date: null },
            ]),
          ),
        ),
    );
    render(<DocumentsPage />);
    fireEvent.change(screen.getByLabelText("Tipo de documento"), {
      target: { value: "ficha_indicador" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Aplicar filtros" }));
    await screen.findByRole("heading", { name: "Resultado novo" });
    await act(async () => {
      first(Response.json(page()));
    });
    expect(
      screen.queryByRole("heading", { name: "Ficha ICF" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Não identificada")).toBeInTheDocument();
  });
});
