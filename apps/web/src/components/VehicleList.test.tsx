import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import VehicleList from "./VehicleList";
import type { Vehicle } from "../api/positions";
afterEach(cleanup);
it("creates no hidden rows and limits each open page to 100 vehicles", async () => {
  const vehicles: Vehicle[] = Array.from({ length: 250 }, (_, i) => ({
    id: String(i),
    line_id: 1,
    line: "X",
    direction: 1,
    destination: "Terminal",
    latitude: -23,
    longitude: -46,
    gps_at: null,
    accessible: null,
  }));
  const { container } = render(<VehicleList vehicles={vehicles} />);
  expect(container.querySelectorAll("tbody tr")).toHaveLength(0);
  const details = container.querySelector("details")!;
  await act(async () => {
    details.open = true;
    fireEvent(details, new Event("toggle"));
  });
  expect(container.querySelectorAll("tbody tr")).toHaveLength(100);
  fireEvent.click(screen.getByText("Próxima"));
  expect(container.querySelector("tbody tr td")?.textContent).toBe("100");
  fireEvent.click(screen.getByText("Próxima"));
  expect(container.querySelectorAll("tbody tr")).toHaveLength(50);
  expect(screen.getByText("Próxima")).toBeDisabled();
  await act(async () => {
    details.open = false;
    fireEvent(details, new Event("toggle"));
  });
  expect(container.querySelectorAll("tbody tr")).toHaveLength(0);
});
