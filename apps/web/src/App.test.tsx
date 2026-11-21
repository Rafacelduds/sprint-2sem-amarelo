vi.mock("./CollectionCoverage", () => ({ default: () => null }));
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useEffect } from "react";
import App from "./App";
import type { Vehicle } from "./api/positions";
import type { Bounds } from "./network";
import type { RouteCollection } from "./api/network";

vi.mock("./components/BusMap", () => ({
  default: function MockBusMap({
    vehicles,
    routes,
    onBounds,
    onSelect,
    visual,
    routeFocus,
    onRoutePick,
    fitRequest,
  }: {
    onSelect: (id: string) => void;
    routeFocus: string | null;
    fitRequest: number;
    onRoutePick: (labels: string[]) => void;
    visual: { mode: string; busDiameter: number; groupScale: number };
    vehicles: Vehicle[];
    routes: RouteCollection[];
    onBounds: (b: Bounds) => void;
  }) {
    useEffect(
      () => onBounds({ north: -23, south: -24, east: -46, west: -47 }),
      [onBounds],
    );
    return (
      <div>
        <div data-testid="visual-mode">
          {visual.mode}:{visual.busDiameter}:{visual.groupScale}
        </div>
        <button onClick={() => onSelect(vehicles[0].id)}>
          Selecionar ônibus no mapa
        </button>
        <output data-testid="fit-request">{fitRequest}</output>
        <div data-testid="route-focus">{routeFocus ?? "all"}</div>
        <button onClick={() => onRoutePick(["5015-10"])}>
          Clicar percurso único
        </button>
        <button onClick={() => onRoutePick(["5015-10", "701A-10"])}>
          Clicar trecho compartilhado
        </button>
        <div data-testid="map">{vehicles.map((v) => v.id).join(",")}</div>
        <div data-testid="routes">
          {routes
            .flatMap((route) =>
              route.features.map((feature) => feature.properties.line_id),
            )
            .join(",")}
        </div>
        <button
          onClick={() =>
            onBounds({ north: -23.5, south: -23.555, east: -46, west: -47 })
          }
        >
          Mover mapa de teste
        </button>
      </div>
    );
  },
}));
const network = {
  status: "ready",
  version: "a".repeat(64),
  areas: [
    { id: 2, name: "Norte", color: "#22599B" },
    { id: 8, name: "Oeste", color: "#DE7D30" },
  ],
  synthetic: true,
  lines: [
    { line_id: 1, area_id: 2, color: "#22599B" },
    { line_id: 11, area_id: 2, color: "#22599B" },
    { line_id: 2, area_id: 8, color: "#DE7D30" },
  ],
};
function snapshot(age = 0) {
  return {
    collected_at: new Date(Date.now() - age * 1000).toISOString(),
    served_at: new Date().toISOString(),
    stale: age > 60,
    lines: [
      { id: 1, label: "5015-10", direction: 1, destination: "Terminal A" },
      { id: 11, label: "5015-10", direction: 2, destination: "Terminal B" },
      { id: 2, label: "701A-10", direction: 1, destination: "Terminal C" },
    ],
    vehicles: [
      {
        id: "100",
        line_id: 1,
        line: "5015-10",
        direction: 1,
        latitude: -23.55,
        longitude: -46.63,
        gps_at: new Date(Date.now() - 10000).toISOString(),
      },
      {
        id: "110",
        line_id: 11,
        line: "5015-10",
        direction: 2,
        latitude: -23.56,
        longitude: -46.64,
        gps_at: new Date(Date.now() - 120000).toISOString(),
      },
      {
        id: "200",
        line_id: 2,
        line: "701A-10",
        direction: 1,
        latitude: -23.56,
        longitude: -46.64,
        gps_at: null,
      },
    ],
    source: "SPTrans / Olho Vivo",
    discarded: 0,
  };
}
function respond(age = 0) {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
    const u = String(url);
    if (u.includes("/network/catalog"))
      return new Response(JSON.stringify(network));
    if (u.includes("/network/routes"))
      return new Response("{}", { status: 404 });
    return new Response(JSON.stringify(snapshot(age)));
  });
}

