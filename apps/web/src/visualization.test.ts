import { afterEach, describe, expect, it, vi } from "vitest";
import { colorSegments } from "./clusters";
import {
  readVisual,
  DEFAULT_VISUAL,
  VISUAL_KEY,
  heatAppearance,
} from "./visualization";
afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});
describe("Preferências e composição", () => {
  it("uses defaults for absent, corrupt, invalid or inaccessible preferences", () => {
    expect(readVisual()).toEqual(DEFAULT_VISUAL);
    for (const value of [
      "{",
      "null",
      '{"mode":"unknown"}',
      JSON.stringify({ ...DEFAULT_VISUAL, busDiameter: 100 }),
      JSON.stringify({ ...DEFAULT_VISUAL, groupScale: 0.2 }),
    ]) {
      window.localStorage.setItem(VISUAL_KEY, value);
      expect(readVisual()).toEqual(DEFAULT_VISUAL);
    }
    vi.spyOn(window.localStorage, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(readVisual()).toEqual(DEFAULT_VISUAL);
  });
  it("restores only visual preferences from this browser", () => {
    const visual = {
      mode: "mixed",
      composition: "equal",
      groupScale: 1.5,
      busDiameter: 18,
    };
    window.localStorage.setItem(
      VISUAL_KEY,
      JSON.stringify({ ...visual, selectedBus: "private" }),
    );
    expect(readVisual()).toEqual({ ...DEFAULT_VISUAL, ...visual });
  });
  it("represents frequency or presence without changing counts, including unknown colors", () => {
    const counts = { "#002F6C": 3, "#FF671F": 1, "#78838B": 0 };
    const proportion = colorSegments(counts, "proportional");
    const equal = colorSegments(counts, "equal");
    expect(proportion.map((s) => s.end - s.start)).toEqual([75, 25]);
    expect(equal.map((s) => s.end - s.start)).toEqual([50, 50]);
    expect(equal.map((s) => s.count)).toEqual([3, 1]);
    expect(counts["#002F6C"]).toBe(3);
    expect(colorSegments({}, "equal")).toEqual([]);
  });
});

it("increases heat visibility monotonically without changing the observed population", () => {
  const low = heatAppearance(25, "density");
  const normal = heatAppearance(100, "density");
  const high = heatAppearance(200, "density");
  expect(low.max).toBeGreaterThan(normal.max);
  expect(high.max).toBeLessThan(normal.max);
  expect(low.opacity).toBeLessThan(normal.opacity);
  expect(high.opacity).toBeGreaterThan(normal.opacity);
  expect(heatAppearance(100, "mixed").opacity).toBeLessThan(normal.opacity);
});
it("validates new preferences and migrates previously saved settings", () => {
  const legacy = {
    mode: "density",
    composition: "equal",
    groupScale: 1.4,
    busDiameter: 13,
  };
  window.localStorage.setItem(VISUAL_KEY, JSON.stringify(legacy));
  expect(readVisual()).toEqual({ ...DEFAULT_VISUAL, ...legacy });
  const updated = {
    ...DEFAULT_VISUAL,
    groupSizing: "uniform",
    heatIntensity: 175,
  };
  window.localStorage.setItem(VISUAL_KEY, JSON.stringify(updated));
  expect(readVisual()).toEqual(updated);
  for (const invalid of [
    { ...updated, heatIntensity: 0 },
    { ...updated, heatIntensity: 201 },
    { ...updated, groupSizing: "other" },
  ]) {
    window.localStorage.setItem(VISUAL_KEY, JSON.stringify(invalid));
    expect(readVisual()).toEqual(DEFAULT_VISUAL);
  }
});
