import type { Snapshot, Vehicle } from "@amarelo/api-client";
export type { Snapshot, Vehicle };

export async function getPositions(signal: AbortSignal): Promise<Snapshot> {
  const base = import.meta.env.VITE_API_URL ?? "/api";
  const response = await fetch(`${base}/vehicles/positions`, {
    signal,
    cache: "no-store",
  });
  if (!response.ok)
    throw new Error("Não foi possível atualizar as posições dos ônibus.");
  return response.json() as Promise<Snapshot>;
}