function respondWithRoutes() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
    const u = String(url);
    if (u.includes("/network/catalog"))
      return new Response(JSON.stringify(network));
    if (u.includes("/network/routes/")) {
      const id = Number(new URL(u, "http://test").pathname.split("/").pop());
      const line = snapshot().lines.find((line) => line.id === id)!;
      const route: RouteCollection = {
        type: "FeatureCollection",
        version: network.version,
        captured_at: "2026-11-18T12:00:00Z",
        synthetic: true,
        features: [
          {
            type: "Feature",
            geometry: {
              type: "MultiLineString",
              coordinates: [
                [
                  [-46.63, -23.55],
                  [-46.64, -23.56],
                ],
              ],
            },
            properties: {
              line_id: id,
              label: line.label,
              direction: line.direction,
              destination: line.destination,
              route_id: `synthetic-${line.label}`,
              direction_id: String(line.direction),
              match_source: "Fixture sintética",
            },
          },
        ],
      };
      return new Response(JSON.stringify(route));
    }
    return new Response(JSON.stringify(snapshot()));
  });
}
afterEach(() => {
  window.localStorage.clear();
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
});
describe("Rede pública", () => {
  it.each(["http", "unavailable"])("suspends area filtering on %s and restores it with the catalog", async (failure) => {
    let failing = false;
    const intervals = vi.spyOn(globalThis, "setInterval");
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      if (String(url).includes("/network/catalog")) return failing
        ? failure === "http" ? new Response("", { status: 503 })
          : Response.json({ status: "unavailable", areas: [], lines: [] })
        : Response.json(network);
      if (String(url).includes("/network/routes")) return new Response("", { status: 404 });
      return Response.json(snapshot());
    });
    render(<App />);
    fireEvent.click(await screen.findByLabelText(/2 · Norte/));
    expect(screen.getByTestId("map")).toHaveTextContent(/^100,110$/);
    const refresh = intervals.mock.calls.find(([, delay]) => delay === 60_000)?.[0];
    expect(typeof refresh).toBe("function");
    failing = true;
    await act(async () => { if (typeof refresh === "function") refresh(); });
    expect(screen.getByTestId("map")).toHaveTextContent(/^100,110,200$/);
    expect(screen.getByText(/Filtro por área suspenso/)).toBeInTheDocument();
    expect(screen.getByTestId("routes")).toBeEmptyDOMElement();
    // Continuar refinando linha/sentido independe das associações do GTFS.
    fireEvent.click(screen.getByRole("button", { name: /5015-10/ }));
    fireEvent.change(screen.getByLabelText("Sentido da linha 5015-10"), { target: { value: "2" } });
    expect(screen.getByTestId("map")).toHaveTextContent(/^110$/);
    failing = false;
    await act(async () => { if (typeof refresh === "function") refresh(); });
    expect(screen.queryByText(/Filtro por área suspenso/)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/2 · Norte/)).toBeChecked();
    expect(screen.getByTestId("map")).toHaveTextContent(/^110$/);
    failing = true;
    await act(async () => { if (typeof refresh === "function") refresh(); });
    expect(screen.getByText(/Filtro por área suspenso/)).toBeInTheDocument();
    expect(screen.getByLabelText("Sentido da linha 5015-10")).toHaveValue("2");
    expect(screen.getByTestId("map")).toHaveTextContent(/^110$/);
  });

  it("shows complete GTFS provenance with an explicit timezone", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) =>
      new Response(JSON.stringify(String(url).includes("/network/catalog")
        ? { ...network, source: "https://example.org/gtfs.zip",
            captured_at: "2026-11-20T15:42:17Z" }
        : snapshot())),
    );
    render(<App />);
    fireEvent.click(screen.getByText("Legenda e fontes"));
    expect(await screen.findByText(network.version)).toBeVisible();
    expect(screen.getByText(/Fonte GTFS:/)).toHaveTextContent("https://example.org/gtfs.zip");
    expect(screen.getByText(/Fonte GTFS:/)).toHaveTextContent("20/11/2026, 12:42:17");
    expect(screen.getByText(/Fonte GTFS:/)).toHaveTextContent("America/Sao_Paulo");
  });

  it("removes GTFS associations after a catalog request fails, keeping positions", async () => {
    let failing = false;
    const intervals = vi.spyOn(globalThis, "setInterval");
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      if (String(url).includes("/network/catalog")) {
        return failing ? new Response("", { status: 503 })
          : new Response(JSON.stringify(network));
      }
      return new Response(JSON.stringify(snapshot()));
    });
    render(<App />);
    await screen.findByText("Catálogo de demonstração · dados sintéticos");
    expect(screen.getByTestId("map")).toHaveTextContent("100");
    failing = true;
    const refresh = intervals.mock.calls.find(([, delay]) => delay === 60_000)?.[0];
    expect(typeof refresh).toBe("function");
    await act(async () => { if (typeof refresh === "function") refresh(); });
    fireEvent.click(screen.getByText("Legenda e fontes"));
    expect(screen.getByText(/Referência GTFS indisponível/)).toBeVisible();
    expect(screen.queryByText(network.version)).not.toBeInTheDocument();
    expect(screen.getByTestId("map")).toHaveTextContent("100");
  });

  it("preserves loaded routes when area filters keep the same effective IDs", async () => {
    const fetch = respondWithRoutes();
    render(<App />);
    await screen.findByText("Atualização ativa");
    fireEvent.click(screen.getByRole("button", { name: /5015-10/ }));
    await waitFor(() =>
      expect(screen.getByTestId("routes")).toHaveTextContent(/^1,11$/),
    );
    const routeCalls = () =>
      fetch.mock.calls.filter(([url]) =>
        String(url).includes("/network/routes/"),
      ).length;
    expect(routeCalls()).toBe(2);
    fireEvent.click(screen.getByLabelText(/2 · Norte/));
    expect(screen.getByTestId("routes")).toHaveTextContent(/^1,11$/);
    fireEvent.click(screen.getByLabelText(/8 · Oeste/));
    expect(screen.getByTestId("routes")).toHaveTextContent(/^1,11$/);
    fireEvent.click(screen.getByLabelText(/8 · Oeste/));
    fireEvent.click(screen.getByLabelText(/2 · Norte/));
    expect(screen.getByTestId("routes")).toHaveTextContent(/^1,11$/);
    expect(routeCalls()).toBe(2);
  });
  it("preserves routes when changing sense leaves the effective IDs unchanged", async () => {
    respondWithRoutes();
    render(<App />);
    await screen.findByText("Atualização ativa");
    fireEvent.click(screen.getByRole("button", { name: /701A-10/ }));
    await waitFor(() =>
      expect(screen.getByTestId("routes")).toHaveTextContent(/^2$/),
    );
    fireEvent.change(screen.getByLabelText("Sentido da linha 701A-10"), {
      target: { value: "1" },
    });
    expect(screen.getByTestId("routes")).toHaveTextContent(/^2$/);
    fireEvent.change(screen.getByLabelText("Sentido da linha 701A-10"), {
      target: { value: "both" },
    });
    expect(screen.getByTestId("routes")).toHaveTextContent(/^2$/);
  });
  it("removes excluded geometry and restores routes when effective IDs change", async () => {
    respondWithRoutes();
    render(<App />);
    await screen.findByText("Atualização ativa");
    fireEvent.click(screen.getByRole("button", { name: /5015-10/ }));
    await waitFor(() =>
      expect(screen.getByTestId("routes")).toHaveTextContent(/^1,11$/),
    );
    fireEvent.change(screen.getByLabelText("Sentido da linha 5015-10"), {
      target: { value: "2" },
    });
    expect(screen.getByTestId("routes")).not.toHaveTextContent(/(^|,)1(,|$)/);
    await waitFor(() =>
      expect(screen.getByTestId("routes")).toHaveTextContent(/^11$/),
    );
    fireEvent.click(screen.getByLabelText(/8 · Oeste/));
    expect(screen.getByTestId("routes")).toBeEmptyDOMElement();
    fireEvent.click(screen.getByLabelText(/8 · Oeste/));
    await waitFor(() =>
      expect(screen.getByTestId("routes")).toHaveTextContent(/^11$/),
    );
    fireEvent.click(screen.getByLabelText("Remover linha 5015-10"));
    expect(screen.getByTestId("routes")).toBeEmptyDOMElement();
  });

  it("starts with the network, accumulates lines and selects senses", async () => {
    respond();
    render(<App />);
    await screen.findByText("Atualização ativa");
    expect(screen.getByTestId("map")).toHaveTextContent("100,110,200");
    const summary = within(
      screen.getByRole("region", { name: "Resumo da área visível" }),
    );
    expect(summary.getByText("33%")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /5015-10/ }));
    expect(screen.getByTestId("map")).toHaveTextContent("100,110");
    expect(screen.getByTestId("map")).not.toHaveTextContent("200");
    fireEvent.click(screen.getByRole("button", { name: /701A-10/ }));
    expect(screen.getByTestId("map")).toHaveTextContent("100,110,200");
    fireEvent.change(screen.getByLabelText("Sentido da linha 5015-10"), {
      target: { value: "2" },
    });
    expect(screen.getByTestId("map")).toHaveTextContent("110,200");
    expect(screen.getByTestId("map")).not.toHaveTextContent("100");
    fireEvent.click(screen.getByLabelText("Remover linha 5015-10"));
    expect(screen.getByTestId("map")).toHaveTextContent("200");
    fireEvent.click(screen.getByText("Limpar filtros"));
    expect(screen.getByTestId("map")).toHaveTextContent("100,110,200");
  });
  it("combines areas and lines, and changes only visible totals when panning", async () => {
    respond();
    render(<App />);
    await screen.findByText("Atualização ativa");
    fireEvent.click(screen.getByText("Mover mapa de teste"));
    const summary = within(
      screen.getByRole("region", { name: "Resumo da área visível" }),
    );
    expect(summary.getByText("100%")).toBeInTheDocument();
    expect(screen.getByTestId("map")).toHaveTextContent("100,110,200");
    fireEvent.click(screen.getByLabelText(/8 · Oeste/));
    expect(screen.getByTestId("map")).toHaveTextContent("200");
    expect(screen.getByTestId("map")).not.toHaveTextContent("100");
    fireEvent.click(screen.getByLabelText(/2 · Norte/));
    expect(screen.getByTestId("map")).toHaveTextContent("100,110,200");
  });
  it("keeps positions usable when the catalog is unavailable", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) =>
      String(url).includes("/network/")
        ? Promise.reject(new Error("offline"))
        : new Response(JSON.stringify(snapshot())),
    );
    render(<App />);
    await screen.findByText("Atualização ativa");
    expect(screen.getByTestId("map")).toHaveTextContent("100,110,200");
    expect(
      screen.getByText(/Cores e percursos planejados indisponíveis/),
    ).toBeInTheDocument();
  });
  it("does not display expired positions as live", async () => {
    respond(61);
    render(<App />);
    await screen.findByText("As posições expiraram");
    expect(screen.getByTestId("map")).toBeEmptyDOMElement();
  });
  it("shows source failures honestly", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("offline"));
    render(<App />);
    await screen.findByText("Não foi possível atualizar");
    expect(screen.getByTestId("map")).toBeEmptyDOMElement();
  });
  it("expires retained positions while retries fail", async () => {
    vi.useFakeTimers();
    respond();
    render(<App />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(screen.getByTestId("map")).toHaveTextContent("100");
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("offline"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(61000);
    });
    expect(screen.getByTestId("map")).toBeEmptyDOMElement();
    expect(screen.getByText("As posições expiraram")).toBeInTheDocument();
  });
});

