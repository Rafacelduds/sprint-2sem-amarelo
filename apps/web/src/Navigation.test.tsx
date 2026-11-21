import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";

vi.mock("./MapPage", () => ({ default: () => <main>Mapa da rede</main> }));
vi.mock("./DocumentsPage", () => ({
  default: () => <main>Consulta documental</main>,
}));
vi.mock("./SchedulesPage", () => ({ default: () => <main>Consulta de programação</main> }));
vi.mock("./ReliabilityPage", () => ({ default: () => <main>Consulta de confiabilidade</main> }));
vi.mock("./ExportsPage", () => ({ default: () => <main>Consulta de dados brutos</main> }));
afterEach(() => {
  cleanup();
  window.history.replaceState(null, "", "/");
});

it("abre dados brutos por link direto e preserva a navegação existente", () => {
  window.history.replaceState(null, "", "/#dados-brutos");
  render(<App />);
  expect(screen.getByText("Consulta de dados brutos")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Dados brutos" })).toHaveAttribute("aria-current", "page");
  expect(document.title).toContain("Dados brutos em Parquet");
  window.history.replaceState(null, "", "/#mapa");
  fireEvent(window, new HashChangeEvent("hashchange"));
  expect(screen.getByText("Mapa da rede")).toBeInTheDocument();
});

it("abre confiabilidade por link direto e permite voltar ao acervo", () => {
  window.history.replaceState(null, "", "/#confiabilidade");
  render(<App />);
  expect(screen.getByText("Consulta de confiabilidade")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Confiabilidade" })).toHaveAttribute("aria-current", "page");
  expect(document.title).toContain("Confiabilidade da coleta");
  window.history.replaceState(null, "", "/#acervo");
  fireEvent(window, new HashChangeEvent("hashchange"));
  expect(screen.getByText("Consulta documental")).toBeInTheDocument();
  expect(screen.queryByText("Consulta de confiabilidade")).not.toBeInTheDocument();
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

it("abre a programação por link direto e volta ao mapa", () => {
  window.history.replaceState(null, "", "/#programacao"); render(<App />);
  expect(screen.getByText("Consulta de programação")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Programação" })).toHaveAttribute("aria-current", "page");
  window.history.replaceState(null, "", "/#mapa");
  fireEvent(window, new HashChangeEvent("hashchange"));
  expect(screen.getByText("Mapa da rede")).toBeInTheDocument();
});

it("preserva as duas telas ao navegar entre programação e confiabilidade", () => {
  window.history.replaceState(null, "", "/#programacao");
  render(<App />);
  expect(screen.getByText("Consulta de programação")).toBeInTheDocument();
  window.history.replaceState(null, "", "/#confiabilidade");
  fireEvent(window, new HashChangeEvent("hashchange"));
  expect(screen.getByText("Consulta de confiabilidade")).toBeInTheDocument();
  expect(screen.queryByText("Consulta de programação")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Programação" })).toBeInTheDocument();
});
