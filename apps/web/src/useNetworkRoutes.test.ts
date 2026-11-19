import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { getRoute, type RouteCollection } from "./api/network";
import { useNetworkRoutes } from "./useNetworkRoutes";
vi.mock("./api/network", () => ({ getRoute: vi.fn() }));
const fetchRoute = vi.mocked(getRoute);
const version = "a".repeat(64);
function route(id: number, v = version): RouteCollection {
  return {
    type: "FeatureCollection",
    version: v,
    captured_at: "2026-11-19T12:00:00Z",
    synthetic: true,
    features: [
      {
        type: "Feature",
        geometry: {
          type: "MultiLineString",
          coordinates: [
            [
              [-46, -23],
              [-46.1, -23.1],
            ],
          ],
        },
        properties: {
          line_id: id,
          label: `TEST${id}`,
          direction: 1,
          destination: "Terminal",
          route_id: String(id),
          direction_id: "0",
          match_source: "Fixture sintética",
        },
      },
    ],
  };
}
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});
it("loads progressively with at most four in-flight requests", async () => {
  const pending: (() => void)[] = [];
  let active = 0,
    maximum = 0;
  fetchRoute.mockImplementation(
    (id) =>
      new Promise((resolve) => {
        active++;
        maximum = Math.max(maximum, active);
        pending.push(() => {
          active--;
          resolve(route(id));
        });
      }),
  );
  const { result } = renderHook(() =>
    useNetworkRoutes(
      Array.from({ length: 12 }, (_, i) => i + 1),
      version,
      0,
    ),
  );
  await waitFor(() => expect(fetchRoute).toHaveBeenCalledTimes(4));
  await act(async () => {
    pending.splice(0).forEach((resolve) => resolve());
  });
  await waitFor(() => expect(result.current.completed).toBe(4));
  expect(result.current.routes).toHaveLength(4);
  expect(result.current.loading).toBe(true);
  await act(async () => {
    pending.splice(0).forEach((resolve) => resolve());
  });
  await waitFor(() => expect(fetchRoute).toHaveBeenCalledTimes(12));
  await act(async () => {
    pending.splice(0).forEach((resolve) => resolve());
  });
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.routes).toHaveLength(12);
  expect(maximum).toBe(4);
});
it("reuses geometry across area changes and separates GTFS versions", async () => {
  fetchRoute.mockImplementation(async (id, v) => route(id, v));
  const { result, rerender } = renderHook(
    ({ ids, v }) => useNetworkRoutes(ids, v, 0),
    { initialProps: { ids: [1, 2, 3], v: version } },
  );
  await waitFor(() => expect(result.current.completed).toBe(3));
  rerender({ ids: [1, 3], v: version });
  await waitFor(() => expect(result.current.completed).toBe(2));
  expect(fetchRoute).toHaveBeenCalledTimes(3);
  rerender({ ids: [1, 3, 4], v: version });
  await waitFor(() => expect(result.current.completed).toBe(3));
  expect(fetchRoute).toHaveBeenCalledTimes(4);
  rerender({ ids: [1, 3, 4], v: "b".repeat(64) });
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(fetchRoute).toHaveBeenCalledTimes(7);
  expect(result.current.routes.every((r) => r.version === "b".repeat(64))).toBe(
    true,
  );
});
it("retries only unavailable routes and rejects a response from a different version", async () => {
  fetchRoute.mockImplementation(async (id) =>
    id === 2 ? { ...route(id), version: "b".repeat(64) } : route(id),
  );
  const { result, rerender } = renderHook(
    ({ retry }) => useNetworkRoutes([1, 2], version, retry),
    { initialProps: { retry: 0 } },
  );
  await waitFor(() => expect(result.current.missing).toEqual([2]));
  expect(result.current.routes).toHaveLength(1);
  fetchRoute.mockImplementation(async (id) => route(id));
  rerender({ retry: 1 });
  await waitFor(() => expect(result.current.completed).toBe(2));
  await waitFor(() => expect(result.current.missing).toEqual([]));
  expect(fetchRoute).toHaveBeenCalledTimes(3);
});
it("aborts obsolete loads and does not publish results from the previous area", async () => {
  const signals: AbortSignal[] = [];
  const pending: (() => void)[] = [];
  fetchRoute.mockImplementation(
    (id, _v, signal) =>
      new Promise((resolve) => {
        signals.push(signal);
        pending.push(() => resolve(route(id)));
      }),
  );
  const { result, rerender } = renderHook(
    ({ ids }) => useNetworkRoutes(ids, version, 0),
    { initialProps: { ids: [1, 2, 3, 4, 5] } },
  );
  await waitFor(() => expect(fetchRoute).toHaveBeenCalledTimes(4));
  rerender({ ids: [] });
  expect(signals.every((s) => s.aborted)).toBe(true);
  await act(async () => {
    pending.forEach((resolve) => resolve());
  });
  expect(result.current.routes).toEqual([]);
  expect(result.current.loading).toBe(false);
  expect(fetchRoute).toHaveBeenCalledTimes(4);
});

it("keeps loaded geometry stable across unrelated clock renders", async () => {
  fetchRoute.mockImplementation(async (id) => route(id));
  const { result, rerender } = renderHook(
    ({ ids }) => useNetworkRoutes(ids, version, 0),
    { initialProps: { ids: [1, 2], tick: 0 } },
  );
  await waitFor(() => expect(result.current.loading).toBe(false));
  const loaded = result.current.routes;
  rerender({ ids: [1, 2], tick: 1 });
  expect(result.current.routes).toBe(loaded);
  expect(fetchRoute).toHaveBeenCalledTimes(2);
});