describe("Visualização e detalhes", () => {
  it("switches modes, persists preferences, and restores defaults without changing filters", async () => {
    respondWithRoutes();
    const first = render(<App />);
    await screen.findByRole("button", { name: /5015-10/ });
    fireEvent.click(screen.getByRole("button", { name: /5015-10/ }));
    fireEvent.click(screen.getByText("Mais opções", { exact: true }));
    fireEvent.click(screen.getByRole("button", { name: "Misto" }));
    fireEvent.change(
      screen.getByRole("slider", { name: /Tamanho dos ônibus/ }),
      { target: { value: "18" } },
    );
    fireEvent.change(
      screen.getByRole("slider", { name: /Tamanho geral dos grupos/ }),
      { target: { value: "150" } },
    );
    expect(screen.getByTestId("visual-mode")).toHaveTextContent("mixed:18:1.5");
    expect(screen.getByTestId("map")).toHaveTextContent("100,110");
    fireEvent.click(screen.getByRole("button", { name: "Calor" }));
    expect(
      screen.queryByRole("slider", { name: /Tamanho geral dos grupos/ }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/Inclui GPS antigo/)).toBeInTheDocument();
    first.unmount();
    render(<App />);
    expect(screen.getByTestId("visual-mode")).toHaveTextContent(
      "density:18:1.5",
    );
    fireEvent.click(screen.getByRole("button", { name: "Restaurar padrões" }));
    expect(screen.getByTestId("visual-mode")).toHaveTextContent("clusters:9:1");
  });
  it("opens details above filters, keeps selection during navigation, and reports filtering out", async () => {
    respond();
    render(<App />);
    await screen.findByRole("button", { name: /5015-10/ });
    fireEvent.click(
      screen.getByRole("button", { name: "Selecionar ônibus no mapa" }),
    );
    expect(
      screen.getByRole("region", { name: "Detalhes da seleção" }),
    ).toHaveTextContent("Ônibus 100");
    fireEvent.click(
      screen.getByRole("button", { name: "Mover mapa de teste" }),
    );
    expect(
      screen.getByRole("region", { name: "Detalhes da seleção" }),
    ).toHaveTextContent("Ônibus 100");
    fireEvent.click(screen.getByRole("button", { name: /701A-10/ }));
    expect(
      within(
        screen.getByRole("region", { name: "Detalhes da seleção" }),
      ).getByRole("status"),
    ).toHaveTextContent("deixou de estar disponível");
    fireEvent.click(screen.getByRole("button", { name: "Fechar detalhes" }));
    expect(
      screen.queryByRole("region", { name: "Detalhes da seleção" }),
    ).not.toBeInTheDocument();
  });
});

