import { describe, expect, it } from "vitest";
import { gpsQuality, matchesFilters } from "./network";
import type { Vehicle } from "./api/positions";
const bus: Vehicle = {
  id: "1",
  line_id: 1,
  line: "5015-10",
  direction: 2,
  latitude: -23.5,
  longitude: -46.6,
  destination: "Terminal",
  accessible: null,
  gps_at: null,
};
describe("Qualidade e filtros", () => {
  it("treats missing, invalid and future GPS times as unknown", () => {
    const now = Date.parse("2026-11-18T12:00:00Z");
    for (const gps_at of [null, "invalid", "2026-11-18T12:00:01Z"])
      expect(gpsQuality({ ...bus, gps_at }, now)).toBe("unknown");
    expect(gpsQuality({ ...bus, gps_at: "2026-11-18T11:59:00Z" }, now)).toBe(
      "recent",
    );
    expect(gpsQuality({ ...bus, gps_at: "2026-11-18T11:58:59Z" }, now)).toBe(
      "old",
    );
  });
  it("uses only proven area mappings and combines filters as intersection", () => {
    const styles = new Map([[1, { area: 2, color: "#22599B" }]]);
    expect(matchesFilters(bus, { "5015-10": "both" }, ["2"], styles)).toBe(
      true,
    );
    expect(matchesFilters(bus, { "5015-10": 1 }, ["2"], styles)).toBe(false);
    expect(matchesFilters(bus, {}, ["8"], styles)).toBe(false);
    expect(matchesFilters(bus, {}, ["unknown"], new Map())).toBe(true);
  });
});
