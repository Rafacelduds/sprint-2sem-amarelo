import type { RouteCollection } from "./api/network";
export type Point = { x: number; y: number };
export type ProjectedSegment = { label: string; a: Point; b: Point };
export function availableRouteLabels(routes: RouteCollection[]) {
  return new Set(
    routes.flatMap((route) =>
      route.features
        .filter((feature) =>
          feature.geometry.coordinates.some((segment) => segment.length >= 2),
        )
        .map((feature) => feature.properties.label),
    ),
  );
}
export function effectiveRouteFocus(
  wanted: string | null,
  selected: string[],
  available: Set<string>,
) {
  if (wanted === null) return null;
  if (selected.includes(wanted) && available.has(wanted)) return wanted;
  return [...selected].reverse().find((label) => available.has(label)) ?? null;
}
export function projectRoutes(
  routes: RouteCollection[],
  project: (coordinate: [number, number]) => Point,
  size: Point,
  simplify: (points: Point[]) => Point[] = (points) => points,
): ProjectedSegment[] {
  const segments: ProjectedSegment[] = [];
  for (const route of routes)
    for (const feature of route.features)
      for (const path of feature.geometry.coordinates) {
        let a: Point | undefined;
        for (const b of simplify(path.map(project))) {
          if (
            a &&
            Math.max(a.x, b.x) >= -8 &&
            Math.min(a.x, b.x) <= size.x + 8 &&
            Math.max(a.y, b.y) >= -8 &&
            Math.min(a.y, b.y) <= size.y + 8
          )
            segments.push({ label: feature.properties.label, a, b });
          a = b;
        }
      }
  return segments;
}
export function routesNearPoint(
  segments: ProjectedSegment[],
  point: Point,
  tolerance = 8,
) {
  const found = new Map<string, number>();
  for (const { label, a, b } of segments) {
    if (
      point.x < Math.min(a.x, b.x) - tolerance ||
      point.x > Math.max(a.x, b.x) + tolerance ||
      point.y < Math.min(a.y, b.y) - tolerance ||
      point.y > Math.max(a.y, b.y) + tolerance
    )
      continue;
    const dx = b.x - a.x,
      dy = b.y - a.y;
    const t =
      dx || dy
        ? Math.max(
            0,
            Math.min(
              1,
              ((point.x - a.x) * dx + (point.y - a.y) * dy) /
                (dx * dx + dy * dy),
            ),
          )
        : 0;
    const distance = Math.hypot(point.x - a.x - t * dx, point.y - a.y - t * dy);
    if (distance <= tolerance)
      found.set(label, Math.min(found.get(label) ?? Infinity, distance));
  }
  return [...found]
    .sort(([a, da], [b, db]) => da - db || a.localeCompare(b))
    .map(([label]) => label);
}
export function routePaint(
  label: string,
  focus: string | null,
  area = false,
  overview = false,
) {
  if (overview) return { weight: 2.5, opacity: 0.45, casing: false };
  if (area && focus !== null && focus !== label)
    return { weight: 2.5, opacity: 0.2, casing: false };
  return focus === null
    ? { weight: 4, opacity: 0.75, casing: true }
    : focus === label
      ? { weight: 5, opacity: 0.85, casing: true }
      : { weight: 3, opacity: 0.35, casing: false };
}
export function casingColor(color: string) {
  const channels = [1, 3, 5]
    .map((i) => parseInt(color.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  const luminance =
    channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
  return luminance > 0.55 ? "#3b4648" : "#ffffff";
}