it("keeps the map usable when saving visual preferences is blocked", async () => {
  vi.spyOn(window.localStorage, "setItem").mockImplementation(() => {
    throw new Error("quota");
  });
  respond();
  render(<App />);
  await screen.findByRole("button", { name: /5015-10/ });
  fireEvent.click(screen.getByRole("button", { name: "Calor" }));
  expect(screen.getByTestId("visual-mode")).toHaveTextContent("density:9:1");
  expect(screen.getByTestId("map")).toHaveTextContent("100");
});

it("shows a simple mode choice and only the relevant controls, persisting intensity and size style", async () => {
  respond();
  const first = render(<App />);
  await screen.findByText("Atualização ativa");
  const panel = within(screen.getByRole("region", { name: "Visualização" }));
  expect(
    panel.getByRole("button", { name: "Grupos", pressed: true }),
  ).toBeVisible();
  expect(panel.getByText("Mais opções").closest("details")).not.toHaveAttribute(
    "open",
  );
  fireEvent.click(panel.getByRole("button", { name: "Calor" }));
  expect(panel.getAllByRole("slider")).toHaveLength(1);
  expect(
    panel.queryByRole("button", { name: "Mesmo tamanho" }),
  ).not.toBeInTheDocument();
  fireEvent.change(
    panel.getByRole("slider", { name: "Intensidade do calor" }),
    { target: { value: "175" } },
  );
  fireEvent.click(panel.getByRole("button", { name: "Misto" }));
  fireEvent.click(panel.getByRole("button", { name: "Mesmo tamanho" }));
  expect(screen.getByTestId("map")).toHaveTextContent("100,110,200");
  first.unmount();
  render(<App />);
  expect(
    screen.getByRole("button", { name: "Misto", pressed: true }),
  ).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Mesmo tamanho", pressed: true }),
  ).toBeVisible();
  expect(
    screen.getByRole("slider", { name: "Intensidade do calor" }),
  ).toHaveValue("175");
  fireEvent.click(screen.getByRole("button", { name: "Restaurar padrões" }));
  expect(
    screen.getByRole("button", { name: "Grupos", pressed: true }),
  ).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Por quantidade", pressed: true }),
  ).toBeVisible();
  expect(
    screen.getByText("Mais opções").closest("details"),
  ).not.toHaveAttribute("open");
});

