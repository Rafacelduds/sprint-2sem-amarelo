import {
  dailyReliabilityReportsReliabilityDayGet,
  type ReliabilityReport,
} from "@amarelo/api-client";

export type { ReliabilityReport };
export type ReportResult =
  | { kind: "ready"; data: ReliabilityReport }
  | { kind: "unpublished" | "invalid" | "unavailable" };

const baseUrl = new URL(
  import.meta.env.VITE_API_URL ?? "/api",
  window.location.origin,
).href.replace(/\/$/, "");

export async function getReliability(day: string, signal: AbortSignal): Promise<ReportResult> {
  const result = await dailyReliabilityReportsReliabilityDayGet({
    baseUrl,
    path: { day },
    signal,
    cache: "no-store",
    throwOnError: false,
  });
  if (!result.response.ok) {
    return { kind: result.response.status === 404 ? "unpublished"
      : result.response.status === 422 ? "invalid" : "unavailable" };
  }
  if (!result.data || result.data.day !== day) throw new Error("Dia divergente na resposta");
  return { kind: "ready", data: result.data };
}
