import { describe, expect, it } from "vitest";
import {
  availableRouteLabels,
  effectiveRouteFocus,
  projectRoutes,
  routesNearPoint,
  routePaint,
  casingColor,
} from "./routeFocus";
import type { RouteCollection } from "./api/network";
function fixture(): RouteCollection[] {
  return [
    {
      features: [
        {
          properties: { label: "A" },
          geometry: {
            coordinates: [
              [
                [0, 10],
                [100, 10],
              ],
              [
                [0, 10],
                [100, 10],
              ],
            ],
          },
        },
        {
          properties: { label: "B" },
          geometry: {
            coordinates: [
              [
                [0, 10],
                [100, 10],
              ],
            ],
          },
        },
        {
          properties: { label: "C" },
          geometry: {
            coordinates: [
              [
                [0, 40],
                [100, 40],
              ],
            ],
          },
        },
        { properties: { label: "unavailable" }, geometry: { coordinates: [] } },
      ],
    },
  ] as RouteCollection[];
}
describe("Foco e escolha de percursos", () => {
  it("finds shared lines regardless of draw order and deduplicates senses and variants", () => {
    const segments = projectRoutes(fixture(), ([x, y]) => ({ x, y }), {
      x: 120,
      y: 80,
    });
    expect(routesNearPoint(segments, { x: 50, y: 17 })).toEqual(["A", "B"]);
    expect(routesNearPoint(segments.reverse(), { x: 50, y: 17 })).toEqual([
      "A",
      "B",
    ]);
    expect(routesNearPoint(segments, { x: 50, y: 40 })).toEqual(["C"]);
    expect(routesNearPoint(segments, { x: 50, y: 25 })).toEqual([]);
    expect(routesNearPoint(segments, { x: 109, y: 10 })).toEqual([]);
    expect(routesNearPoint(segments, { x: 108, y: 10 })).toEqual(["A", "B"]);
  });
  it("reprojects correctly after navigation and never connects distinct segments", () => {
    const data = fixture();
    const original = JSON.stringify(data);
    const shifted = projectRoutes(
      data,
      ([x, y]) => ({ x: x + 200, y: y + 100 }),
      { x: 400, y: 200 },
    );
    expect(routesNearPoint(shifted, { x: 250, y: 110 })).toEqual(["A", "B"]);
    expect(routesNearPoint(shifted, { x: 50, y: 10 })).toEqual([]);
    expect(
      projectRoutes(data, ([x, y]) => ({ x: x + 200, y }), { x: 100, y: 80 }),
    ).toEqual([]);
    expect(JSON.stringify(data)).toBe(original);
    const disconnected = [
      {
        features: [
          {
            properties: { label: "A" },
            geometry: {
              coordinates: [
                [
                  [0, 10],
                  [10, 10],
                ],
                [
                  [90, 10],
                  [100, 10],
                ],
              ],
            },
          },
        ],
      },
    ] as RouteCollection[];
    expect(
      routesNearPoint(
        projectRoutes(disconnected, ([x, y]) => ({ x, y }), { x: 120, y: 80 }),
        { x: 50, y: 10 },
      ),
    ).toEqual([]);
  });
  it("keeps all mode, falls back to an available selection and excludes missing geometry", () => {
    const available = availableRouteLabels(fixture());
    expect([...available]).toEqual(["A", "B", "C"]);
    expect(effectiveRouteFocus("B", ["A", "B", "C"], available)).toBe("B");
    expect(
      effectiveRouteFocus("removed", ["A", "B", "missing"], available),
    ).toBe("B");
    expect(effectiveRouteFocus(null, ["A", "B"], available)).toBeNull();
    expect(effectiveRouteFocus("A", [], available)).toBeNull();
  });
  it("emphasizes the focused line and gives yellow a contrasting narrow casing", () => {
    expect(routePaint("A", "A")).toEqual({
      weight: 5,
      opacity: 0.85,
      casing: true,
    });
    expect(routePaint("B", "A").opacity).toBeLessThan(
      routePaint("A", "A").opacity,
    );
    expect(routePaint("A", null)).toEqual(routePaint("B", null));
    expect(casingColor("#FFD100")).toBe("#3b4648");
    expect(casingColor("#002F6C")).toBe("#ffffff");
  });
});