describe("Foco dos percursos", () => {
  it("focuses additions, switches focus without requests or filter changes, and falls back on removal", async () => {
    const fetch = respondWithRoutes();
    render(<App />);
    await screen.findByRole("button", { name: /^5015-10/ });
    fireEvent.click(screen.getByRole("button", { name: /^5015-10/ }));
    await waitFor(() =>
      expect(screen.getByTestId("route-focus")).toHaveTextContent("5015-10"),
    );
    fireEvent.click(screen.getByRole("button", { name: /^701A-10/ }));
    await waitFor(() =>
      expect(screen.getByTestId("route-focus")).toHaveTextContent("701A-10"),
    );
    const calls = fetch.mock.calls.length;
    fireEvent.click(
      screen.getByRole("button", { name: "Destacar linha 5015-10" }),
    );
    expect(screen.getByTestId("route-focus")).toHaveTextContent("5015-10");
    expect(screen.getByTestId("map")).toHaveTextContent("100,110,200");
    fireEvent.click(screen.getByRole("button", { name: "Destacar todas" }));
    expect(screen.getByTestId("route-focus")).toHaveTextContent("all");
    fireEvent.click(
      screen.getByRole("button", { name: "Clicar percurso único" }),
    );
    expect(screen.getByTestId("route-focus")).toHaveTextContent("5015-10");
    expect(fetch.mock.calls.length).toBe(calls);
    fireEvent.click(
      screen.getByRole("button", { name: "Remover linha 5015-10" }),
    );
    expect(screen.getByTestId("route-focus")).toHaveTextContent("701A-10");
    fireEvent.click(
      screen.getByRole("button", { name: "Remover linha 701A-10" }),
    );
    expect(
      screen.queryByRole("region", { name: "Destaque dos percursos" }),
    ).not.toBeInTheDocument();
  });
  it("asks in the panel for overlapping lines and closes vehicle details", async () => {
    respondWithRoutes();
    render(<App />);
    await screen.findByRole("button", { name: /^5015-10/ });
    fireEvent.click(screen.getByRole("button", { name: /^5015-10/ }));
    fireEvent.click(screen.getByRole("button", { name: /^701A-10/ }));
    await waitFor(() =>
      expect(screen.getByTestId("route-focus")).toHaveTextContent("701A-10"),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Selecionar ônibus no mapa" }),
    );
    expect(
      screen.getByRole("region", { name: "Detalhes da seleção" }),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Clicar trecho compartilhado" }),
    );
    expect(
      screen.queryByRole("region", { name: "Detalhes da seleção" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Linhas neste trecho")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Escolher linha 5015-10" }),
    );
    expect(screen.getByTestId("route-focus")).toHaveTextContent("5015-10");
    expect(screen.queryByText("Linhas neste trecho")).not.toBeInTheDocument();
    expect(screen.getByTestId("map")).toHaveTextContent("100,110,200");
  });
  it("keeps available focus when the last added line has no geometry", async () => {
    const fetch = respondWithRoutes();
    const original = fetch.getMockImplementation()!;
    fetch.mockImplementation(async (...args) =>
      String(args[0]).includes("/network/routes/2?")
        ? new Response("{}", { status: 404 })
        : original(...args),
    );
    render(<App />);
    await screen.findByRole("button", { name: /^5015-10/ });
    fireEvent.click(screen.getByRole("button", { name: /^5015-10/ }));
    await waitFor(() =>
      expect(screen.getByTestId("route-focus")).toHaveTextContent("5015-10"),
    );
    fireEvent.click(screen.getByRole("button", { name: /^701A-10/ }));
    await screen.findByText(/Percurso planejado indisponível em 1 sentidos/);
    expect(screen.getByTestId("route-focus")).toHaveTextContent("5015-10");
    expect(
      screen.getByRole("button", { name: "Destacar linha 701A-10" }),
    ).toBeDisabled();
  });
});

