export type Visualization = {
  mode: "clusters" | "density" | "mixed";
  composition: "proportional" | "equal";
  groupScale: number;
  busDiameter: number;
  groupSizing: "proportional" | "uniform";
  heatIntensity: number;
};
export const VISUAL_KEY = "observaonibus.map.visual.v1";
export const DEFAULT_VISUAL: Visualization = {
  mode: "clusters",
  composition: "proportional",
  groupScale: 1,
  busDiameter: 9,
  groupSizing: "proportional",
  heatIntensity: 100,
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
    // Additive migration of preferences saved before these controls existed.
    const groupSizing = value.groupSizing ?? DEFAULT_VISUAL.groupSizing;
    const heatIntensity = value.heatIntensity ?? DEFAULT_VISUAL.heatIntensity;
    if (
      !["proportional", "uniform"].includes(groupSizing) ||
      !Number.isInteger(heatIntensity) ||
      heatIntensity < 25 ||
      heatIntensity > 200
    )
      return { ...DEFAULT_VISUAL };
    return {
      groupSizing,
      heatIntensity,
      mode: value.mode,
      composition: value.composition,
      groupScale: value.groupScale,
      busDiameter: value.busDiameter,
    };
  } catch {
    return { ...DEFAULT_VISUAL };
  }
}

export function heatAppearance(intensity: number, mode: Visualization["mode"]) {
  const gain = intensity / 100;
  return {
    max: 4 / gain,
    opacity: Math.min(0.9, (mode === "mixed" ? 0.48 : 0.7) * Math.sqrt(gain)),
  };
}
