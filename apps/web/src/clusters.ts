import Supercluster, {
  type ClusterFeature,
  type PointFeature,
} from "supercluster";
import type { Vehicle } from "./api/positions";
import { UNKNOWN_COLOR, type LineStyle } from "./network";
export const MAP_MAX_ZOOM = 19;
export const CLUSTER_PAGE_SIZE = 10;
export type BusPoint = PointFeature<{ bus: Vehicle }>;
export type ColorCounts = Record<string, number>;
export type ClusterColors = { colors: ColorCounts };
export type BusCluster = ClusterFeature<ClusterColors>;
export type MapPoint = BusPoint | BusCluster;
export type BusIndex = Supercluster<{ bus: Vehicle }, ClusterColors>;
export type GroupSelection = { index: BusIndex; id: number; total: number };
export function isCluster(point: MapPoint): point is BusCluster {
  return "cluster" in point.properties && point.properties.cluster === true;
}
export function createBusIndex(
  vehicles: Vehicle[],
  styles = new Map<number, LineStyle>(),
): BusIndex {
  return new Supercluster<{ bus: Vehicle }, ClusterColors>({
    map: ({ bus }) => ({
      colors: {
        [(styles.get(bus.line_id)?.color ?? UNKNOWN_COLOR).toUpperCase()]: 1,
      },
    }),
    reduce: (accumulated, properties) => {
      // Supercluster shallow-clones aggregates; detach the histogram before reducing.
      const colors = { ...accumulated.colors };
      for (const [color, count] of Object.entries(properties.colors))
        colors[color] = (colors[color] ?? 0) + count;
      accumulated.colors = colors;
    },
    radius: 96,
    extent: 512,
    maxZoom: MAP_MAX_ZOOM,
    minPoints: 2,
  }).load(
    vehicles.map((bus) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [bus.longitude, bus.latitude] },
      properties: { bus },
    })),
  );
}
export function clusterDiameter(count: number) {
  return count < 10 ? 24 : count < 100 ? 28 : 32;
}
export function clusterPage(index: BusIndex, id: number, page: number) {
  return index
    .getLeaves(id, CLUSTER_PAGE_SIZE, page * CLUSTER_PAGE_SIZE)
    .map((point) => point.properties.bus);
}

export function colorSegments(
  colors: ColorCounts,
  composition: "proportional" | "equal",
) {
  const entries = Object.entries(colors)
    .filter(([, count]) => count > 0)
    .sort(([a], [b]) => {
      if (a === UNKNOWN_COLOR.toUpperCase()) return 1;
      if (b === UNKNOWN_COLOR.toUpperCase()) return -1;
      return a.localeCompare(b);
    });
  const total = entries.reduce((sum, [, count]) => sum + count, 0);
  let end = 0;
  return entries.map(([color, count]) => {
    const start = end;
    end +=
      composition === "equal" ? 100 / entries.length : (count / total) * 100;
    return { color, count, start, end };
  });
}
export function groupGradient(
  colors: ColorCounts,
  composition: "proportional" | "equal",
) {
  const segments = colorSegments(colors, composition);
  return segments.length
    ? `conic-gradient(${segments.map((s) => `${s.color} ${s.start}% ${s.end}%`).join(",")})`
    : UNKNOWN_COLOR;
}
