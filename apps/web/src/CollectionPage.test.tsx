import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import CollectionPage from "./CollectionPage";
import { getCollection } from "./api/collection";
vi.mock("./api/collection", () => ({ getCollection: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
it("requires a key and distinguishes absent history from the live map", async () => {
  vi.mocked(getCollection).mockResolvedValue({ checked_at: "2026-11-21T12:00:00Z", recent_activity: false, age_seconds: null, activity_timeout_seconds: 180, last_success_at: null, cycles: [] });
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
