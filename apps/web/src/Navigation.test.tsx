import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";

vi.mock("./MapPage", () => ({ default: () => <main>Mapa da rede</main> }));
vi.mock("./DocumentsPage", () => ({
  default: () => <main>Consulta documental</main>,
}));
vi.mock("./SchedulesPage", () => ({ default: () => <main>Consulta de programação</main> }));
afterEach(() => {
  cleanup();
  window.history.replaceState(null, "", "/");
});

it("abre a programação por link direto e volta ao mapa", () => {
  window.history.replaceState(null, "", "/#programacao"); render(<App />);
  expect(screen.getByText("Consulta de programação")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Programação" })).toHaveAttribute("aria-current", "page");
  window.history.replaceState(null, "", "/#mapa");
  fireEvent(window, new HashChangeEvent("hashchange"));
  expect(screen.getByText("Mapa da rede")).toBeInTheDocument();
});

it("abre link direto do acervo e acompanha navegação por hash", () => {
  window.history.replaceState(null, "", "/#acervo");
  render(<App />);
  expect(screen.getByText("Consulta documental")).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "Acervo documental" }),
  ).toHaveAttribute("aria-current", "page");
  window.history.replaceState(null, "", "/#mapa");
  fireEvent(window, new HashChangeEvent("hashchange"));
  expect(screen.getByText("Mapa da rede")).toBeInTheDocument();
  expect(screen.queryByText("Consulta documental")).not.toBeInTheDocument();
});
