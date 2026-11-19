import { afterEach, describe, expect, it, vi } from "vitest";
import { colorSegments } from "./clusters";
import { readVisual, DEFAULT_VISUAL, VISUAL_KEY } from "./visualization";
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
    expect(readVisual()).toEqual(visual);
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
