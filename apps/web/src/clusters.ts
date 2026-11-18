import Supercluster, {
  type ClusterFeature,
  type PointFeature,
} from "supercluster";
import type { Vehicle } from "./api/positions";
export const MAP_MAX_ZOOM = 19;
export const CLUSTER_PAGE_SIZE = 10;
export type BusPoint = PointFeature<{ bus: Vehicle }>;
export type BusCluster = ClusterFeature<Record<string, never>>;
export type MapPoint = BusPoint | BusCluster;
export type BusIndex = Supercluster<{ bus: Vehicle }, Record<string, never>>;
export function isCluster(point: MapPoint): point is BusCluster {
  return "cluster" in point.properties && point.properties.cluster === true;
}
export function createBusIndex(vehicles: Vehicle[]): BusIndex {
  return new Supercluster<{ bus: Vehicle }, Record<string, never>>({
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
