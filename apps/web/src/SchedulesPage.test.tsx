import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import SchedulesPage from "./SchedulesPage";
import type { ScheduleRun, ScheduleDepartures } from "./api/schedules";

const hash = "a".repeat(64);
const run: ScheduleRun = {
  run_id: "b415988f-37d7-4877-a732-788b8668a645", service_date: "2026-11-19",
  day_type: "U", timezone: "America/Sao_Paulo", started_at: "2026-11-19T12:00:00Z",
  finished_at: "2026-11-19T12:05:00Z", rule_version: "us04-v1", code_version: "working-tree",
  source_url: "https://itinerariosapi.sptrans.com.br", validity: "capture_reference_only_not_official_historical_validity",
  operational_day_cutoff: null, manifest_sha256: hash, parquet_sha256: "b".repeat(64),
  lines: [{ line: "1020-10", status: "official", source_sha256: "c".repeat(64),
    expected: { "0": 4, "1": 0 }, written: { "0": 3 }, declared_counts_match: false },
    { line: "1012-10", status: "official", source_sha256: "d".repeat(64),
      expected: { "0": 3, "1": 0 }, written: { "0": 3 }, declared_counts_match: true }],
  official_lines_checked: 30, official_lines_concordant: 22,
  has_discrepancies: true, acceptance_30_lines: false, complete: true,
};
function result(overrides: Partial<ScheduleDepartures> = {}): ScheduleDepartures {
  return {
    run, line: run.lines[0], source_captured_at: "2026-11-19T12:01:00Z", direction: null,
    direction_totals: [{ direction: "0", written: 3, declared: 4 }, { direction: "1", written: 0, declared: 0 }],
    total: 3, offset: 0, limit: 100, items: [
      { direction: "0", direction_system: "sptrans_itinerarios", departure_seconds: 84600,
        time: "23:30:00", kind: "official", source_order: 0, trip_id: null },
      { direction: "0", direction_system: "sptrans_itinerarios", departure_seconds: 1800,
        time: "00:30:00", kind: "official", source_order: 1, trip_id: null },
      { direction: "0", direction_system: "sptrans_itinerarios", departure_seconds: 1800,
        time: "00:30:00", kind: "official", source_order: 2, trip_id: null },
    ], ...overrides,
  };
}
const urlOf = (input: RequestInfo | URL) => new URL(input instanceof Request ? input.url : String(input));
const selectDay = () => fireEvent.change(screen.getByLabelText("Dia de referência"), { target: { value: "2026-11-19" } });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("programação pública", () => {
  it("consulta o contrato gerado e preserva fonte, divergência, ordem e horários repetidos", async () => {
    const calls: URL[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input); calls.push(url);
      return Response.json(url.pathname.endsWith("departures") ? result()
        : { day: url.searchParams.get("day"), runs: [run] });
    }));
    render(<SchedulesPage />); selectDay();
    await screen.findByText("23:30:00");
    expect(screen.getAllByText("00:30:00")).toHaveLength(2);
    expect(screen.getByText("Divergência nos totais da fonte")).toBeInTheDocument();
    expect(screen.getByText("4 declarados")).toBeInTheDocument();
    expect(calls.at(-1)?.searchParams.get("line")).toBe("1020-10");
    expect(calls.at(-1)?.searchParams.get("limit")).toBe("100");
    fireEvent.click(screen.getByText("Fonte, versão e integridade"));
    expect(screen.getByText(`SHA-256 do manifesto: ${hash}`)).toBeVisible();
    expect(screen.getByText(/22\/30 linhas oficiais concordantes/)).toBeInTheDocument();
    expect(screen.getByText(/Corte do dia operacional não definido/)).toBeInTheDocument();
  });

  it("distingue dia sem publicação de falha e permite atualizar", async () => {
    let failing = false;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => failing
      ? Response.json({}, { status: 503 }) : Response.json({ day: urlOf(input).searchParams.get("day"), runs: [] })));
    render(<SchedulesPage />);
    await screen.findByRole("heading", { name: "Sem publicação para este dia" });
    failing = true;
    fireEvent.click(screen.getByRole("button", { name: "Atualizar publicações" }));
    await screen.findByRole("alert");
    expect(screen.queryByText("Sem publicação para este dia")).not.toBeInTheDocument();
    expect(screen.queryByText("23:30:00")).not.toBeInTheDocument();
  });

  it("cancela a consulta de linha anterior e ignora uma resposta atrasada", async () => {
    const pending: { url: URL; resolve: (response: Response) => void; signal: AbortSignal }[] = [];
    vi.stubGlobal("fetch", vi.fn((input: Request) => {
      const url = urlOf(input);
      if (!url.pathname.endsWith("departures")) return Promise.resolve(Response.json({ day: url.searchParams.get("day"), runs: [run] }));
      return new Promise<Response>((resolve) => pending.push({ url, resolve, signal: input.signal }));
    }));
    render(<SchedulesPage />); selectDay();
    await waitFor(() => expect(pending).toHaveLength(1));
    fireEvent.change(screen.getByLabelText("Linha"), { target: { value: "1012-10" } });
    await waitFor(() => expect(pending).toHaveLength(2));
    expect(pending[0].signal.aborted).toBe(true);
    await act(async () => pending[1].resolve(Response.json(result({ line: run.lines[1], items: [] }))));
    await screen.findByRole("heading", { name: "Linha 1012-10" });
    await act(async () => pending[0].resolve(Response.json(result())));
    expect(screen.queryByRole("heading", { name: "Linha 1020-10" })).not.toBeInTheDocument();
    expect(screen.queryByText("23:30:00")).not.toBeInTheDocument();
  });

  it("envia paginação e sentido, reiniciando a página ao mudar o filtro", async () => {
    const urls: URL[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input); urls.push(url);
      if (!url.pathname.endsWith("departures")) return Response.json({ day: url.searchParams.get("day"), runs: [run] });
      return Response.json(result({ total: 101, offset: Number(url.searchParams.get("offset")),
        direction: url.searchParams.get("direction") }));
    }));
    render(<SchedulesPage />); selectDay();
    await screen.findByText("23:30:00");
    fireEvent.click(screen.getByRole("button", { name: "Próxima" }));
    await waitFor(() => expect(urls.at(-1)?.searchParams.get("offset")).toBe("100"));
    fireEvent.change(screen.getByLabelText("Sentido"), { target: { value: "1" } });
    await waitFor(() => expect(urls.at(-1)?.searchParams.get("direction")).toBe("1"));
    expect(urls.at(-1)?.searchParams.get("offset")).toBe("0");
  });

  it("identifica alternativa GTFS estimada sem converter horário acima de 24h", async () => {
    const data = result({ line: { ...run.lines[0], status: "gtfs", declared_counts_match: null },
      items: [{ direction: "1", direction_system: "gtfs", departure_seconds: 90000,
        time: "25:00:00", kind: "gtfs_frequency_estimate", source_order: 0, trip_id: "test" }] });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => Response.json(urlOf(input).pathname.endsWith("departures")
      ? data : { day: urlOf(input).searchParams.get("day"), runs: [{ ...run, lines: [data.line] }] })));
    render(<SchedulesPage />); selectDay();
    await screen.findByText("25:00:00");
    expect(screen.getByText("Alternativa GTFS")).toBeInTheDocument();
    expect(screen.getByText("GTFS · possibilidade estimada")).toBeInTheDocument();
    expect(screen.queryByText("Divergência nos totais da fonte")).not.toBeInTheDocument();
  });

  it("não apresenta a ausência da fonte como zero partidas", async () => {
    const data = result({ line: { line: "1020-10", status: "unavailable" }, total: 0, items: [], direction_totals: [] });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => Response.json(urlOf(input).pathname.endsWith("departures")
      ? data : { day: urlOf(input).searchParams.get("day"), runs: [{ ...run, lines: [data.line] }] })));
    render(<SchedulesPage />); selectDay();
    await screen.findByText("Indisponível");
    expect(screen.getByText(/Isso não significa zero partidas/)).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("oculta resultados ao trocar dia e ao falhar a leitura do Parquet", async () => {
    let broken = false;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input);
      if (url.pathname.endsWith("departures")) return broken ? Response.json({}, { status: 503 }) : Response.json(result());
      return Response.json({ day: url.searchParams.get("day"), runs: [run] });
    }));
    render(<SchedulesPage />); selectDay(); await screen.findByText("23:30:00");
    broken = true;
    fireEvent.click(screen.getByRole("button", { name: "Atualizar publicações" }));
    expect(screen.queryByText("23:30:00")).not.toBeInTheDocument();
    await screen.findByRole("heading", { name: "Publicação indisponível" });
    fireEvent.change(screen.getByLabelText("Dia de referência"), { target: { value: "" } });
    expect(screen.getByText("Selecione um dia válido.")).toBeInTheDocument();
    expect(screen.queryByText("Publicação indisponível")).not.toBeInTheDocument();
  });
});
