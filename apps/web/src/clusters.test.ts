import { describe, expect, it } from "vitest";
import {
  createBusIndex,
  isCluster,
  clusterDiameter,
  clusterPage,
  MAP_MAX_ZOOM,
} from "./clusters";
import { matchesFilters } from "./network";
import type { Vehicle } from "./api/positions";
const world: [number, number, number, number] = [-180, -85, 180, 85];
function bus(id: number, lat = -23.55, lon = -46.63): Vehicle {
  return {
    id: String(id),
    line_id: id % 2 ? 1 : 2,
    line: id % 2 ? "A" : "B",
    direction: id % 3 ? 1 : 2,
    destination: "Terminal",
    latitude: lat,
    longitude: lon,
    gps_at: null,
    accessible: null,
  };
}
describe("Agrupamentos espaciais", () => {
  it("preserves all observations and splits neighboring vehicles as zoom increases", () => {
    const index = createBusIndex([
      bus(1),
      bus(2, -23.551, -46.631),
      bus(3, -23.552, -46.632),
    ]);
    const low = index.getClusters(world, 10);
    expect(low).toHaveLength(1);
    expect(isCluster(low[0])).toBe(true);
    if (!isCluster(low[0])) throw new Error("Expected cluster");
    expect(low[0].properties.point_count).toBe(3);
    expect(
      index.getClusterExpansionZoom(low[0].properties.cluster_id),
    ).toBeGreaterThan(10);
    const high = index.getClusters(world, MAP_MAX_ZOOM);
    expect(high).toHaveLength(3);
    expect(high.every((p) => !isCluster(p))).toBe(true);
  });
  it("groups only positions passing the combined filters, even across area and line identities", () => {
    const buses = Array.from({ length: 12 }, (_, i) => bus(i));
    const styles = new Map([
      [1, { area: 2, color: "#22599B" }],
      [2, { area: 8, color: "#DE7D30" }],
    ]);
    const filtered = buses.filter((b) =>
      matchesFilters(b, { A: "both", B: 1 }, ["2", "8"], styles),
    );
    const index = createBusIndex(filtered);
    const points = index.getClusters(world, 12);
    expect(points).toHaveLength(1);
    expect(isCluster(points[0])).toBe(true);
    if (!isCluster(points[0])) throw new Error("Expected cluster");
    expect(points[0].properties.point_count).toBe(filtered.length);
    const leaves = index
      .getLeaves(points[0].properties.cluster_id, Infinity)
      .map((p) => p.properties.bus.id);
    expect(leaves.sort()).toEqual(filtered.map((b) => b.id).sort());
    expect(index.getClusters([-40, -20, -39, -19], 12)).toEqual([]);
  });
  it("retains coincident vehicles at maximum zoom and paginates without losing or repeating vehicles", () => {
    const buses = Array.from({ length: 23 }, (_, i) => bus(i));
    const index = createBusIndex(buses);
    const point = index.getClusters(world, MAP_MAX_ZOOM)[0];
    if (!isCluster(point)) throw new Error("Expected cluster at max zoom");
    const id = point.properties.cluster_id;
    expect(index.getClusterExpansionZoom(id)).toBe(MAP_MAX_ZOOM + 1);
    const pages = [
      clusterPage(index, id, 0),
      clusterPage(index, id, 1),
      clusterPage(index, id, 2),
    ];
    expect(pages.map((p) => p.length)).toEqual([10, 10, 3]);
    expect(new Set(pages.flat().map((b) => b.id)).size).toBe(23);
  });
  it("handles filtering to empty and keeps cluster diameters within 24–32 pixels", () => {
    expect(createBusIndex([]).getClusters(world, 12)).toEqual([]);
    for (const count of [2, 9, 10, 99, 100, 10000])
      expect(clusterDiameter(count)).toBeGreaterThanOrEqual(24);
    for (const count of [2, 9, 10, 99, 100, 10000])
      expect(clusterDiameter(count)).toBeLessThanOrEqual(32);
  });
  it("does not change the index when querying multiple viewports", () => {
    const index = createBusIndex(
      Array.from({ length: 10000 }, (_, i) =>
        bus(i, -23.5 + (i % 100) * 0.001, -46.7 + Math.floor(i / 100) * 0.001),
      ),
    );
    const before = index.getClusters(world, 10);
    for (let zoom = 10; zoom <= 19; zoom++)
      index.getClusters([-46.7, -23.5, -46.65, -23.45], zoom);
    expect(index.getClusters(world, 10)).toEqual(before);
    expect(
      before.reduce(
        (total, point) =>
          total + (isCluster(point) ? point.properties.point_count : 1),
        0,
      ),
    ).toBe(10000);
  });
});
