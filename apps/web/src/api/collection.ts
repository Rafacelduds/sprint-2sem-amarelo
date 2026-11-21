import { collectionStatusOperationsCollectionGet, type CollectionStatus } from "@amarelo/api-client";
export type { CollectionStatus };
const baseUrl = new URL(import.meta.env.VITE_API_URL ?? "/api", window.location.origin).href.replace(/\/$/, "");

export async function getCollection(token: string, signal: AbortSignal) {
  const result = await collectionStatusOperationsCollectionGet({
    baseUrl, signal, headers: { Authorization: `Bearer ${token}` },
    cache: "no-store", throwOnError: false,
  });
  if (result.response.status === 401 || result.response.status === 403) throw new Error("unauthorized");
  if (!result.response.ok || !result.data) throw new Error("unavailable");
  return result.data;
}
