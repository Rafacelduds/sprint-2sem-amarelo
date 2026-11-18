import type { NetworkCatalog, RouteCollection } from "@amarelo/api-client";
export type { NetworkCatalog, RouteCollection };
const base = import.meta.env.VITE_API_URL ?? "/api";
export async function getCatalog(signal: AbortSignal): Promise<NetworkCatalog> {
  const response = await fetch(`${base}/network/catalog`, {
    signal,
    cache: "no-cache",
  });
  if (!response.ok) throw new Error("Catálogo indisponível");
  return response.json() as Promise<NetworkCatalog>;
}
export async function getRoute(
  id: number,
  version: string,
  signal: AbortSignal,
): Promise<RouteCollection> {
  const response = await fetch(
    `${base}/network/routes/${id}?version=${encodeURIComponent(version)}`,
    { signal },
  );
  if (!response.ok) throw new Error("Percurso indisponível");
  return response.json() as Promise<RouteCollection>;
}
