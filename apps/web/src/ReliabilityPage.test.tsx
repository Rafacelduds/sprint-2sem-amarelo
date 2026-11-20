import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ReliabilityPage from "./ReliabilityPage";
import type { ReliabilityReport } from "./api/reliability";

const hash = "a".repeat(64);
function report(overrides: Partial<ReliabilityReport> = {}): ReliabilityReport {
  return {
    day: "2026-11-20", timezone: "America/Sao_Paulo", rule_version: "us13-v1",
    code_version: "b".repeat(40), generated_at: "2026-11-20T04:00:00Z",
    period_start: "2026-11-20T03:00:00Z", period_end: "2026-11-20T04:00:00Z",
    provisional: true, fallback_interval_seconds: 30, scheduling_tolerance_seconds: 5,
    cycles: 2, legacy_interval_cycles: 0, gap_seconds: 60,
    gaps: [{ start: "2026-11-20T03:10:00Z", end: "2026-11-20T03:11:00Z",
      cause: "origin_failure", evidence: "recorded_cycle", possible_maintenance: true,
      maintenance_confirmed: false }],
    gtfs_source_id: "sptrans", gtfs_reference_periods: [
      { start: "2026-11-20T03:00:00Z", end: "2026-11-20T03:30:00Z", sha256: null },
      { start: "2026-11-20T03:30:00Z", end: "2026-11-20T04:00:00Z", sha256: hash },
    ],
    gtfs_used: [{ sha256: hash, link_status: "matched", observations: 18 }],
    schedules_status: "references_found", schedule_references: [{
      run_id: "run-real-shape-test", started_at: "2026-11-20T03:20:00Z", finished_at: "2026-11-20T03:21:00Z",
      manifest_sha256: "c".repeat(64), source_hashes: ["d".repeat(64)], complete: false, has_discrepancies: true,
    }],
    limitations: ["Ausência de ciclo não comprova ausência de ônibus."],
    ...overrides,
  };
}
const requestUrl = (input: RequestInfo | URL) => new URL(input instanceof Request ? input.url : String(input));
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-20T15:00:00Z"));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("relatório de confiabilidade", () => {
  it("consulta pelo cliente gerado e exibe períodos, cobertura, falhas e referências sem deslocar o dia", async () => {
    const urls: URL[] = [];
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      urls.push(requestUrl(input));
      return Response.json(report());
    });
    vi.stubGlobal("fetch", fetch);
    render(<ReliabilityPage />);
    await screen.findByRole("article", { name: "Relatório de 20/11/2026" });
    expect(urls[0].pathname).toBe("/api/reports/reliability/2026-11-20");
    expect(screen.getByText("98,33%")).toBeInTheDocument();
    expect(screen.getByText("120")).toBeInTheDocument();
    expect(screen.getByText(/intervalo uniforme de 30 s/)).toBeInTheDocument();
    expect(screen.getByText(/20\/11\/2026, 00:00:00 até 20\/11\/2026, 01:00:00/)).toBeInTheDocument();
    expect(screen.getByText("Falha de origem")).toBeInTheDocument();
    expect(screen.getByText(/apenas uma possibilidade, sem confirmação/)).toBeInTheDocument();
    expect(screen.getByText(/Sem referência GTFS compatível/)).toBeInTheDocument();
    expect(screen.getByText(/18 observações/)).toBeInTheDocument();
    expect(screen.getByText(/Captura incompleta/)).toHaveTextContent("Divergências da fonte identificadas");
    expect(screen.getByText(`SHA-256 do manifesto: ${"c".repeat(64)}`)).toBeInTheDocument();
  });

  it("separa relatório não publicado de falha de consulta e permite tentar novamente", async () => {
    const fetch = vi.fn().mockResolvedValueOnce(Response.json({}, { status: 404 }))
      .mockResolvedValueOnce(Response.json({}, { status: 503 })).mockResolvedValueOnce(Response.json(report()));
    vi.stubGlobal("fetch", fetch);
    render(<ReliabilityPage />);
    await screen.findByRole("heading", { name: "Dia ainda não publicado" });
    expect(screen.queryByText("Tempo sem lacuna")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Atualizar relatório" }));
    await screen.findByRole("alert");
    expect(screen.queryByText("Dia ainda não publicado")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Atualizar relatório" }));
    await screen.findByRole("article");
  });

  it("identifica ausência completa de coleta, GTFS e manifestos sem apresentar cobertura como serviço", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json(report({
      cycles: 0, gap_seconds: 3600,
      gaps: [{ start: "2026-11-20T03:00:00Z", end: "2026-11-20T04:00:00Z",
        cause: "no_cycle_record", evidence: "inferred_absence" }],
      gtfs_used: [], gtfs_reference_periods: [], schedule_references: [], schedules_status: "no_manifest_for_day",
    }))));
    render(<ReliabilityPage />);
    await screen.findByText("Sem evidência de coleta neste período");
    expect(screen.getByText("Sem evidência")).toBeInTheDocument();
    expect(screen.getByText("Ausência inferida de registro")).toBeInTheDocument();
    expect(screen.getByText(/Nenhum manifesto de programação encontrado/)).toBeInTheDocument();
    expect(screen.getByText(/Sem observações com vínculo GTFS/)).toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
  });

  it("oculta dados anteriores durante troca de dia e ignora respostas antigas mesmo fora de ordem", async () => {
    const pending: { day: string; resolve: (response: Response) => void; signal: AbortSignal }[] = [];
    vi.stubGlobal("fetch", vi.fn((input: Request) => new Promise<Response>((resolve) => {
      pending.push({ day: requestUrl(input).pathname.slice(-10), resolve, signal: input.signal });
    })));
    render(<ReliabilityPage />);
    expect(screen.getByText(/Carregando relatório de 20\/11\/2026/)).toBeInTheDocument();
    await waitFor(() => expect(pending).toHaveLength(1));
    await act(async () => pending[0].resolve(Response.json(report())));
    await screen.findByRole("article");
    fireEvent.change(screen.getByLabelText("Dia civil · São Paulo"), { target: { value: "2026-11-19" } });
    expect(screen.queryByText("98,33%")).not.toBeInTheDocument();
    expect(screen.getByText(/Carregando relatório de 19\/11\/2026/)).toBeInTheDocument();
    await waitFor(() => expect(pending).toHaveLength(2));
    fireEvent.change(screen.getByLabelText("Dia civil · São Paulo"), { target: { value: "2026-11-18" } });
    await waitFor(() => expect(pending).toHaveLength(3));
    expect(pending[1].signal.aborted).toBe(true);
    await act(async () => pending[2].resolve(Response.json(report({ day: "2026-11-18", cycles: 9 }))));
    await screen.findByRole("article", { name: "Relatório de 18/11/2026" });
    await act(async () => pending[1].resolve(Response.json(report({ day: "2026-11-19" }))));
    expect(screen.queryByRole("article", { name: "Relatório de 19/11/2026" })).not.toBeInTheDocument();
    expect(screen.getByText("9")).toBeInTheDocument();
  });

  it("retira o relatório anterior ao atualizar o mesmo dia e trata erro de rede", async () => {
    let fail!: (reason: Error) => void;
    const fetch = vi.fn().mockResolvedValueOnce(Response.json(report()))
      .mockImplementationOnce(() => new Promise((_resolve, reject) => { fail = reject; }));
    vi.stubGlobal("fetch", fetch);
    render(<ReliabilityPage />);
    await screen.findByRole("article");
    fireEvent.click(screen.getByRole("button", { name: "Atualizar relatório" }));
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    await waitFor(() => expect(fail).toBeTypeOf("function"));
    await act(async () => fail(new Error("offline")));
    await screen.findByRole("alert");
  });

  it("rejeita resposta de outro dia e data vazia ou futura não dispara consultas", async () => {
    const fetch = vi.fn(async () => Response.json(report({ day: "2026-11-19" })));
    vi.stubGlobal("fetch", fetch);
    render(<ReliabilityPage />);
    await screen.findByRole("alert");
    fireEvent.change(screen.getByLabelText("Dia civil · São Paulo"), { target: { value: "" } });
    expect(screen.getByText(/Selecione um dia válido/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Dia civil · São Paulo"), { target: { value: "2026-11-21" } });
    expect(screen.getByRole("button", { name: "Atualizar relatório" })).toBeDisabled();
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("seleciona hoje pelo fuso de São Paulo mesmo quando o UTC já mudou de dia", () => {
    vi.setSystemTime(new Date("2026-11-21T01:00:00Z"));
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({}, { status: 404 })));
    render(<ReliabilityPage />);
    expect(screen.getByLabelText("Dia civil · São Paulo")).toHaveValue("2026-11-20");
  });
});
