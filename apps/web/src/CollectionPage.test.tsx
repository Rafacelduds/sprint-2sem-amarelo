import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import CollectionPage from "./CollectionPage";
import { getCollection } from "./api/collection";
vi.mock("./api/collection", () => ({ getCollection: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
it("requires a key and distinguishes absent history from the live map", async () => {
  vi.mocked(getCollection).mockResolvedValue({ alert_configured_now: false, checked_at: "2026-11-21T12:00:00Z", recent_activity: false, age_seconds: null, activity_timeout_seconds: 180, last_success_at: null, cycles: [] });
  render(<CollectionPage />);
  expect(getCollection).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Chave de operação"), { target: { value: "test-key" } });
  fireEvent.click(screen.getByText("Consultar coleta"));
  expect(await screen.findByText("Nenhum ciclo persistido.")).toBeInTheDocument();
  expect(screen.getByText("Coletor inativo ou atrasado")).toBeInTheDocument();
  fireEvent.click(screen.getByText("Encerrar acesso"));
  expect(screen.getByLabelText("Chave de operação")).toHaveValue("");
});
it("does not present a failed query as current activity", async () => {
  vi.mocked(getCollection).mockRejectedValue(new Error("unavailable"));
  render(<CollectionPage />);
  fireEvent.change(screen.getByLabelText("Chave de operação"), { target: { value: "test-key" } });
  fireEvent.click(screen.getByText("Consultar coleta"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível consultar a coleta");
});

it("shows persisted incident recovery without inventing delivery", async () => {
  vi.mocked(getCollection).mockResolvedValue({ alert_configured_now: true, checked_at: "2026-11-21T12:00:00Z", recent_activity: false, age_seconds: 800, activity_timeout_seconds: 120, last_success_at: "2026-11-21T11:59:00Z", cycles: [{ id: "simulation", status: "origin_failure", scheduled_at: "2026-11-21T11:40:00Z", finished_at: "2026-11-21T11:41:00Z", collected_at: null, positions: 0, snapshots: 0, diagnostics: { "Tentativas automáticas": "6 rodadas; 5 retentativas" }, failure_started_at: "2026-11-21T11:40:00Z", recovered_at: "2026-11-21T11:59:00Z", outage_seconds: 1140, alert_delivered_at: null, recovery_alert_delivered_at: null }] });
  render(<CollectionPage />);
  fireEvent.change(screen.getByLabelText("Chave de operação"), { target: { value: "test-key" } });
  fireEvent.click(screen.getByText("Consultar coleta"));
  expect(await screen.findByText(/Incidente recuperado/)).toBeInTheDocument();
  expect(screen.getByText(/Sem confirmação de envio/)).toBeInTheDocument();
  expect(screen.getByText("6 rodadas; 5 retentativas")).toBeInTheDocument();
});