it("shows area routes without selecting lines, focuses them without filtering, and reuses loaded geometry", async () => {
  const fetch = respondWithRoutes();
  render(<App />);
  await screen.findByText("Atualização ativa");
  expect(screen.getByTestId("routes")).toBeEmptyDOMElement();
  fireEvent.click(screen.getByLabelText(/2 · Norte/));
  await waitFor(() =>
    expect(screen.getByTestId("routes")).toHaveTextContent(/^1,11$/),
  );
  expect(
    screen.getByText(/Percursos das áreas · 1 linhas/),
  ).toBeInTheDocument();
  expect(
    screen.queryByLabelText("Linhas selecionadas"),
  ).not.toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Clicar percurso único" }),
  );
  expect(screen.getByTestId("route-focus")).toHaveTextContent("5015-10");
  expect(screen.getByTestId("map")).toHaveTextContent("100,110");
  fireEvent.click(screen.getByLabelText(/8 · Oeste/));
  await waitFor(() =>
    expect(screen.getByTestId("routes")).toHaveTextContent(/^1,11,2$/),
  );
  const routeCalls = () =>
    fetch.mock.calls.filter(([url]) => String(url).includes("/network/routes/"))
      .length;
  expect(routeCalls()).toBe(3);
  fireEvent.click(screen.getByLabelText(/2 · Norte/));
  expect(screen.getByTestId("routes")).toHaveTextContent(/^2$/);
  fireEvent.click(screen.getByLabelText(/2 · Norte/));
  await waitFor(() =>
    expect(screen.getByTestId("routes")).toHaveTextContent(/^2,1,11$|^1,11,2$/),
  );
  expect(routeCalls()).toBe(3);
  fireEvent.click(screen.getByRole("button", { name: /^5015-10/ }));
  expect(screen.getByTestId("routes")).toHaveTextContent(/^1,11$/);
  expect(screen.getByTestId("map")).toHaveTextContent("100,110");
  fireEvent.change(screen.getByLabelText("Sentido da linha 5015-10"), {
    target: { value: "2" },
  });
  expect(screen.getByTestId("routes")).toHaveTextContent(/^11$/);
});
it("does not infer routes for an area with no catalog mapping", async () => {
  respond();
  render(<App />);
  await screen.findByText("Atualização ativa");
  fireEvent.click(screen.getByLabelText(/Área não identificada/));
  expect(screen.getByTestId("routes")).toBeEmptyDOMElement();
  expect(screen.getByText(/Nenhum percurso associado/)).toBeInTheDocument();
});

