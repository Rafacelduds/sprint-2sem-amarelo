import {
  scheduleCatalogSchedulesGet,
  scheduleDeparturesSchedulesRunIdDeparturesGet,
} from "@amarelo/api-client";
export type { ScheduleCatalog, ScheduleDepartures, ScheduleRun } from "@amarelo/api-client";

const baseUrl = new URL(import.meta.env.VITE_API_URL ?? "/api", window.location.origin).href.replace(/\/$/, "");
export const schedulePageSize = 100;

export async function getSchedules(day: string, signal: AbortSignal) {
  const result = await scheduleCatalogSchedulesGet({
    baseUrl, query: { day }, signal, cache: "no-store", throwOnError: true,
  });
  if (result.data.day !== day) throw new Error("Dia divergente");
  return result.data;
}

export type DepartureQuery = {
  day: string; run: string; line: string; direction: string; offset: number; revision: number;
};
export async function getDepartures(query: DepartureQuery, signal: AbortSignal) {
  const result = await scheduleDeparturesSchedulesRunIdDeparturesGet({
    baseUrl, path: { run_id: query.run },
    query: { line: query.line, direction: query.direction || undefined,
      offset: query.offset, limit: schedulePageSize },
    signal, cache: "no-store", throwOnError: true,
  });
  if (result.data.run.run_id !== query.run || result.data.run.service_date !== query.day
    || result.data.line.line !== query.line || result.data.offset !== query.offset
    || (result.data.direction ?? "") !== query.direction) throw new Error("Resultado divergente");
  return result.data;
}
