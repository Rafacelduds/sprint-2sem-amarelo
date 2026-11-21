import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { coverageCollectionCoverageGet } from "@amarelo/api-client";
import CollectionCoverage from "./CollectionCoverage";
vi.mock("@amarelo/api-client", () => ({ coverageCollectionCoverageGet: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
it("identifies the affected garages and does not present old evidence as current", async () => {
  vi.mocked(coverageCollectionCoverageGet).mockResolvedValue({ response: new Response(), data: { checked_at: "2026-11-21T17:00:00Z", cycle_at: "2026-11-21T16:07:06Z", status: "partial", stale: true, failed_garage_companies: [600,602,603], road_saved: true, garages_saved: 24 }, request: new Request("http://test") });
  render(<CollectionCoverage />);
  expect(await screen.findByText("Coleta histórica com cobertura parcial")).toBeInTheDocument();
  expect(screen.getByText(/600, 602, 603/)).toBeInTheDocument();
  expect(screen.getByText(/situação atual é desconhecida/)).toBeInTheDocument();
  expect(screen.getByText(/mapa ao vivo usa uma consulta separada/)).toBeInTheDocument();
});
it("keeps uncertainty visible when the query fails", async () => {
  vi.mocked(coverageCollectionCoverageGet).mockRejectedValue(new Error("offline"));
  render(<CollectionCoverage />);
  expect(await screen.findByText("Cobertura não pôde ser consultada")).toBeInTheDocument();
  expect(screen.getByText(/Não há evidência suficiente/)).toBeInTheDocument();
});