it.each(["empty", "expired", "offline"])(
  "fits available area routes when positions are %s",
  async (state) => {
    const fetch = respondWithRoutes();
    const original = fetch.getMockImplementation()!;
    fetch.mockImplementation(async (...args) => {
      if (String(args[0]).includes("/network/")) return original(...args);
      if (state === "offline") throw new Error("positions unavailable");
      const payload = snapshot(state === "expired" ? 61 : 0);
      return new Response(
        JSON.stringify(
          state === "empty" ? { ...payload, vehicles: [], lines: [] } : payload,
        ),
      );
    });
    render(<App />);
    fireEvent.click(await screen.findByLabelText(/2 · Norte/));
    await waitFor(() =>
      expect(screen.getByTestId("routes")).toHaveTextContent(/^1,11$/),
    );
    expect(screen.getByTestId("map")).toBeEmptyDOMElement();
    const fit = screen.getByRole("button", { name: "Enquadrar seleção" });
    expect(fit).toBeEnabled();
    expect(screen.getByTestId("fit-request")).toHaveTextContent("0");
    fireEvent.click(fit);
    expect(screen.getByTestId("fit-request")).toHaveTextContent("1");
  },
);
it("keeps fitting disabled without positions or drawable routes", async () => {
  const fetch = respondWithRoutes();
  const original = fetch.getMockImplementation()!;
  fetch.mockImplementation(async (...args) => {
    const url = String(args[0]);
    if (url.includes("/network/routes/"))
      return new Response("{}", { status: 404 });
    if (url.includes("/network/catalog")) return original(...args);
    return new Response(
      JSON.stringify({ ...snapshot(), vehicles: [], lines: [] }),
    );
  });
  render(<App />);
  fireEvent.click(await screen.findByLabelText(/2 · Norte/));
  await screen.findByText(/0 linhas exibidas/);
  expect(screen.getByTestId("routes")).toBeEmptyDOMElement();
  expect(
    screen.getByRole("button", { name: "Enquadrar seleção" }),
  ).toBeDisabled();
});
