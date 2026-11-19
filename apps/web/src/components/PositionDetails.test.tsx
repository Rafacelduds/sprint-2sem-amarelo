import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import PositionDetails from "./PositionDetails";
import { createBusIndex, isCluster, MAP_MAX_ZOOM } from "../clusters";
import type { Vehicle } from "../api/positions";
afterEach(cleanup);
const buses: Vehicle[] = Array.from({ length: 23 }, (_, i) => ({
  id: String(i),
  line_id: 1,
  line: "701A-10",
  direction: 1,
  destination: "Terminal",
  latitude: -23.5,
  longitude: -46.6,
  gps_at: null,
  accessible: null,
}));
it("paginates coincident vehicles in the panel and selects an individual", () => {
  const index = createBusIndex(buses);
  const point = index.getClusters([-180, -85, 180, 85], MAP_MAX_ZOOM)[0];
  if (!isCluster(point)) throw new Error("Expected coincident cluster");
  const onSelect = vi.fn();
  render(
    <PositionDetails
      selectedId={null}
      vehicle={null}
      group={{ index, id: point.properties.cluster_id, total: 23 }}
      styles={new Map()}
      collectedAt={null}
      now={Date.now()}
      onSelect={onSelect}
      onClose={vi.fn()}
    />,
  );
  expect(screen.getAllByRole("listitem")).toHaveLength(10);
  fireEvent.click(screen.getByRole("button", { name: "Próxima" }));
  expect(screen.getByText("2 / 3")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Próxima" }));
  expect(screen.getAllByRole("listitem")).toHaveLength(3);
  expect(screen.getByRole("button", { name: "Próxima" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: /Ônibus 20/ }));
  expect(onSelect).toHaveBeenCalledWith("20");
});
it("updates selected information and reports an unavailable observation", () => {
  const props = {
    selectedId: "0",
    vehicle: buses[0],
    group: null,
    styles: new Map(),
    collectedAt: null,
    now: Date.now(),
    onSelect: vi.fn(),
    onClose: vi.fn(),
  };
  const { rerender } = render(<PositionDetails {...props} />);
  expect(
    screen.getByText("Horário desconhecido", { exact: false }),
  ).toBeInTheDocument();
  rerender(
    <PositionDetails
      {...props}
      vehicle={{ ...buses[0], destination: "Novo destino", accessible: true }}
    />,
  );
  expect(screen.getByText("Novo destino")).toBeInTheDocument();
  rerender(<PositionDetails {...props} vehicle={null} />);
  expect(screen.getByRole("status")).toHaveTextContent(
    "deixou de estar disponível",
  );
});
