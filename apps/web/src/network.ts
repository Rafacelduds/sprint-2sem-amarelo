import type { Vehicle } from "./api/positions";
import type { NetworkCatalog } from "./api/network";
export type Bounds = {
  north: number;
  south: number;
  east: number;
  west: number;
};
export type Selection = Record<string, number | "both">;
export type AreaStyle = { id: number; name: string; color: string };
export type LineStyle = { area: number | null; color: string };
export const UNKNOWN_COLOR = "#78838b";
export const EMPTY_STYLES = new Map<number, LineStyle>();
export function lineStyles(catalog: NetworkCatalog | null) {
  return new Map<number, LineStyle>(
    (catalog?.lines ?? []).map((l) => [
      l.line_id,
      { area: l.area_id ?? null, color: l.color ?? UNKNOWN_COLOR },
    ]),
  );
}
export function gpsQuality(
  bus: Vehicle,
  now: number,
): "recent" | "old" | "unknown" {
  if (!bus.gps_at) return "unknown";
  const age = now - Date.parse(bus.gps_at);
  if (!Number.isFinite(age) || age < 0) return "unknown";
  return age <= 60_000 ? "recent" : "old";
}
export function inBounds(bus: Vehicle, bounds: Bounds | null) {
  return (
    !bounds ||
    (bus.latitude <= bounds.north &&
      bus.latitude >= bounds.south &&
      bus.longitude >= bounds.west &&
      bus.longitude <= bounds.east)
  );
}
export function matchesFilters(
  bus: Vehicle,
  selection: Selection,
  areas: string[],
  styles: Map<number, LineStyle>,
) {
  const area = String(styles.get(bus.line_id)?.area ?? "unknown");
  if (areas.length && !areas.includes(area)) return false;
  const selected = selection[bus.line];
  return (
    Object.keys(selection).length === 0 ||
    selected === "both" ||
    selected === bus.direction
  );
}
