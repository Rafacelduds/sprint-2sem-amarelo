import { statusOperationsBackupsGet, type BackupStatus } from "@amarelo/api-client";
export type { BackupStatus };
const baseUrl = new URL(import.meta.env.VITE_API_URL ?? "/api", window.location.origin).href.replace(/\/$/, "");

export async function getBackups(token: string, signal: AbortSignal) {
  const result = await statusOperationsBackupsGet({
    baseUrl, signal, headers: { Authorization: `Bearer ${token}` },
    cache: "no-store", throwOnError: false,
  });
  if (result.response.status === 401 || result.response.status === 403) throw new Error("unauthorized");
  if (!result.response.ok || !result.data) throw new Error("unavailable");
  return result.data;
}
