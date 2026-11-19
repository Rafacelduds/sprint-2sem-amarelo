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
  }: {
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
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
});
describe("Rede pública", () => {
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
    expect(screen.getByText(/Cores e percursos planejados indisponíveis/)).toBeInTheDocument();
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
