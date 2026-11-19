export type Visualization = {
  mode: "clusters" | "density" | "mixed";
  composition: "proportional" | "equal";
  groupScale: number;
  busDiameter: number;
};
export const VISUAL_KEY = "observaonibus.map.visual.v1";
export const DEFAULT_VISUAL: Visualization = {
  mode: "clusters",
  composition: "proportional",
  groupScale: 1,
  busDiameter: 9,
};
export function readVisual(): Visualization {
  try {
    const value = JSON.parse(window.localStorage.getItem(VISUAL_KEY) ?? "null");
    if (
      !value ||
      !["clusters", "density", "mixed"].includes(value.mode) ||
      !["proportional", "equal"].includes(value.composition) ||
      !Number.isFinite(value.groupScale) ||
      value.groupScale < 1 ||
      value.groupScale > 1.5 ||
      !Number.isInteger(value.busDiameter) ||
      value.busDiameter < 9 ||
      value.busDiameter > 18
    )
      return { ...DEFAULT_VISUAL };
    return {
      mode: value.mode,
      composition: value.composition,
      groupScale: value.groupScale,
      busDiameter: value.busDiameter,
    };
  } catch {
    return { ...DEFAULT_VISUAL };
  }
}
